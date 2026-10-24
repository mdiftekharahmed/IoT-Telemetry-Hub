"""Batch relocation suggester.

Trigger: predicted breach OR health score < 40.
Ranking: lowest remaining_pct first → nearest expiry → highest qty.
Candidates: predicted safe 30-min, free capacity, healthy compressor, door closed.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, BatchMovement, Fridge, Reading, RelocationSuggestion, utcnow

logger = logging.getLogger(__name__)

HEALTH_ALERT_THRESHOLD   = 40.0
REMAINING_ALERT_THRESHOLD = 20.0


def _free_slots(db: Session, fridge: Fridge) -> int:
    used = db.scalar(
        select(Batch).where(Batch.fridge_id == fridge.id, Batch.status != "DISCARD")
    )
    # Count active batches
    from sqlalchemy import func
    used_count = db.scalar(
        select(func.count()).select_from(Batch).where(
            Batch.fridge_id == fridge.id, Batch.status != "DISCARD"
        )
    ) or 0
    return fridge.capacity_slots - used_count


def _latest_reading(db: Session, fridge: Fridge) -> Reading | None:
    if not fridge.device_id:
        return None
    return db.scalar(
        select(Reading)
        .where(Reading.device_id == fridge.device_id)
        .order_by(Reading.ts.desc())
        .limit(1)
    )


def build_suggestion(db: Session, trigger_fridge_id: int,
                     forecast_results: dict, health_result: dict) -> RelocationSuggestion | None:
    """Build and persist a relocation suggestion if warranted."""
    trigger_fridge = db.get(Fridge, trigger_fridge_id)
    if not trigger_fridge:
        return None

    # Rank batches to move
    batches = db.scalars(
        select(Batch).where(
            Batch.fridge_id == trigger_fridge_id,
            Batch.status != "DISCARD",
        )
    ).all()

    if not batches:
        return None

    def sort_key(b: Batch):
        days_to_expiry = (b.expiry_date - date.today()).days if b.expiry_date else 9999
        return (b.remaining_pct, days_to_expiry, -b.qty)

    ranked = sorted(batches, key=sort_key)

    # Find candidate target fridges
    all_fridges = db.scalars(select(Fridge).where(Fridge.id != trigger_fridge_id)).all()
    candidates = []
    for f in all_fridges:
        if _free_slots(db, f) <= 0:
            continue
        latest = _latest_reading(db, f)
        if not latest:
            continue
        # Must be in safe range with door closed
        if latest.temp_c < 2.0 or latest.temp_c > 8.0:
            continue
        if latest.door_open:
            continue
        candidates.append(f)

    if not candidates:
        logger.info("No suitable target fridges for relocation from fridge %d", trigger_fridge_id)
        return None

    # Greedy assignment
    plan = []
    for batch in ranked:
        if not candidates:
            break
        target = candidates[0]
        reason_parts = []
        if forecast_results.get("breach_predicted"):
            reason_parts.append("predicted breach in 30 min")
        if health_result.get("score", 100) < HEALTH_ALERT_THRESHOLD:
            reason_parts.append(f"compressor health {health_result['score']:.0f}/100")
        reason = "; ".join(reason_parts) or "precautionary relocation"

        plan.append({
            "batch_id":      batch.id,
            "batch_code":    batch.code,
            "vaccine_name":  batch.vaccine_name,
            "from_fridge_id": trigger_fridge_id,
            "to_fridge_id":  target.id,
            "remaining_pct": round(batch.remaining_pct, 1),
            "reason":        reason,
        })
        # Remove target from candidates if full after this move
        if _free_slots(db, target) <= 1:
            candidates.pop(0)

    if not plan:
        return None

    suggestion = RelocationSuggestion(
        from_fridge_id=trigger_fridge_id,
        plan_json=json.dumps(plan),
        status="pending",
    )
    db.add(suggestion)
    db.flush()
    logger.info("Relocation suggestion %d created (%d moves)", suggestion.id, len(plan))
    return suggestion


def confirm_suggestion(db: Session, suggestion_id: int,
                        confirmed_by_user_id: int, actor: str) -> list[BatchMovement]:
    """Execute all moves in one transaction and write audit entries."""
    import app.audit as audit_mod

    suggestion = db.get(RelocationSuggestion, suggestion_id)
    if not suggestion or suggestion.status != "pending":
        raise ValueError("Suggestion not found or not pending")

    plan = json.loads(suggestion.plan_json)
    movements = []
    for item in plan:
        batch = db.get(Batch, item["batch_id"])
        if not batch:
            continue
        old_fridge = batch.fridge_id
        batch.fridge_id = item["to_fridge_id"]
        mv = BatchMovement(
            batch_id=batch.id,
            from_fridge_id=old_fridge,
            to_fridge_id=item["to_fridge_id"],
            moved_by=confirmed_by_user_id,
            reason="ai_suggestion",
        )
        db.add(mv)
        movements.append(mv)

    suggestion.status       = "confirmed"
    suggestion.confirmed_by = confirmed_by_user_id
    suggestion.updated_at   = utcnow()
    db.flush()

    audit_mod.append(db, actor=actor, action="RELOCATION_CONFIRMED", payload={
        "suggestion_id": suggestion_id,
        "moves": len(movements),
    })
    return movements
