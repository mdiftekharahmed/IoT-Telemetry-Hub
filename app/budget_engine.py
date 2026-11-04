"""Heat-exposure budget engine.

Budget rules (per spec §3.2):
  - weight = 0  if T ≤ 8°C
  - weight = 1  if 8 < T ≤ 12°C
  - weight = 2  if T > 12°C
  - exposure += dt_min * weight * time_scale
  - 60 weighted minutes → Discard

Status transitions:
  OK  → AT_RISK  (remaining_pct < 20 %)
  AT_RISK → DISCARD (remaining_pct == 0, latched until admin reset)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.audit as audit
from app.models import Batch, Fridge, Reading, utcnow
from app.thresholds import get_thresholds

logger = logging.getLogger(__name__)

DT_CAP_MINUTES   = 2.0    # cap dt to avoid inflating exposure after a sync gap


def exposure_weight(
    temp_c: float,
    threshold_temp: float | None = None,
    double_temp: float | None = None,
) -> float:
    th = get_thresholds()
    t_thresh = threshold_temp if threshold_temp is not None else th["budget_threshold_temp"]
    t_double = double_temp if double_temp is not None else th["budget_double_temp"]
    if temp_c <= t_thresh:
        return 0.0
    if temp_c <= t_double:
        return 1.0
    return 2.0


def _remaining_pct(exposure: float, total_minutes: float | None = None) -> float:
    th = get_thresholds()
    total = total_minutes if total_minutes is not None else th["budget_total_minutes"]
    return max(0.0, 100.0 * (1.0 - exposure / total))


def update_exposure(
    db: Session,
    fridge_id: int,
    temp_c: float,
    ts: datetime,
    time_scale: float = 1.0,
    publish_cmd_fn=None,     # callable(device_id, cmd_type, payload) for downlink
) -> None:
    """Called after a new reading is stored. Updates all active batches in fridge."""
    fridge = db.get(Fridge, fridge_id)
    if fridge is None:
        return

    batches = db.scalars(
        select(Batch).where(
            Batch.fridge_id == fridge_id,
            Batch.status != "DISCARD",
        )
    ).all()

    w = exposure_weight(temp_c)

    th = get_thresholds()
    at_risk_thresh = th.get("budget_at_risk_pct", 20.0)

    for batch in batches:
        if batch.last_exposure_ts is not None:
            last_ts = batch.last_exposure_ts.replace(tzinfo=UTC) \
                if batch.last_exposure_ts.tzinfo is None \
                else batch.last_exposure_ts
            dt_min = (ts - last_ts).total_seconds() / 60.0
            dt_min = min(dt_min, DT_CAP_MINUTES)
        else:
            dt_min = 0.0

        added = dt_min * w * time_scale
        batch.exposure_weighted_min += added
        batch.last_exposure_ts = ts

        remaining = _remaining_pct(batch.exposure_weighted_min, th.get("budget_total_minutes", 60.0))
        old_status = batch.status

        if remaining == 0.0 and not batch.discard_latched:
            batch.status = "DISCARD"
            batch.discard_latched = True
            logger.warning("Batch %s DISCARD latched (fridge %s)", batch.code, fridge_id)
            audit.append(db, actor="system", action="BATCH_DISCARD", payload={
                "batch_id": batch.id, "code": batch.code,
                "exposure_min": batch.exposure_weighted_min,
                "fridge_id": fridge_id,
            })
            # Send LATCH_RED to the device
            if publish_cmd_fn and fridge.device_id:
                publish_cmd_fn(fridge.device_id, "LATCH_RED", {"batch": batch.code})

        elif remaining < at_risk_thresh and batch.status == "OK":
            batch.status = "AT_RISK"
            logger.info("Batch %s AT_RISK (%.1f%% remaining)", batch.code, remaining)
            audit.append(db, actor="system", action="BATCH_AT_RISK", payload={
                "batch_id": batch.id, "code": batch.code,
                "remaining_pct": remaining,
            })

        if old_status != batch.status:
            db.flush()


def reset_discard(
    db: Session,
    batch_id: int,
    actor: str,
    reason: str,
    publish_cmd_fn=None,
) -> Batch:
    """Admin-only: clear the Discard latch. Returns updated batch."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise ValueError(f"Batch {batch_id} not found")
    if not batch.discard_latched:
        raise ValueError("Batch is not Discard-latched")

    batch.discard_latched = False
    batch.status = "AT_RISK"
    db.flush()

    audit.append(db, actor=actor, action="BATCH_DISCARD_RESET", payload={
        "batch_id": batch.id, "code": batch.code, "reason": reason,
    })

    # Send RESET_RED to device
    fridge = db.get(Fridge, batch.fridge_id) if batch.fridge_id else None
    if publish_cmd_fn and fridge and fridge.device_id:
        publish_cmd_fn(fridge.device_id, "RESET_RED", {"batch": batch.code})

    return batch


def recompute_exposure_from_history(db: Session, fridge_id: int,
                                    time_scale: float = 1.0) -> None:
    """Re-run the budget engine over all stored readings in ts order (for sync gaps)."""
    fridge = db.get(Fridge, fridge_id)
    if not fridge or not fridge.device_id:
        return

    # Reset all batches to zero
    batches = db.scalars(select(Batch).where(Batch.fridge_id == fridge_id)).all()
    for b in batches:
        b.exposure_weighted_min = 0.0
        b.last_exposure_ts = None
        b.status = "OK"
        b.discard_latched = False

    readings = db.scalars(
        select(Reading)
        .where(Reading.device_id == fridge.device_id)
        .order_by(Reading.ts)
    ).all()

    for r in readings:
        ts = r.ts.replace(tzinfo=UTC) if r.ts.tzinfo is None else r.ts
        update_exposure(db, fridge_id, r.temp_c, ts, time_scale)
