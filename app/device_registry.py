"""DB-backed device secret resolution.

Source of truth for per-device HMAC secrets is the `devices.mqtt_password`
column (64-char hex). It replaces the former hard-coded `settings.device_secrets_json`
environment config, which is kept only as a legacy fallback for devices that
have no DB row yet (e.g. seed scripts not yet migrated).

Everywhere a secret is needed (ingestion verification, downlink signing,
provisioning screens) it must be resolved through this module.
"""

from __future__ import annotations

import secrets as pysecrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device

SECRET_LEN = 64  # 32-byte key, hex-encoded


def generate_secret() -> str:
    """Mint a fresh 32-byte HMAC secret as 64-char lowercase hex."""
    return pysecrets.token_hex(32)


def get_device_secret(db: Session, device_id: str) -> str | None:
    """Resolve a single device secret from the database (None if unknown/absent)."""
    device = db.get(Device, device_id)
    if device is None:
        return None
    return device.mqtt_password or None


def db_device_secrets(db: Session) -> dict[str, str]:
    """Map of every DB-registered device with a non-empty secret."""
    return {
        d.device_id: d.mqtt_password
        for d in db.scalars(select(Device).where(Device.mqtt_password.is_not(None)))
        if d.mqtt_password
    }


def resolve_secrets_map(db: Session, env_fallback: dict[str, str] | None = None) -> dict[str, str]:
    """DB secrets win; environment-configured secrets only fill gaps."""
    merged = dict(env_fallback or {})
    merged.update(db_device_secrets(db))
    return merged
