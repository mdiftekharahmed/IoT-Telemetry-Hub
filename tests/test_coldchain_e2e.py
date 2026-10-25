"""End-to-End ColdChain Integration Tests.

Validates:
1. End-to-end telemetry flow: HMAC ingest → DB reading → heat budget update → audit log.
2. Security enforcement: tampered signatures rejected and logged to security_events.
3. Cryptographic hash-chain integrity & tamper detection:
   - Normal chain verifies cleanly.
   - Modifying any past block causes verify_chain to detect and pinpoint first_broken_idx.
4. Offline sync batch ingestion:
   - Ingesting a bulk envelope of 60 buffered readings.
   - Re-syncing the same buffer is idempotent (detects duplicates without failing).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text

import app.audit as audit_mod
from app.budget_engine import update_exposure
from app.cc_ingestion import ingest_sync, ingest_telemetry
from app.models import AuditLog, Batch, Device, Fridge, Reading, SecurityEvent
from app.security import canonical_json, hmac_sign

DEVICE_ID = "fridge-A"
SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
SECRETS = {DEVICE_ID: SECRET}


def make_payload(seq: int, nonce: str, temp_c: float = 4.2, secret: str = SECRET) -> bytes:
    ts = time.time()
    data = {
        "temp_c": temp_c,
        "door_open": False,
        "door_open_s": 0,
        "compressor_on": False,
        "lockout_s": 45,
        "power_source": "MAINS",
        "mains_present": True,
        "battery_pct": 100.0,
        "battery_v": 4.20,
        "state": "SAFE",
        "red_latched": False,
        "sim_mode": True,
    }
    d_canon = canonical_json(data)
    sig = hmac_sign(secret, [DEVICE_ID, str(seq), str(ts), nonce, d_canon])
    return json.dumps({
        "v": 1, "dev": DEVICE_ID, "seq": seq, "ts": ts,
        "nonce": nonce, "d": data, "sig": sig,
    }).encode()


@pytest.fixture
def e2e_setup(application):
    factory = application.state.sessions
    with factory.begin() as db:
        dev = Device(device_id=DEVICE_ID, name="Pharma Hub Main", enabled=True)
        db.add(dev)
        db.flush()

        fridge = Fridge(name="Main Vaccine Fridge", capacity_slots=20, device_id=DEVICE_ID)
        db.add(fridge)
        db.flush()

        batch = Batch(
            code="E2E-VAX-01",
            vaccine_name="EpiVac",
            qty=150,
            fridge_id=fridge.id,
            status="OK",
            exposure_weighted_min=0.0,
            qr_token="qr-e2e-token-01",
        )
        db.add(batch)
        db.flush()
        f_id, b_id = fridge.id, batch.id

    return {"factory": factory, "fridge_id": f_id, "batch_id": b_id}


def test_e2e_telemetry_and_budget_flow(e2e_setup):
    """End-to-end: verified telemetry ingestion updates readings and budget exposure."""
    factory = e2e_setup["factory"]
    fridge_id = e2e_setup["fridge_id"]
    batch_id = e2e_setup["batch_id"]

    # 1. Ingest valid telemetry reading
    payload = make_payload(seq=101, nonce="e2e-nonce-101", temp_c=9.5)
    res = ingest_telemetry(factory, f"cc/{DEVICE_ID}/telemetry", payload, SECRETS)
    assert res.status == "accepted"

    # 2. Trigger heat budget engine for this reading
    with factory.begin() as db:
        update_exposure(db, fridge_id, temp_c=9.5, ts=datetime.now(tz=UTC))

    # 3. Verify reading and batch state in database
    with factory() as db:
        reading = db.scalar(select(Reading).where(Reading.device_id == DEVICE_ID, Reading.seq == 101))
        assert reading is not None
        assert reading.temp_c == 9.5

        batch = db.get(Batch, batch_id)
        assert batch is not None
        assert batch.status in ("OK", "AT_RISK")


def test_security_event_on_tampered_payload(e2e_setup):
    """Payload with tampered content fails HMAC and creates a SecurityEvent."""
    factory = e2e_setup["factory"]
    bad_payload = make_payload(seq=201, nonce="e2e-nonce-bad", temp_c=5.0,
                               secret="ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff")

    res = ingest_telemetry(factory, f"cc/{DEVICE_ID}/telemetry", bad_payload, SECRETS)
    assert res.status == "rejected"

    with factory() as db:
        sec_event = db.scalar(
            select(SecurityEvent).where(SecurityEvent.device_id == DEVICE_ID, SecurityEvent.kind == "BAD_SIG")
        )
        assert sec_event is not None


def test_audit_hash_chain_tamper_detection(e2e_setup):
    """Modifying a historical entry in the hash chain is pinpointed by verify_chain."""
    factory = e2e_setup["factory"]

    # Append 5 legitimate audit entries
    with factory.begin() as db:
        for i in range(5):
            audit_mod.append(db, actor=f"user_{i}", action=f"ACTION_{i}", payload={"step": i})

    # Verify initial valid chain
    with factory() as db:
        res = audit_mod.verify_chain(db)
        assert res["valid"] is True
        assert res["checked"] >= 5
        assert res["first_broken_idx"] is None

    # Tamper with an existing entry's payload
    with factory.begin() as db:
        target = db.scalar(select(AuditLog).where(AuditLog.action == "ACTION_2"))
        assert target is not None
        tampered_idx = target.idx
        # Directly modify payload without updating the cryptographic hash
        target.payload_json = json.dumps({"step": 9999, "tampered": True})

    # Chain verification MUST fail and identify tampered_idx
    with factory() as db:
        tamper_res = audit_mod.verify_chain(db)
        assert tamper_res["valid"] is False
        assert tamper_res["first_broken_idx"] == tampered_idx


def test_offline_sync_bulk_and_idempotency(e2e_setup):
    """Bulk upload of buffered offline readings is accepted, and re-syncing is idempotent."""
    factory = e2e_setup["factory"]

    # Construct offline sync envelope with 60 readings
    readings = []
    base_ts = time.time() - 3600  # 1 hour ago
    for i in range(1, 61):
        readings.append({
            "seq": 1000 + i,
            "ts": base_ts + (i * 5),
            "d": {
                "temp_c": 4.0 + (i % 3) * 0.1,
                "door_open": False,
                "compressor_on": True if i % 10 < 5 else False,
                "mains_present": True,
                "power_source": "MAINS",
                "state": "SAFE",
            },
        })

    sync_envelope = json.dumps({
        "dev": DEVICE_ID,
        "ts": time.time(),
        "nonce": "bulk-sync-nonce-001",
        "readings": readings,
    }).encode()

    # First sync: all 60 accepted
    res1 = ingest_sync(factory, f"cc/{DEVICE_ID}/sync", sync_envelope, SECRETS)
    assert res1.status == "accepted"
    assert res1.accepted == 60
    assert res1.duplicates == 0

    with factory() as db:
        count = db.scalar(
            select(func.count()).select_from(Reading).where(
                Reading.device_id == DEVICE_ID,
                Reading.seq >= 1001,
                Reading.seq <= 1060,
            )
        )
        assert count == 60

    # Second sync: new nonce but same sequences -> all 60 detected as duplicates
    sync_envelope_dupe = json.dumps({
        "dev": DEVICE_ID,
        "ts": time.time(),
        "nonce": "bulk-sync-nonce-002",
        "readings": readings,
    }).encode()

    res2 = ingest_sync(factory, f"cc/{DEVICE_ID}/sync", sync_envelope_dupe, SECRETS)
    assert res2.status == "accepted"
    assert res2.accepted == 0
    assert res2.duplicates == 60
