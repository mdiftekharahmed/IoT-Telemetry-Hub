"""ColdChain ingest: HMAC verify → nonce dedup → seq dedup → store reading.

Security check order (per spec §1.2):
  1. Allow-list fields
  2. Timestamp within ±window of server time
  3. HMAC valid (constant-time)
  4. Nonce not seen before
  5. INSERT with UNIQUE(device_id, seq) → ON CONFLICT DO NOTHING
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Device, Nonce, Reading, SecurityEvent, utcnow
from app.security import canonical_json, hmac_verify

logger = logging.getLogger(__name__)

# MQTT topic patterns
CC_TELEMETRY = re.compile(r"^cc/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/telemetry$")
CC_SYNC      = re.compile(r"^cc/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/sync$")
CC_EVENT     = re.compile(r"^cc/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/event$")
CC_STATUS    = re.compile(r"^cc/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/status$")
CC_ACK       = re.compile(r"^cc/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/ack$")

MAX_PAYLOAD_BYTES = 32_768
NONCE_PURGE_WINDOW = timedelta(minutes=15)

# Top-level fields allowed in a ColdChain telemetry message
ALLOWED_TOP_FIELDS = {"v", "dev", "seq", "ts", "nonce", "d", "sig"}

# Fields allowed inside the "d" data object
ALLOWED_DATA_FIELDS = {
    "temp_c", "door_open", "door_open_s", "compressor_on", "lockout_s",
    "power_source", "mains_present", "battery_pct", "battery_v",
    "state", "red_latched", "sim_mode",
}


class SecurityRejection(Exception):
    def __init__(self, kind: str, detail: str = ""):
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind}: {detail}")


@dataclass
class IngestResult:
    status: str
    accepted: int = 0
    duplicates: int = 0


def _log_security_event(db: Session, device_id: str | None, kind: str, excerpt: str) -> None:
    db.add(SecurityEvent(device_id=device_id, kind=kind, raw_excerpt=excerpt[:512]))
    db.flush()


def _parse_and_validate_payload(raw: bytes) -> dict:
    """Parse JSON, check for duplicate keys, and verify top-level field allow-list."""
    seen: set[str] = set()

    def _hook(pairs):
        result = {}
        for k, v in pairs:
            if k in seen:
                raise ValueError(f"duplicate JSON key: {k}")
            seen.add(k)
            result[k] = v
        return result

    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_hook)
    extra = set(data.keys()) - ALLOWED_TOP_FIELDS
    if extra:
        raise SecurityRejection("BAD_FIELD", f"unexpected fields: {extra}")
    return data


def _check_timestamp(ts_epoch: int | float, window_s: int) -> None:
    now = time.time()
    if abs(now - float(ts_epoch)) > window_s:
        raise SecurityRejection("STALE_TS", f"delta={now - float(ts_epoch):.1f}s")


def _check_hmac(device_id: str, secret: str, msg: dict) -> None:
    d_canon = canonical_json({k: v for k, v in msg["d"].items()
                               if k in ALLOWED_DATA_FIELDS})
    parts = [msg["dev"], str(msg["seq"]), str(msg["ts"]), msg["nonce"], d_canon]
    if not hmac_verify(secret, parts, msg.get("sig", "")):
        raise SecurityRejection("BAD_SIG")


def _check_nonce(db: Session, device_id: str, nonce: str) -> None:
    # Purge stale nonces first
    cutoff = utcnow() - NONCE_PURGE_WINDOW
    db.query(Nonce).filter(Nonce.seen_at < cutoff).delete(synchronize_session=False)
    existing = db.scalar(
        select(Nonce).where(Nonce.device_id == device_id, Nonce.nonce == nonce)
    )
    if existing:
        raise SecurityRejection("REPLAY", f"nonce={nonce}")
    db.add(Nonce(device_id=device_id, nonce=nonce))


def _build_reading(device_id: str, seq: int, ts_epoch: int | float, d: dict,
                   ingested_at: datetime) -> Reading:
    ts = datetime.fromtimestamp(float(ts_epoch), tz=UTC)
    return Reading(
        device_id=device_id,
        seq=seq,
        ts=ts,
        temp_c=float(d.get("temp_c", 0.0)),
        door_open=bool(d.get("door_open", False)),
        door_open_s=int(d.get("door_open_s", 0)),
        compressor_on=bool(d.get("compressor_on", False)),
        lockout_s=int(d.get("lockout_s", 0)),
        power_source=str(d.get("power_source", "MAINS"))[:16],
        mains_present=bool(d.get("mains_present", True)),
        battery_pct=d.get("battery_pct"),
        battery_v=d.get("battery_v"),
        state=str(d.get("state", "SAFE"))[:16],
        red_latched=bool(d.get("red_latched", False)),
        sim_mode=bool(d.get("sim_mode", False)),
        ts_source="ntp",
        ingested_at=ingested_at,
    )


def ingest_telemetry(
    factory: sessionmaker[Session],
    topic: str,
    payload: bytes,
    device_secrets: dict[str, str],
    ts_window_s: int = 60,
) -> IngestResult:
    match = CC_TELEMETRY.fullmatch(topic)
    if not match or len(payload) > MAX_PAYLOAD_BYTES:
        raise SecurityRejection("BAD_FIELD", "invalid topic or oversized payload")

    device_id = match.group(1)

    with factory() as db:
        with db.begin():
            try:
                msg = _parse_and_validate_payload(payload)
            except (UnicodeError, ValueError, SecurityRejection) as exc:
                kind = exc.kind if isinstance(exc, SecurityRejection) else "BAD_FIELD"
                _log_security_event(db, device_id, kind, payload[:256].decode(errors="replace"))
                return IngestResult("rejected")

            device = db.get(Device, device_id)
            if device is None or not device.enabled:
                _log_security_event(db, device_id, "UNKNOWN_DEVICE", device_id)
                return IngestResult("device_rejected")

            secret = device_secrets.get(device_id)
            if not secret:
                _log_security_event(db, device_id, "NO_SECRET", device_id)
                return IngestResult("rejected")

            try:
                _check_timestamp(msg["ts"], ts_window_s)
                _check_hmac(device_id, secret, msg)
                _check_nonce(db, device_id, msg["nonce"])
            except SecurityRejection as exc:
                _log_security_event(db, device_id, exc.kind, exc.detail)
                return IngestResult("rejected")

            ingested_at = utcnow()
            reading = _build_reading(device_id, int(msg["seq"]), msg["ts"],
                                     msg.get("d", {}), ingested_at)
            try:
                db.add(reading)
                db.flush()
            except IntegrityError:
                db.rollback()
                return IngestResult("duplicate", duplicates=1)

            # Update device heartbeat
            device.last_seen = ingested_at
            device.last_seq  = int(msg["seq"])

    logger.info("cc/telemetry accepted device=%s seq=%s", device_id, msg["seq"])
    return IngestResult("accepted", accepted=1)


def ingest_sync(
    factory: sessionmaker[Session],
    topic: str,
    payload: bytes,
    device_secrets: dict[str, str],
    ts_window_s: int = 60,
) -> IngestResult:
    """Process a buffered sync batch from an offline node."""
    match = CC_SYNC.fullmatch(topic)
    if not match or len(payload) > MAX_PAYLOAD_BYTES:
        raise SecurityRejection("BAD_FIELD", "invalid sync topic or oversized payload")

    device_id = match.group(1)

    with factory() as db:
        with db.begin():
            try:
                envelope = json.loads(payload.decode("utf-8"))
            except Exception:
                _log_security_event(db, device_id, "BAD_FIELD", "unparseable sync")
                return IngestResult("rejected")

            device = db.get(Device, device_id)
            if device is None or not device.enabled:
                return IngestResult("device_rejected")

            secret = device_secrets.get(device_id)
            if not secret:
                return IngestResult("rejected")

            # Envelope timestamp check (the fresh ts/nonce are on the envelope)
            try:
                _check_timestamp(envelope["ts"], ts_window_s)
                _check_nonce(db, device_id, envelope["nonce"])
            except SecurityRejection as exc:
                _log_security_event(db, device_id, exc.kind, exc.detail)
                return IngestResult("rejected")

            readings = sorted(envelope.get("readings", []), key=lambda r: r["seq"])
            accepted = duplicates = 0
            ingested_at = utcnow()

            for item in readings:
                r = _build_reading(device_id, int(item["seq"]), item["ts"],
                                   item.get("d", {}), ingested_at)
                try:
                    db.add(r)
                    db.flush()
                    accepted += 1
                except IntegrityError:
                    db.rollback()
                    duplicates += 1

            if accepted > 0:
                device.last_seen = ingested_at

    logger.info("cc/sync device=%s accepted=%d duplicates=%d", device_id, accepted, duplicates)
    return IngestResult("accepted", accepted=accepted, duplicates=duplicates)
