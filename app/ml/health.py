"""Compressor health scoring (0-100) using cooling-rate analysis + Isolation Forest."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)
MODEL_DIR = Path(__file__).parent.parent.parent / "models"

# Healthy baseline: expected cooling rate in °C/min for a nominal compressor
BASELINE_COOLING_RATE = 0.4   # °C/min from 7→3°C


def _extract_cycles(df: pd.DataFrame) -> pd.DataFrame:
    """Extract compressor ON cycles and compute per-cycle metrics."""
    df = df.copy().sort_values("t_s").reset_index(drop=True)
    cycles = []
    in_cycle = False
    cycle_start_idx = 0
    T_at_start = 0.0

    for i, row in df.iterrows():
        if row["compressor_on"] and not in_cycle:
            in_cycle = True
            cycle_start_idx = i
            T_at_start = row["temp_c"]
        elif not row["compressor_on"] and in_cycle:
            in_cycle = False
            cycle_df = df.iloc[cycle_start_idx:i]
            duration_s = len(cycle_df) * 5  # 5-s steps
            if duration_s < 30:
                continue
            T_end = cycle_df["temp_c"].iloc[-1]
            cool_rate = (T_at_start - T_end) / (duration_s / 60.0) if duration_s > 0 else 0
            duty = df["compressor_on"].iloc[
                max(0, cycle_start_idx - 360):i
            ].mean()
            cycles.append({
                "duration_s":  duration_s,
                "cool_rate":   cool_rate,
                "duty_30m":    duty,
                "T_start":     T_at_start,
                "T_end":       T_end,
            })

    return pd.DataFrame(cycles) if cycles else pd.DataFrame(
        columns=["duration_s", "cool_rate", "duty_30m", "T_start", "T_end"]
    )


def train_health(df: pd.DataFrame) -> dict:
    """Fit Isolation Forest on healthy-compressor cycles."""
    # Use runs with normal k_cool as "healthy"
    if "k_cool" in df.columns:
        healthy = df[df["k_cool"] >= 0.020]
    else:
        healthy = df

    all_cycles = []
    for run_id, group in healthy.groupby("run_id"):
        cycles = _extract_cycles(group)
        if len(cycles):
            all_cycles.append(cycles)

    if not all_cycles:
        logger.warning("No cycles found for health training")
        return {"error": "no cycles"}

    cycles_df = pd.concat(all_cycles, ignore_index=True)
    X = cycles_df[["cool_rate", "duty_30m", "duration_s"]].values

    iso = IsolationForest(contamination=0.05, random_state=42, n_jobs=1)
    iso.fit(X)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(iso, MODEL_DIR / "health_iso.pkl")
    joblib.dump(float(cycles_df["cool_rate"].mean()), MODEL_DIR / "health_baseline_rate.pkl")

    logger.info("Health model trained on %d cycles from %d runs",
                len(cycles_df), len(all_cycles))
    return {"cycles_trained": len(cycles_df), "mean_cool_rate": cycles_df["cool_rate"].mean()}


_iso_cache: Any = None
_baseline_rate: float | None = None


def _load_health_model():
    global _iso_cache, _baseline_rate
    path = MODEL_DIR / "health_iso.pkl"
    if _iso_cache is None and path.exists():
        _iso_cache = joblib.load(path)
        _baseline_rate = joblib.load(MODEL_DIR / "health_baseline_rate.pkl")
    return _iso_cache, _baseline_rate


def score_health(readings: list[dict]) -> dict:
    """Score compressor health 0-100 from a list of recent reading dicts."""
    iso, baseline_rate = _load_health_model()
    if not readings or len(readings) < 20:
        return {"available": False, "reason": "insufficient data"}

    df = pd.DataFrame(readings).sort_values("t_s").reset_index(drop=True)
    cycles = _extract_cycles(df)

    if cycles.empty:
        duty_approx = float(df["compressor_on"].mean()) if "compressor_on" in df.columns else 0.5
        duty_penalty = abs(duty_approx - 0.45) * 40.0
        provisional = max(50.0, min(95.0, 88.0 - duty_penalty))
        return {
            "available": True,
            "score": round(provisional, 1),
            "trend": "good" if provisional >= 70 else "watch",
            "mean_cooling_rate": round(BASELINE_COOLING_RATE, 3),
            "cycles_analyzed": 1,
        }

    recent = cycles.tail(5)
    mean_rate = float(recent["cool_rate"].mean())

    # Rate-based score
    rate_score = np.clip(mean_rate / (baseline_rate or BASELINE_COOLING_RATE), 0, 1) * 100

    # Anomaly score (Isolation Forest: -1 anomaly, 1 normal → map to 0-100)
    if iso:
        X = recent[["cool_rate", "duty_30m", "duration_s"]].values
        raw = iso.decision_function(X)  # higher = more normal
        iso_score = float(np.clip((np.mean(raw) + 0.5) * 100, 0, 100))
    else:
        iso_score = rate_score

    health = round(0.6 * rate_score + 0.4 * iso_score, 1)

    if health >= 70:
        trend = "good"
    elif health >= 40:
        trend = "watch"
    else:
        trend = "failing"

    return {
        "available": True,
        "score": health,
        "trend": trend,
        "mean_cooling_rate": round(mean_rate, 3),
        "cycles_analyzed": len(cycles),
    }
