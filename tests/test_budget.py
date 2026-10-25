"""Unit tests for the heat-exposure budget engine and discard latch logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.budget_engine import exposure_weight, reset_discard, update_exposure
from app.models import AuditLog, Batch, Fridge


def test_exposure_weight():
    """Weight thresholds: 0 (<=8), 1 (8 < T <= 12), 2 (>12)."""
    assert exposure_weight(3.0) == 0.0
    assert exposure_weight(8.0) == 0.0
    assert exposure_weight(8.1) == 1.0
    assert exposure_weight(10.0) == 1.0
    assert exposure_weight(12.0) == 1.0
    assert exposure_weight(12.1) == 2.0
    assert exposure_weight(15.0) == 2.0


def test_budget_accumulation_and_discard_latch(application):
    """Accruing 60 weighted minutes triggers DISCARD and latches red."""
    factory = application.state.sessions

    with factory.begin() as db:
        fridge = Fridge(name="BudgetFridge", capacity_slots=5, device_id="fridge-B")
        db.add(fridge)
        db.flush()

        batch = Batch(
            code="BATCH-BUDGET-1",
            vaccine_name="Rotavirus",
            qty=40,
            fridge_id=fridge.id,
            status="OK",
            exposure_weighted_min=0.0,
            qr_token="qr-budget-1",
        )
        db.add(batch)
        db.flush()
        fridge_id = fridge.id
        batch_id = batch.id

    # 1. 10 minutes at 10°C (weight 1.0) -> 10 weighted minutes
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    with factory.begin() as db:
        update_exposure(db, fridge_id, temp_c=10.0, ts=t0)

    t1 = t0 + timedelta(minutes=10)
    with factory.begin() as db:
        # Note: DT_CAP_MINUTES is 2.0 min, so let's step in 2-minute intervals to simulate readings
        for step in range(1, 6):
            step_ts = t0 + timedelta(minutes=step * 2)
            update_exposure(db, fridge_id, temp_c=10.0, ts=step_ts)

    with factory() as db:
        b = db.get(Batch, batch_id)
        assert round(b.exposure_weighted_min, 1) == 10.0
        assert b.status == "OK"
        assert b.discard_latched is False

    # 2. Add enough exposure to cross the 60-minute threshold using 14°C (weight 2.0)
    # Need 50 more weighted minutes -> 25 real minutes at weight 2.0
    current_t = t1
    with factory.begin() as db:
        for step in range(1, 14):  # 13 steps * 2 min = 26 min * 2.0 = 52 weighted min
            current_t = t1 + timedelta(minutes=step * 2)
            update_exposure(db, fridge_id, temp_c=14.0, ts=current_t)

    with factory() as db:
        b = db.get(Batch, batch_id)
        assert b.exposure_weighted_min >= 60.0
        assert b.status == "DISCARD"
        assert b.discard_latched is True

        # Check audit log contains BATCH_DISCARD
        audit_entry = db.scalar(select(AuditLog).where(AuditLog.action == "BATCH_DISCARD"))
        assert audit_entry is not None

    # 3. Cooling back down to 4°C must NOT clear the discard latch
    cool_t = current_t + timedelta(minutes=5)
    with factory.begin() as db:
        update_exposure(db, fridge_id, temp_c=4.0, ts=cool_t)

    with factory() as db:
        b = db.get(Batch, batch_id)
        assert b.status == "DISCARD"
        assert b.discard_latched is True


def test_admin_reset_discard(application):
    """Admin reset clears the discard latch and restores status to AT_RISK."""
    factory = application.state.sessions

    with factory.begin() as db:
        fridge = Fridge(name="ResetFridge", capacity_slots=5, device_id="fridge-C")
        db.add(fridge)
        db.flush()

        batch = Batch(
            code="BATCH-RESET-1",
            vaccine_name="Measles",
            qty=25,
            fridge_id=fridge.id,
            status="DISCARD",
            discard_latched=True,
            exposure_weighted_min=62.0,
            qr_token="qr-reset-1",
        )
        db.add(batch)
        db.flush()
        batch_id = batch.id

    with factory.begin() as db:
        reset_discard(db, batch_id, actor="admin_alice", reason="Supervisor approved post-inspection")

    with factory() as db:
        b = db.get(Batch, batch_id)
        assert b.discard_latched is False
        assert b.status == "AT_RISK"

        # Check audit log
        audit_entry = db.scalar(select(AuditLog).where(AuditLog.action == "BATCH_DISCARD_RESET"))
        assert audit_entry is not None
        assert audit_entry.actor == "admin_alice"
