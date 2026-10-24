"""Append-only hash-chained audit log.

hash_n = SHA256(prev_hash || idx || ts.isoformat() || actor || action || canonical_json(payload))

Genesis record has prev_hash = "0" * 64.
A PostgreSQL trigger in migration 0006 blocks UPDATE and DELETE.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import AuditLog, utcnow

logger = logging.getLogger(__name__)
_write_lock = threading.Lock()


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash: str, idx: int, ts: datetime,
                  actor: str, action: str, payload_json: str) -> str:
    blob = (
        prev_hash
        + str(idx)
        + ts.astimezone(UTC).isoformat()
        + actor
        + action
        + payload_json
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _ensure_genesis(db: Session) -> None:
    count = db.scalar(select(func.count()).select_from(AuditLog))
    if count == 0:
        ts = utcnow()
        payload_json = _canonical({"event": "genesis"})
        prev_hash = "0" * 64
        h = _compute_hash(prev_hash, 0, ts, "system", "GENESIS", payload_json)
        db.execute(
            text(
                "INSERT INTO audit_log (ts, actor, action, payload_json, prev_hash, hash)"
                " VALUES (:ts, :actor, :action, :payload, :prev, :hash)"
            ),
            {"ts": ts, "actor": "system", "action": "GENESIS",
             "payload": payload_json, "prev": prev_hash, "hash": h},
        )
        db.flush()


def append(db: Session, actor: str, action: str, payload: dict) -> AuditLog:
    """Append one record to the chain inside the caller's transaction."""
    with _write_lock:
        _ensure_genesis(db)
        # Lock the last row to prevent concurrent forks (PostgreSQL)
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT idx FROM audit_log ORDER BY idx DESC LIMIT 1 FOR UPDATE"))

        last = db.scalar(select(AuditLog).order_by(AuditLog.idx.desc()).limit(1))
        prev_hash = last.hash if last else "0" * 64
        next_idx  = (last.idx + 1) if last else 1
        ts = utcnow()
        payload_json = _canonical(payload)
        h = _compute_hash(prev_hash, next_idx, ts, actor, action, payload_json)

        entry = AuditLog(
            ts=ts, actor=actor, action=action,
            payload_json=payload_json,
            prev_hash=prev_hash, hash=h,
        )
        db.add(entry)
        db.flush()
        return entry


def verify_chain(db: Session) -> dict:
    """Recompute the whole chain; return {valid, checked, first_broken_idx}."""
    rows = db.scalars(select(AuditLog).order_by(AuditLog.idx)).all()
    prev_hash = "0" * 64
    for row in rows:
        expected = _compute_hash(row.prev_hash, row.idx, row.ts,
                                 row.actor, row.action, row.payload_json or "")
        if expected != row.hash or row.prev_hash != prev_hash:
            return {"valid": False, "checked": row.idx, "first_broken_idx": row.idx}
        prev_hash = row.hash
    return {"valid": True, "checked": len(rows), "first_broken_idx": None}
