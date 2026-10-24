"""Seed demo data for ColdChain hackathon presentation.

Creates: 2 fridges, 2 devices, 5 batches, 3 users (admin/pharmacist/inspector),
2 hours of synthetic readings, and a genesis audit log entry.

Usage:
    python -m scripts.seed_coldchain
    # or via Docker:
    docker compose run --rm api python -m scripts.seed_coldchain
"""

from __future__ import annotations

import json
import secrets
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Ensure the project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import build_engine, session_factory
from app.models import (
    Batch, BatchMovement, Device, Fridge, Reading, User, utcnow,
)
import app.audit as audit_mod


SETTINGS = Settings()


def _hash_password(pw: str) -> str:
    from pwdlib import PasswordHash
    return PasswordHash.recommended().hash(pw)


def seed(db: Session):
    print("Seeding ColdChain demo data...")

    # ── Users ──────────────────────────────────────────────────────────────────
    users = [
        User(username="admin",       bcrypt_hash=_hash_password("admin123"),       role="admin"),
        User(username="pharmacist1", bcrypt_hash=_hash_password("pharma123"),      role="pharmacist"),
        User(username="inspector1",  bcrypt_hash=_hash_password("inspect123"),     role="inspector"),
    ]
    for u in users:
        existing = db.query(User).filter_by(username=u.username).first()
        if not existing:
            db.add(u)
    db.flush()
    print(f"  Users: {[u.username for u in users]}")

    # ── Devices ────────────────────────────────────────────────────────────────
    devices = [
        Device(device_id="fridge-A", name="Fridge A (Main Ward)", enabled=True,
               mqtt_password=secrets.token_urlsafe(12)),
        Device(device_id="fridge-B", name="Fridge B (Pharmacy)", enabled=True,
               mqtt_password=secrets.token_urlsafe(12)),
    ]
    for d in devices:
        if not db.get(Device, d.device_id):
            db.add(d)
    db.flush()

    # ── Fridges ────────────────────────────────────────────────────────────────
    fridges: list[Fridge] = []
    for dev in devices:
        f = db.query(Fridge).filter_by(device_id=dev.device_id).first()
        if not f:
            f = Fridge(
                name=dev.name,
                capacity_slots=8,
                location="Block C, Ground Floor",
                device_id=dev.device_id,
            )
            db.add(f)
            db.flush()
        fridges.append(f)

        # Link device → fridge
        d = db.get(Device, dev.device_id)
        d.fridge_id = f.id
    db.flush()
    print(f"  Fridges: {[f.name for f in fridges]}")

    # ── Batches ────────────────────────────────────────────────────────────────
    batch_specs = [
        ("BCH-001", "COVID-19 Vaccine",   500, date(2025, 6, 1),  fridges[0].id, 0.0),
        ("BCH-002", "Influenza Vaccine",  200, date(2025, 3, 15), fridges[0].id, 45.0),  # AT_RISK
        ("BCH-003", "Hepatitis B",        150, date(2025, 9, 1),  fridges[0].id, 0.0),
        ("BCH-004", "Insulin (Regular)",  300, date(2025, 1, 30), fridges[1].id, 0.0),
        ("BCH-005", "MMR Vaccine",        100, date(2025, 7, 15), fridges[1].id, 58.0),  # near Discard
    ]
    for code, name, qty, exp, fid, exposure in batch_specs:
        existing = db.query(Batch).filter_by(code=code).first()
        if not existing:
            remaining = max(0.0, 100.0 * (1.0 - exposure / 60.0))
            if remaining == 0.0:
                status, latched = "DISCARD", True
            elif remaining < 20.0:
                status, latched = "AT_RISK", False
            else:
                status, latched = "OK", False
            db.add(Batch(
                code=code, vaccine_name=name, qty=qty,
                expiry_date=exp, fridge_id=fid,
                exposure_weighted_min=exposure,
                status=status, discard_latched=latched,
                qr_token=secrets.token_urlsafe(32),
            ))
    db.flush()
    print(f"  Batches: {[s[0] for s in batch_specs]}")

    # ── Synthetic readings (2 hours, 5-s intervals) ───────────────────────────
    from app.ml.simulator import SimParams, simulate_run
    for dev_id, fridge in [("fridge-A", fridges[0]), ("fridge-B", fridges[1])]:
        existing = db.query(Reading).filter_by(device_id=dev_id).count()
        if existing > 0:
            print(f"  Readings for {dev_id} already exist, skipping")
            continue
        params = SimParams(T_amb=22.0, duration_s=7200.0)
        df = simulate_run(params, seed=hash(dev_id) % 1000)
        base_ts = datetime.now(UTC) - timedelta(hours=2)
        for i, row in df.iterrows():
            ts = base_ts + timedelta(seconds=row["t_s"])
            db.add(Reading(
                device_id=dev_id, seq=i + 1, ts=ts,
                temp_c=row["temp_c"],
                door_open=bool(row["door_open"]),
                door_open_s=int(row["door_open_s"]),
                compressor_on=bool(row["compressor_on"]),
                lockout_s=int(row["lockout_s"]),
                state=row["state"],
                sim_mode=True,
                ingested_at=utcnow(),
            ))
        print(f"  Readings for {dev_id}: {len(df)} rows")
    db.flush()

    # ── Audit log genesis ─────────────────────────────────────────────────────
    audit_mod.append(db, actor="system", action="SEED_COMPLETE", payload={
        "fridges": len(fridges), "batches": len(batch_specs), "users": len(users),
    })
    print("  Audit genesis entry written")

    db.commit()
    print("✓ Seed complete.")


if __name__ == "__main__":
    engine  = build_engine(SETTINGS.database_url)
    factory = session_factory(engine)
    with factory() as db:
        seed(db)
