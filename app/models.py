from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def utcnow() -> datetime:
    return datetime.now(UTC)


# ─────────────────────────────────────────────────────────────────────────────
# Existing tables (kept intact for backward-compat with legacy dashboard)
# ─────────────────────────────────────────────────────────────────────────────

class Device(Base):
    __tablename__ = "devices"
    device_id:    Mapped[str]           = mapped_column(String(64), primary_key=True)
    name:         Mapped[str]           = mapped_column(String(120))
    enabled:      Mapped[bool]          = mapped_column(Boolean, default=True)
    mqtt_password: Mapped[str | None]   = mapped_column(String(64), nullable=True)
    created_at:   Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow)
    # ColdChain additions
    last_seen:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seq:     Mapped[int | None]    = mapped_column(Integer, nullable=True)
    fridge_id:    Mapped[int | None]    = mapped_column(
        ForeignKey("fridges.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fridge: Mapped[Fridge | None] = relationship("Fridge", foreign_keys=[fridge_id])


class Parameter(Base):
    __tablename__ = "parameters"
    name:    Mapped[str]        = mapped_column(String(64), primary_key=True)
    unit:    Mapped[str | None] = mapped_column(String(16), nullable=True)
    enabled: Mapped[bool]       = mapped_column(Boolean, default=True)


class IngestedMessage(Base):
    """Deduplication receipt; contains no raw or unapproved parameter values."""
    __tablename__ = "ingested_messages"
    device_id:   Mapped[str]      = mapped_column(ForeignKey("devices.device_id"), primary_key=True)
    message_id:  Mapped[str]      = mapped_column(String(36), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Telemetry(Base):
    __tablename__ = "telemetry"
    __table_args__ = (Index("ix_telemetry_timestamp_id", "timestamp", "id"),)
    id:          Mapped[int]      = mapped_column(Integer, primary_key=True)
    record_id:   Mapped[int]      = mapped_column(ForeignKey("telemetry_records.id"), index=True)
    timestamp:   Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    device_id:   Mapped[str]      = mapped_column(ForeignKey("devices.device_id"))
    parameter:   Mapped[str]      = mapped_column(String(64))
    value:       Mapped[float]    = mapped_column(Float)


class TelemetryRecord(Base):
    """One registry entry per accepted device transmission."""
    __tablename__ = "telemetry_records"
    id:          Mapped[int]           = mapped_column(Integer, primary_key=True)
    device_id:   Mapped[str]           = mapped_column(ForeignKey("devices.device_id"))
    message_id:  Mapped[str | None]    = mapped_column(String(36), nullable=True)
    timestamp:   Mapped[datetime]      = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow)


class Admin(Base):
    __tablename__ = "admins"
    username:      Mapped[str] = mapped_column(String(64), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    token_hash: Mapped[str]      = mapped_column(String(64), primary_key=True)
    username:   Mapped[str]      = mapped_column(ForeignKey("admins.username"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class UserProfile(Base):
    __tablename__ = "user_profiles"
    username:   Mapped[str]           = mapped_column(
        ForeignKey("admins.username", ondelete="CASCADE"), primary_key=True
    )
    full_name:  Mapped[str | None]    = mapped_column(String(120), nullable=True)
    email:      Mapped[str | None]    = mapped_column(String(254), nullable=True)
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime]      = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ─────────────────────────────────────────────────────────────────────────────
# ColdChain tables
# ─────────────────────────────────────────────────────────────────────────────

class User(Base):
    """ColdChain role-based user (admin / pharmacist / inspector)."""
    __tablename__ = "users"
    id:            Mapped[int]           = mapped_column(Integer, primary_key=True)
    username:      Mapped[str]           = mapped_column(String(64), unique=True, nullable=False)
    bcrypt_hash:   Mapped[str]           = mapped_column(String(255), nullable=False)
    role:          Mapped[str]           = mapped_column(String(20), default="pharmacist")
    active:        Mapped[bool]          = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int]           = mapped_column(Integer, default=0)
    locked_until:  Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow)


class Fridge(Base):
    __tablename__ = "fridges"
    id:             Mapped[int]         = mapped_column(Integer, primary_key=True)
    name:           Mapped[str]         = mapped_column(String(120), nullable=False)
    capacity_slots: Mapped[int]         = mapped_column(Integer, default=10)
    location:       Mapped[str | None]  = mapped_column(String(255), nullable=True)
    device_id:      Mapped[str | None]  = mapped_column(
        ForeignKey("devices.device_id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    device: Mapped[Device | None]  = relationship("Device", foreign_keys=[device_id])
    batches: Mapped[list[Batch]]   = relationship("Batch", back_populates="fridge")


class Batch(Base):
    __tablename__ = "batches"
    id:                   Mapped[int]         = mapped_column(Integer, primary_key=True)
    code:                 Mapped[str]         = mapped_column(String(64), unique=True, nullable=False)
    vaccine_name:         Mapped[str]         = mapped_column(String(120), nullable=False)
    qty:                  Mapped[int]         = mapped_column(Integer, nullable=False)
    expiry_date:          Mapped[date | None] = mapped_column(Date, nullable=True)
    fridge_id:            Mapped[int | None]  = mapped_column(
        ForeignKey("fridges.id", ondelete="SET NULL"), nullable=True, index=True
    )
    exposure_weighted_min: Mapped[float]      = mapped_column(Float, default=0.0)
    last_exposure_ts:     Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    status:               Mapped[str]         = mapped_column(String(16), default="OK")
    discard_latched:      Mapped[bool]        = mapped_column(Boolean, default=False)
    qr_token:             Mapped[str]         = mapped_column(String(64), unique=True, nullable=False)
    created_at:           Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=utcnow)

    fridge: Mapped[Fridge | None] = relationship("Fridge", back_populates="batches")

    @property
    def remaining_pct(self) -> float:
        return max(0.0, 100.0 * (1.0 - self.exposure_weighted_min / 60.0))


class BatchMovement(Base):
    __tablename__ = "batch_movements"
    id:           Mapped[int]         = mapped_column(Integer, primary_key=True)
    batch_id:     Mapped[int]         = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_fridge_id: Mapped[int|None]  = mapped_column(Integer, nullable=True)
    to_fridge_id:   Mapped[int|None]  = mapped_column(Integer, nullable=True)
    moved_by:       Mapped[int|None]  = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    moved_at: Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=utcnow)
    reason:   Mapped[str]             = mapped_column(String(32), default="manual")


class Reading(Base):
    """One ColdChain telemetry row. UNIQUE(device_id, seq) enforces idempotency."""
    __tablename__ = "readings"
    __table_args__ = (
        UniqueConstraint("device_id", "seq", name="uq_readings_device_seq"),
        Index("ix_readings_device_ts", "device_id", "ts"),
    )
    id:           Mapped[int]       = mapped_column(Integer, primary_key=True)
    device_id:    Mapped[str]       = mapped_column(ForeignKey("devices.device_id"), nullable=False)
    seq:          Mapped[int]       = mapped_column(Integer, nullable=False)
    ts:           Mapped[datetime]  = mapped_column(DateTime(timezone=True), nullable=False)
    temp_c:       Mapped[float]     = mapped_column(Float, nullable=False)
    door_open:    Mapped[bool]      = mapped_column(Boolean, default=False)
    door_open_s:  Mapped[int]       = mapped_column(Integer, default=0)
    compressor_on: Mapped[bool]     = mapped_column(Boolean, default=False)
    lockout_s:    Mapped[int]       = mapped_column(Integer, default=0)
    power_source: Mapped[str]       = mapped_column(String(16), default="MAINS")
    mains_present: Mapped[bool]     = mapped_column(Boolean, default=True)
    battery_pct:  Mapped[float|None] = mapped_column(Float, nullable=True)
    battery_v:    Mapped[float|None] = mapped_column(Float, nullable=True)
    state:        Mapped[str]       = mapped_column(String(16), default="SAFE")
    red_latched:  Mapped[bool]      = mapped_column(Boolean, default=False)
    sim_mode:     Mapped[bool]      = mapped_column(Boolean, default=False)
    ts_source:    Mapped[str]       = mapped_column(String(16), default="ntp")
    ingested_at:  Mapped[datetime]  = mapped_column(DateTime(timezone=True), default=utcnow)


class Nonce(Base):
    """Per-device nonce deduplication (replay attack prevention)."""
    __tablename__ = "nonces"
    __table_args__ = (
        UniqueConstraint("device_id", "nonce", name="uq_nonces_device_nonce"),
        Index("ix_nonces_seen_at", "seen_at"),
    )
    id:        Mapped[int]      = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str]      = mapped_column(ForeignKey("devices.device_id"), nullable=False)
    nonce:     Mapped[str]      = mapped_column(String(64), nullable=False)
    seen_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SecurityEvent(Base):
    __tablename__ = "security_events"
    id:         Mapped[int]         = mapped_column(Integer, primary_key=True)
    device_id:  Mapped[str | None]  = mapped_column(String(64), nullable=True, index=True)
    kind:       Mapped[str]         = mapped_column(String(32), nullable=False)
    raw_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Append-only hash-chained audit log. DB trigger blocks UPDATE/DELETE."""
    __tablename__ = "audit_log"
    idx:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts:           Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor:        Mapped[str]      = mapped_column(String(64), nullable=False)
    action:       Mapped[str]      = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str|None] = mapped_column(Text, nullable=True)
    prev_hash:    Mapped[str]      = mapped_column(String(64), nullable=False)
    hash:         Mapped[str]      = mapped_column(String(64), nullable=False)

    def payload(self) -> dict:
        return json.loads(self.payload_json) if self.payload_json else {}


class Alert(Base):
    __tablename__ = "alerts"
    id:              Mapped[int]         = mapped_column(Integer, primary_key=True)
    type:            Mapped[str]         = mapped_column(String(32), nullable=False)
    device_id:       Mapped[str | None]  = mapped_column(String(64), nullable=True)
    batch_id:        Mapped[int | None]  = mapped_column(
        ForeignKey("batches.id", ondelete="SET NULL"), nullable=True
    )
    message:         Mapped[str]         = mapped_column(Text, nullable=False)
    sent_via:        Mapped[str | None]  = mapped_column(String(16), nullable=True)
    created_at:      Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=utcnow)
    acknowledged_by: Mapped[int | None]  = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)


class MlPrediction(Base):
    __tablename__ = "ml_predictions"
    id:             Mapped[int]         = mapped_column(Integer, primary_key=True)
    device_id:      Mapped[str]         = mapped_column(ForeignKey("devices.device_id"), nullable=False)
    ts:             Mapped[datetime]    = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_min:    Mapped[int]         = mapped_column(Integer, nullable=False)
    predicted_temp: Mapped[float|None]  = mapped_column(Float, nullable=True)
    breach_prob:    Mapped[float|None]  = mapped_column(Float, nullable=True)
    health_score:   Mapped[float|None]  = mapped_column(Float, nullable=True)


class RelocationSuggestion(Base):
    __tablename__ = "relocation_suggestions"
    id:           Mapped[int]         = mapped_column(Integer, primary_key=True)
    from_fridge_id: Mapped[int|None]  = mapped_column(
        ForeignKey("fridges.id", ondelete="SET NULL"), nullable=True
    )
    plan_json:    Mapped[str]         = mapped_column(Text, nullable=False)
    status:       Mapped[str]         = mapped_column(String(16), default="pending")
    confirmed_by: Mapped[int | None]  = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at:   Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at:   Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
