"""
Canonical list of permanent system parameters and DB-sync utility.

Upserts all entries in SYSTEM_PARAMETERS into the `parameters` table with is_permanent=True.
Existing custom parameters are never touched.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Parameter

# ── Canonical system parameter definitions ────────────────────────────────────
# key → { unit, description }
# Marked is_permanent=True — cannot be deleted or disabled.

SYSTEM_PARAMETERS: dict[str, dict[str, str]] = {
    # ── Temperature ──────────────────────────────────────────────────────────
    "temp_c": {
        "unit": "°C",
        "description": "Fridge internal temperature (primary cold-chain sensor)",
    },
    # ── Door ─────────────────────────────────────────────────────────────────
    "door_open": {
        "unit": "bool",
        "description": "Fridge door open/closed state (1 = open, 0 = closed)",
    },
    "door_open_s": {
        "unit": "s",
        "description": "Cumulative seconds the door has been open in the current window",
    },
    # ── Compressor ───────────────────────────────────────────────────────────
    "compressor_on": {
        "unit": "bool",
        "description": "Fridge compressor relay state (1 = running, 0 = off)",
    },
    "lockout_s": {
        "unit": "s",
        "description": "Remaining compressor minimum-off lockout time in seconds",
    },
    # ── Vaccine Heat Exposure Budget ──────────────────────────────────────────
    "heat_budget_minutes": {
        "unit": "min",
        "description": "Remaining safe heat exposure budget minutes above 8°C threshold",
    },
    # ── ESP32 Node Power Supply (ESP Node, not fridge) ────────────────────────
    "device_power_status": {
        "unit": "text",
        "description": "ESP32 node power status: MAINS or BATTERY (device supply, not fridge)",
    },
    "node_power": {
        "unit": "text",
        "description": "ESP32 node active power source: MAINS or BATTERY (node supply, not fridge)",
    },
    "node_mains_ok": {
        "unit": "bool",
        "description": "ESP32 node mains AC present flag (1 = mains OK, 0 = running on battery backup)",
    },
    # ── Power aliases for firmware compatibility ──────────────────────────────
    "power_source": {
        "unit": "text",
        "description": "Active power source alias reported by firmware (MAINS / BATTERY)",
    },
    "mains_present": {
        "unit": "bool",
        "description": "Mains AC power detection from ESP32 hardware (1 = AC present)",
    },
    # ── Backup Battery ────────────────────────────────────────────────────────
    "battery_pct": {
        "unit": "%",
        "description": "ESP32 node backup-battery state-of-charge percentage",
    },
    "battery_v": {
        "unit": "V",
        "description": "ESP32 node backup-battery terminal voltage in Volts",
    },
    # ── FSM State & Latch ─────────────────────────────────────────────────────
    "state": {
        "unit": "text",
        "description": "Fridge FSM classification: SAFE / WARNING / BREACH",
    },
    "red_latched": {
        "unit": "bool",
        "description": "Discard latch — red LED stays ON until admin reset via dashboard",
    },
    # ── Simulation ───────────────────────────────────────────────────────────
    "sim_mode": {
        "unit": "bool",
        "description": "Simulation / test mode active flag (not live sensor readings)",
    },
}

# Fast set for guard-check usage (is this a system parameter?)
SYSTEM_PARAMETER_KEYS: frozenset[str] = frozenset(SYSTEM_PARAMETERS.keys())


def seed_system_parameters(db: Session) -> int:
    """
    Upsert all SYSTEM_PARAMETERS into the `parameters` table.

    - New rows are inserted with is_permanent=True, enabled=True.
    - Existing rows have their unit / description / is_permanent refreshed.
    - Custom parameters (is_permanent=False) are preserved.
    """
    touched = 0
    for key, meta in SYSTEM_PARAMETERS.items():
        existing = db.get(Parameter, key)
        if existing is None:
            db.add(Parameter(
                name=key,
                unit=meta["unit"],
                description=meta["description"],
                is_permanent=True,
                enabled=True,
            ))
            touched += 1
        else:
            changed = False
            if existing.unit != meta["unit"]:
                existing.unit = meta["unit"]; changed = True
            if existing.description != meta["description"]:
                existing.description = meta["description"]; changed = True
            if not existing.is_permanent:
                existing.is_permanent = True; changed = True
            if changed:
                touched += 1

    db.commit()
    return touched
