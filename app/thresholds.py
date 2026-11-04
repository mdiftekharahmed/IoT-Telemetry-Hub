"""Dynamic System Thresholds Manager.

Loads, caches, and persists dynamic operational parameters from/to
`config/system_thresholds.json`. Allows the Admin to tune temperature bounds,
compressor ON/OFF triggers, heat budget accumulation rates, and alarm durations
on the fly without rebuilding or restarting the system.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "system_thresholds.json"
_lock = RLock()

DEFAULT_THRESHOLDS: dict[str, Any] = {
    "temp_safe_min": 2.0,
    "temp_safe_max": 8.0,
    "temp_warning_low_band": 0.5,
    "temp_warning_high_band": 0.5,
    "compressor_on_temp": 7.0,
    "compressor_off_temp": 3.0,
    "compressor_min_off_s": 60,
    "budget_threshold_temp": 8.0,
    "budget_double_temp": 12.0,
    "budget_total_minutes": 60.0,
    "budget_at_risk_pct": 20.0,
    "door_warning_s": 30,
    "door_alarm_s": 60,
    "ambient_temp_c": 25.0,
}

_cached_thresholds: dict[str, Any] | None = None


def _load_from_file() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_THRESHOLDS, f, indent=2)
        return dict(DEFAULT_THRESHOLDS)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            merged = dict(DEFAULT_THRESHOLDS)
            merged.update(data)
            return merged
    except Exception as exc:
        logger.warning("Failed to read %s: %s; using defaults", CONFIG_PATH, exc)
        return dict(DEFAULT_THRESHOLDS)


def _save_to_file(thresholds: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(thresholds, f, indent=2)


def get_thresholds() -> dict[str, Any]:
    """Return a copy of the current dynamic thresholds."""
    global _cached_thresholds
    with _lock:
        if _cached_thresholds is None:
            _cached_thresholds = _load_from_file()
        return dict(_cached_thresholds)


def update_thresholds(
    updates: dict[str, Any],
    actor: str = "admin",
    db=None,
    settings=None,
) -> dict[str, Any]:
    """Validate, persist, and broadcast updated dynamic thresholds."""
    global _cached_thresholds
    with _lock:
        current = get_thresholds()
        
        # Type & sanity validations
        for key, val in updates.items():
            if key not in DEFAULT_THRESHOLDS:
                continue
            expected_type = type(DEFAULT_THRESHOLDS[key])
            try:
                current[key] = expected_type(val)
            except (ValueError, TypeError):
                continue

        # Range integrity checks
        if current["temp_safe_min"] >= current["temp_safe_max"]:
            raise ValueError("temp_safe_min must be strictly less than temp_safe_max")
        if current["compressor_off_temp"] >= current["compressor_on_temp"]:
            raise ValueError("compressor_off_temp must be strictly less than compressor_on_temp")
        if current["budget_threshold_temp"] >= current["budget_double_temp"]:
            raise ValueError("budget_threshold_temp must be strictly less than budget_double_temp")

        _save_to_file(current)
        _cached_thresholds = dict(current)

        # Audit logging if DB session passed
        if db is not None:
            try:
                import app.audit as audit_mod
                audit_mod.append(
                    db,
                    actor=actor,
                    action="THRESHOLDS_UPDATED",
                    payload=updates,
                )
            except Exception as exc:
                logger.warning("Failed to audit thresholds update: %s", exc)

        # Broadcast downlink command to all active devices if settings provided
        if settings is not None and db is not None:
            try:
                from sqlalchemy import select
                from app.models import Device
                from app.mqtt_publisher import publish_command

                devices = db.scalars(select(Device).where(Device.enabled == True)).all()
                for dev in devices:
                    publish_command(
                        settings,
                        dev.device_id,
                        "SET_CONFIG",
                        {
                            "comp_on_temp": current["compressor_on_temp"],
                            "comp_off_temp": current["compressor_off_temp"],
                            "lockout_s": current["compressor_min_off_s"],
                            "safe_min": current["temp_safe_min"],
                            "safe_max": current["temp_safe_max"],
                            "door_alarm_s": current["door_alarm_s"],
                        },
                    )
            except Exception as exc:
                logger.warning("Failed to broadcast SET_CONFIG to devices: %s", exc)

        return dict(current)


def reset_to_defaults() -> dict[str, Any]:
    """Reset thresholds back to default values."""
    global _cached_thresholds
    with _lock:
        _cached_thresholds = dict(DEFAULT_THRESHOLDS)
        _save_to_file(_cached_thresholds)
        return dict(_cached_thresholds)
