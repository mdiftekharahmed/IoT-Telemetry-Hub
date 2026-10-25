"""30-minute temperature forecast using Ridge (baseline) + LightGBM."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)
MODEL_DIR  = Path(__file__).parent.parent.parent / "models"
HORIZON_S  = 1800   # 30 minutes
STEP_S     = 5      # firmware publish rate
HORIZON_STEPS = HORIZON_S // STEP_S   # 360 steps


# ── Feature engineering ───────────────────────────────────────────────────────

def _add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values("t_s").reset_index(drop=True)
    T = df["temp_c"]
    df["slope_1m"]   = T.diff(12).fillna(0) / 60
    df["slope_5m"]   = T.diff(60).fillna(0) / 300
    df["slope_10m"]  = T.diff(120).fillna(0) / 600
    df["roll_mean_5m"] = T.rolling(60, min_periods=1).mean()
    df["roll_std_5m"]  = T.rolling(60, min_periods=1).std().fillna(0)
    df["duty_30m"]     = df["compressor_on"].rolling(360, min_periods=1).mean()
    df["since_switch"] = (
        df["compressor_on"].diff().abs().cumsum().fillna(0)
    )
    return df


def _build_xy(df: pd.DataFrame, horizon_steps: int = HORIZON_STEPS):
    df = _add_features(df)
    feature_cols = [
        "temp_c", "slope_1m", "slope_5m", "slope_10m",
        "roll_mean_5m", "roll_std_5m",
        "door_open", "door_open_s", "compressor_on",
        "duty_30m", "since_switch", "lockout_s",
    ]
    X = df[feature_cols].iloc[:-horizon_steps].values
    y = df["temp_c"].shift(-horizon_steps).dropna().values
    # align
    min_len = min(len(X), len(y))
    return X[:min_len], y[:min_len], feature_cols


# ── Training ──────────────────────────────────────────────────────────────────

def train(df: pd.DataFrame) -> dict[str, Any]:
    # Time-based split: first 80% train, last 20% test
    groups = df.groupby("run_id")
    all_runs = list(groups)
    split    = int(len(all_runs) * 0.8)
    train_df = pd.concat([g for _, g in all_runs[:split]])
    test_df  = pd.concat([g for _, g in all_runs[split:]])

    X_tr, y_tr, cols = _build_xy(train_df)
    X_te, y_te, _    = _build_xy(test_df)

    # Baseline: persistence (predict current temp)
    baseline_mae  = mean_absolute_error(y_te, X_te[:, 0])
    baseline_rmse = np.sqrt(mean_squared_error(y_te, X_te[:, 0]))

    # Ridge baseline
    ridge = Pipeline([("scaler", StandardScaler()), ("model", Ridge())])
    ridge.fit(X_tr, y_tr)
    ridge_pred = ridge.predict(X_te)
    ridge_mae  = mean_absolute_error(y_te, ridge_pred)
    ridge_rmse = np.sqrt(mean_squared_error(y_te, ridge_pred))

    # LightGBM (main model)
    try:
        import lightgbm as lgb
        lgbm = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05,
                                  num_leaves=31, random_state=42, n_jobs=1)
        lgbm.fit(X_tr, y_tr)
        lgbm_pred = lgbm.predict(X_te)
        lgbm_mae  = mean_absolute_error(y_te, lgbm_pred)
        lgbm_rmse = np.sqrt(mean_squared_error(y_te, lgbm_pred))
        best_model, best_name = lgbm, "lgbm"
    except Exception as exc:
        logger.warning("LightGBM unavailable (%s), falling back to Ridge", exc)
        best_model, best_name = ridge, "ridge"
        lgbm_mae = lgbm_rmse = None

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(best_model, MODEL_DIR / "forecast_model.pkl")
    joblib.dump(cols, MODEL_DIR / "forecast_features.pkl")

    results = {
        "model": best_name,
        "baseline_mae": round(baseline_mae, 4),
        "baseline_rmse": round(baseline_rmse, 4),
        "ridge_mae": round(ridge_mae, 4),
        "ridge_rmse": round(ridge_rmse, 4),
        "lgbm_mae": round(lgbm_mae, 4) if lgbm_mae else None,
        "lgbm_rmse": round(lgbm_rmse, 4) if lgbm_rmse else None,
        "train_samples": len(X_tr),
        "test_samples": len(X_te),
    }
    logger.info("Forecast training complete: %s", results)
    return results


# ── Inference ─────────────────────────────────────────────────────────────────

_model_cache: Any = None
_feature_cols_cache: list[str] | None = None


def _load_model():
    global _model_cache, _feature_cols_cache
    if _model_cache is None:
        path = MODEL_DIR / "forecast_model.pkl"
        if not path.exists():
            return None, None
        _model_cache = joblib.load(path)
        _feature_cols_cache = joblib.load(MODEL_DIR / "forecast_features.pkl")
    return _model_cache, _feature_cols_cache


def predict_next_30(readings: list[dict]) -> dict:
    """Given recent readings (list of dicts with temp_c, etc.) return forecast."""
    model, cols = _load_model()
    if model is None or len(readings) < 10:
        return {"available": False, "reason": "model not trained or insufficient data"}

    df = pd.DataFrame(readings).sort_values("t_s").reset_index(drop=True)
    df = _add_features(df)

    # Use last row as current feature vector
    row = df[cols].iloc[-1:].values
    predicted_temp = float(model.predict(row)[0])
    cur_temp = float(df["temp_c"].iloc[-1])
    breach = predicted_temp > 8.0 or predicted_temp < 2.0

    breach_in_minutes = None
    if breach:
        if predicted_temp > 8.0 and cur_temp < 8.0:
            breach_in_minutes = max(1, min(30, int(round(30.0 * (8.0 - cur_temp) / (predicted_temp - cur_temp)))))
        elif predicted_temp < 2.0 and cur_temp > 2.0:
            breach_in_minutes = max(1, min(30, int(round(30.0 * (cur_temp - 2.0) / (cur_temp - predicted_temp)))))
        elif cur_temp > 8.0 or cur_temp < 2.0:
            breach_in_minutes = 0

    # Build 11-point trajectory series (5 historical points, Now, 5 future points)
    n = len(df)
    hist_steps = [max(0, n - 1 - int(i * (n / 10))) for i in range(5, 0, -1)]
    points = []
    
    # Historical points
    for idx, step_min in zip(hist_steps, [25, 20, 15, 10, 5]):
        val = round(float(df["temp_c"].iloc[idx]), 2)
        points.append({
            "label": f"-{step_min}m",
            "temp": val,
            "type": "history",
            "predicted_temp": val,
            "breach_prob": 0.0 if 2.0 <= val <= 8.0 else 1.0,
        })
    
    # Current point
    points.append({
        "label": "Now",
        "temp": round(cur_temp, 2),
        "type": "current",
        "predicted_temp": round(cur_temp, 2),
        "breach_prob": 0.0 if 2.0 <= cur_temp <= 8.0 else 1.0,
    })
    
    # Future projected points (+5m, +10m, +15m, +20m, +25m, +30m)
    for m in [5, 10, 15, 20, 25, 30]:
        ratio = m / 30.0
        interp = cur_temp + (predicted_temp - cur_temp) * ratio
        prob = 0.0
        if interp > 8.0:
            prob = min(1.0, (interp - 8.0) / 2.0)
        elif interp < 2.0:
            prob = min(1.0, (2.0 - interp) / 2.0)
        points.append({
            "label": f"+{m}m",
            "temp": round(interp, 2),
            "type": "forecast",
            "predicted_temp": round(interp, 2),
            "breach_prob": round(prob, 2),
        })

    return {
        "available": True,
        "predicted_temp_30m": round(predicted_temp, 2),
        "breach_predicted": breach,
        "breach_in_minutes": breach_in_minutes,
        "current_temp": round(cur_temp, 2),
        "forecast": points,
        "series": points,
    }
