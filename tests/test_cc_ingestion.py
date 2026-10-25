"""Tests for ColdChain HMAC ingestion, replay detection, and security events."""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import select

from app.cc_ingestion import ingest_telemetry
from app.models import Device, Reading, SecurityEvent
from app.security import canonical_json, hmac_sign

DEVICE_ID = "fridge-A"
SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
SECRETS = {DEVICE_ID: SECRET}


def make_signed_payload(
    dev: str = DEVICE_ID,
    seq: int = 1,
    ts: float | None = None,
    nonce: str = "nonce-001",
    secret: str = SECRET,
    temp_c: float = 4.5,
    compressor_on: bool = False,
    door_open: bool = False,
) -> bytes:
    if ts is None:
        ts = time.time()
    data = {
        "temp_c": temp_c,
        "door_open": door_open,
        "door_open_s": 0,
        "compressor_on": compressor_on,
        "lockout_s": 30,
        "power_source": "MAINS",
        "mains_present": True,
        "battery_pct": 98.0,
        "battery_v": 4.15,
        "state": "SAFE",
        "red_latched": False,
        "sim_mode": True,
    }
    d_canon = canonical_json(data)
    parts = [dev, str(seq), str(ts), nonce, d_canon]
    sig = hmac_sign(secret, parts)
    msg = {
        "v": 1,
        "dev": dev,
        "seq": seq,
        "ts": ts,
        "nonce": nonce,
        "d": data,
        "sig": sig,
    }
    return json.dumps(msg).encode()


@pytest.fixture
def cc_device(application):
    with application.state.sessions.begin() as db:
        dev = Device(device_id=DEVICE_ID, name="Cold Storage A", enabled=True)
        db.add(dev)
    return DEVICE_ID


def test_valid_telemetry_ingestion(application, cc_device):
    """Valid signed telemetry is accepted and persisted into the readings table."""
    factory = application.state.sessions
    payload = make_signed_payload(seq=10, nonce="nonce-valid-1")

    res = ingest_telemetry(factory, f"cc/{DEVICE_ID}/telemetry", payload, SECRETS)
    assert res.status == "accepted"
    assert res.accepted == 1

    with factory() as db:
        reading = db.scalar(select(Reading).where(Reading.device_id == DEVICE_ID, Reading.seq == 10))
        assert reading is not None
        assert reading.temp_c == 4.5
        assert reading.state == "SAFE"


def test_bad_hmac_signature_rejected(application, cc_device):
    """Wrong HMAC key leads to rejection and BAD_SIG security event."""
    factory = application.state.sessions
    wrong_secret = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    payload = make_signed_payload(seq=11, nonce="nonce-bad-sig", secret=wrong_secret)

    res = ingest_telemetry(factory, f"cc/{DEVICE_ID}/telemetry", payload, SECRETS)
    assert res.status == "rejected"

    with factory() as db:
        event = db.scalar(select(SecurityEvent).where(SecurityEvent.device_id == DEVICE_ID, SecurityEvent.kind == "BAD_SIG"))
        assert event is not None


def test_stale_timestamp_rejected(application, cc_device):
    """Timestamp outside ±60s window is rejected as STALE_TS."""
    factory = application.state.sessions
    stale_ts = time.time() - 120  # 2 minutes ago
    payload = make_signed_payload(seq=12, ts=stale_ts, nonce="nonce-stale")

    res = ingest_telemetry(factory, f"cc/{DEVICE_ID}/telemetry", payload, SECRETS, ts_window_s=60)
    assert res.status == "rejected"

    with factory() as db:
        event = db.scalar(select(SecurityEvent).where(SecurityEvent.device_id == DEVICE_ID, SecurityEvent.kind == "STALE_TS"))
        assert event is not None


def test_replay_nonce_rejected(application, cc_device):
    """Reusing the same nonce generates a REPLAY rejection."""
    factory = application.state.sessions
    now = time.time()
    payload1 = make_signed_payload(seq=20, ts=now, nonce="fixed-nonce-xyz")
    payload2 = make_signed_payload(seq=21, ts=now, nonce="fixed-nonce-xyz")

    res1 = ingest_telemetry(factory, f"cc/{DEVICE_ID}/telemetry", payload1, SECRETS)
    assert res1.status == "accepted"

    res2 = ingest_telemetry(factory, f"cc/{DEVICE_ID}/telemetry", payload2, SECRETS)
    assert res2.status == "rejected"

    with factory() as db:
        event = db.scalar(select(SecurityEvent).where(SecurityEvent.device_id == DEVICE_ID, SecurityEvent.kind == "REPLAY"))
        assert event is not None


def test_duplicate_seq_idempotent(application, cc_device):
    """Same device and sequence number is deduplicated cleanly."""
    factory = application.state.sessions
    now = time.time()
    payload1 = make_signed_payload(seq=30, ts=now, nonce="nonce-seq-30a")
    payload2 = make_signed_payload(seq=30, ts=now, nonce="nonce-seq-30b")

    res1 = ingest_telemetry(factory, f"cc/{DEVICE_ID}/telemetry", payload1, SECRETS)
    assert res1.status == "accepted"

    res2 = ingest_telemetry(factory, f"cc/{DEVICE_ID}/telemetry", payload2, SECRETS)
    assert res2.status == "duplicate"
    assert res2.duplicates == 1
