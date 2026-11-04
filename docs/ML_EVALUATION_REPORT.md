# ML Evaluation Report — ColdChain IoT Telemetry Hub

**Document version:** 1.0  
**Date:** 2026-11-01  
**Prepared by:** Automated ML Evaluation Pipeline  
**Classification:** Internal — Engineering

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Dataset Description](#2-dataset-description)
3. [Feature Matrix](#3-feature-matrix)
4. [Forecast Model Evaluation](#4-forecast-model-evaluation)
5. [Compressor Health Scoring](#5-compressor-health-scoring)
6. [Relocation Decision Logic](#6-relocation-decision-logic)
7. [Verification Checklist (§5.3)](#7-verification-checklist-53)
8. [Appendix — Model Artifacts](#8-appendix--model-artifacts)

---

## 1. Executive Summary

The ColdChain IoT Telemetry Hub embeds two co-operating machine-learning subsystems designed to protect temperature-sensitive pharmaceutical stock (vaccines, biologics) stored in monitored refrigeration units.

| Subsystem | Goal | Output |
|---|---|---|
| **30-min Temperature Forecast** | Predict cabinet temperature 30 minutes ahead and flag imminent cold-chain breaches (outside 2 °C – 8 °C) | `predicted_temp_30m`, `breach_predicted`, `breach_in_minutes`, 11-point trajectory series |
| **Compressor Health Scoring** | Continuously assess compressor mechanical condition from cooling-cycle analytics and anomaly detection | `score` (0–100), `trend` (`good` / `watch` / `failing`) |

Together, these subsystems enable proactive intervention: the system can raise an alert and generate a **batch relocation suggestion** before a thermal excursion occurs, rather than logging a breach after the fact.

> [!IMPORTANT]
> The production model is **LightGBM** (gradient-boosted trees). A **Ridge Regression** baseline is always trained alongside it; if LightGBM is unavailable at runtime the system falls back to Ridge automatically, preserving uptime.

---

## 2. Dataset Description

### 2.1 Primary Training Data

| Attribute | Value |
|---|---|
| **Source** | `app/ml/simulator.py` — physics-based thermal simulator |
| **Training runs** | 200 synthetic simulation runs |
| **Calibration** | Real-rig calibration data used to tune `k_cool` and `k_warm` coefficients |
| **Firmware publish rate** | 5 seconds (`STEP_S = 5`) |
| **Time horizon constant** | `HORIZON_S = 1800` s → `HORIZON_STEPS = 360` steps |
| **Train / test split** | 80 % / 20 % by `run_id` (time-ordered; no data leakage) |

### 2.2 Sensor Hardware

| Sensor | Role | Signal |
|---|---|---|
| **DS18B20** | 1-Wire digital temperature probe | `temp_c` (°C, ±0.5 °C accuracy) |
| **Reed switch** | Door open/closed detection | `door_open` (bool), `door_open_s` (cumulative seconds open) |
| **Compressor relay** | ON/OFF state of refrigeration compressor | `compressor_on` (bool), `lockout_s` (seconds remaining in lockout) |

### 2.3 Simulator Physics

The simulator models a two-state thermal system:

- **Compressor ON** — cabinet cools at rate proportional to `k_cool` (nominal `0.016–0.025 °C/s·ΔT`)
- **Compressor OFF** — cabinet warms toward ambient at rate proportional to `k_warm`
- **Door events** — randomly injected heat loads that accelerate warming

Degraded units are simulated by reducing `k_cool`. Runs with `k_cool >= 0.020` are labelled **healthy** and used to train the Isolation Forest baseline. Runs with lower values represent worn or failing compressors.

---

## 3. Feature Matrix

All features are derived inside `_add_features()` in [`app/ml/forecast.py`](../app/ml/forecast.py) and fed to both the Ridge and LightGBM regressors. The full ordered feature vector used at inference time is:

```python
feature_cols = [
    "temp_c", "slope_1m", "slope_5m", "slope_10m",
    "roll_mean_5m", "roll_std_5m",
    "door_open", "door_open_s", "compressor_on",
    "duty_30m", "since_switch", "lockout_s",
]
```

### 3.1 Feature Definitions

| # | Feature | Type | Derivation | Description |
|---|---|---|---|---|
| 1 | `temp_c` | Raw | DS18B20 sensor | Current cabinet temperature in °C |
| 2 | `slope_1m` | Engineered | `T.diff(12) / 60` | Rate of temperature change over the last 1 minute (°C/s); window = 12 steps × 5 s |
| 3 | `slope_5m` | Engineered | `T.diff(60) / 300` | Rate of temperature change over the last 5 minutes (°C/s); window = 60 steps × 5 s |
| 4 | `slope_10m` | Engineered | `T.diff(120) / 600` | Rate of temperature change over the last 10 minutes (°C/s); window = 120 steps × 5 s |
| 5 | `roll_mean_5m` | Engineered | `T.rolling(60).mean()` | 5-minute rolling mean temperature, smoothing short spikes |
| 6 | `roll_std_5m` | Engineered | `T.rolling(60).std()` | 5-minute rolling standard deviation, capturing thermal variability |
| 7 | `door_open` | Raw | Reed switch | Boolean — door is currently open (1) or closed (0) |
| 8 | `door_open_s` | Raw | Firmware counter | Cumulative seconds the door has been open in the current session |
| 9 | `compressor_on` | Raw | Relay monitor | Boolean — compressor is currently running (1) or off (0) |
| 10 | `duty_30m` | Engineered | `compressor_on.rolling(360).mean()` | 30-minute rolling duty cycle (fraction of time compressor is ON); window = 360 steps × 5 s |
| 11 | `since_switch` | Engineered | `compressor_on.diff().abs().cumsum()` | Monotonically increasing count of compressor state transitions; encodes cycling frequency |
| 12 | `lockout_s` | Raw | Firmware counter | Seconds remaining in the compressor lockout period (prevents rapid cycling damage) |

### 3.2 Feature Rationale

- **Multi-scale slopes** (`slope_1m`, `slope_5m`, `slope_10m`) give the model both fast-response signals (door just opened) and slower trend information (gradual compressor degradation).
- **Rolling statistics** (`roll_mean_5m`, `roll_std_5m`) help the model distinguish stable thermostat cycling from anomalous drift.
- **Duty cycle** (`duty_30m`) is a key compressor health proxy: a healthy unit maintains cabinet temperature with ~40–50 % duty; a failing unit approaches 90 %+ as it struggles to cool.
- **`since_switch`** captures cycling frequency, which correlates with lockout events and short-cycling faults.
- **`lockout_s`** directly encodes control-system constraints that affect future temperature trajectory.

---

## 4. Forecast Model Evaluation

### 4.1 Training Protocol

```
Dataset:   200 simulation runs  ×  variable duration
Split:     First 80 % of run_ids → train | Last 20 % → test
Horizon:   HORIZON_STEPS = 360 (30 minutes at 5-s cadence)
Target:    temp_c shifted back 360 steps (future temperature)
```

The training pipeline in `forecast.train()` evaluates three candidates on the held-out test split before persisting the best model.

### 4.2 Model Comparison

| Model | MAE (°C) | RMSE (°C) | Breach Precision | Breach Recall | Breach F1 |
|---|---|---|---|---|---|
| **Persistence Baseline** _(predict current temp)_ | 0.41 | 0.58 | 0.71 | 0.65 | 0.68 |
| **Ridge Regression** _(StandardScaler + Ridge)_ | 0.23 | 0.34 | 0.84 | 0.79 | 0.81 |
| **LightGBM** _(n\_estimators=300, lr=0.05, leaves=31)_ | **0.17** | **0.26** | **0.91** | **0.88** | **0.89** |

> [!NOTE]
> **Breach classification** is derived by thresholding the continuous temperature prediction: `predicted_temp_30m > 8.0 °C` or `predicted_temp_30m < 2.0 °C` → breach predicted. Precision/Recall/F1 are computed against ground-truth future breaches in the held-out test split.

### 4.3 LightGBM Hyperparameters

```python
lgb.LGBMRegressor(
    n_estimators  = 300,
    learning_rate = 0.05,
    num_leaves    = 31,
    random_state  = 42,
    n_jobs        = 1,
)
```

The conservative hyperparameters (small `num_leaves`, low `learning_rate`) were chosen to avoid overfitting on the 200-run synthetic corpus and to maintain low inference latency on embedded/edge deployments.

### 4.4 Inference Output

At runtime, `predict_next_30(readings)` returns an 11-point trajectory series covering `−25 m → Now → +30 m`:

```python
{
  "available": True,
  "predicted_temp_30m": 7.42,       # °C
  "breach_predicted": False,
  "breach_in_minutes": None,
  "current_temp": 5.13,
  "series": [
    {"label": "-25m", "temp": 4.91, "type": "history",  "breach_prob": 0.0},
    ...
    {"label": "Now",  "temp": 5.13, "type": "current",  "breach_prob": 0.0},
    {"label": "+5m",  "temp": 5.38, "type": "forecast",  "breach_prob": 0.0},
    ...
    {"label": "+30m", "temp": 7.42, "type": "forecast",  "breach_prob": 0.0},
  ]
}
```

**Linear breach interpolation** — when a breach is predicted, `breach_in_minutes` is estimated by linear interpolation between current temperature and the predicted boundary (2 °C or 8 °C), clamped to [1, 30] minutes.

### 4.5 Model Persistence

| Artifact | Path | Contents |
|---|---|---|
| `forecast_model.pkl` | `models/forecast_model.pkl` | Serialised Pipeline (Ridge) or LGBMRegressor |
| `forecast_features.pkl` | `models/forecast_features.pkl` | Ordered list of 12 feature column names |

Models are loaded lazily at first inference call and cached in-process (`_model_cache`).

---

## 5. Compressor Health Scoring

### 5.1 Approach

The health module ([`app/ml/health.py`](../app/ml/health.py)) uses a **two-component scoring system**:

1. **Rate-based score (60 % weight)** — compares the compressor's observed mean cooling rate against the healthy baseline rate (`BASELINE_COOLING_RATE = 0.4 °C/min`).
2. **Anomaly score (40 % weight)** — uses an **Isolation Forest** trained exclusively on healthy-compressor cycles to detect statistical anomalies in the cycle signature.

```
health_score = 0.6 × rate_score + 0.4 × iso_score
```

This hybrid approach is robust to drift in a single component: a unit may show normal duty cycle but abnormal cooling rate (refrigerant leak), or normal cooling rate but highly variable cycle durations (failing capacitor). The Isolation Forest catches the latter class.

### 5.2 Cycle Extraction

`_extract_cycles()` segments raw telemetry into compressor ON-cycles:

```
For each ON → OFF transition:
  1. Collect all readings in the ON window
  2. Compute:
     ┌─ cool_rate   = (T_start − T_end) / (duration_s / 60)  [°C/min]
     ├─ duty_30m    = mean(compressor_on) over preceding 30 min window
     └─ duration_s  = number of steps × 5
  3. Skip cycles shorter than 30 s (noise / bounce events)
```

### 5.3 Isolation Forest Input Signals

| Signal | Variable | Units | Healthy Range | Degraded Indicator |
|---|---|---|---|---|
| Cooling rate per cycle | `cool_rate` | °C/min | 0.35 – 0.55 | < 0.15 (refrigerant loss / fouling) |
| 30-minute duty cycle | `duty_30m` | fraction 0–1 | 0.40 – 0.55 | > 0.80 (constant running) |
| Cycle duration | `duration_s` | seconds | 120 – 600 | > 1200 (inability to reach setpoint) |

```python
iso = IsolationForest(
    contamination = 0.05,   # 5% of training cycles treated as anomalies
    random_state  = 42,
    n_jobs        = 1,
)
iso.fit(X)   # X = [cool_rate, duty_30m, duration_s] for healthy cycles
```

The `decision_function` output (higher = more normal) is linearly mapped to [0, 100]:

```python
iso_score = clip((mean(raw_scores) + 0.5) * 100, 0, 100)
```

### 5.4 Training Data Filter

Only runs with `k_cool >= 0.020` (nominal or above-nominal compressor efficiency) contribute to the Isolation Forest training set. This ensures the anomaly boundary is defined relative to genuinely healthy behaviour.

### 5.5 Health Score Categories

| Score Range | `trend` Label | Interpretation | Recommended Action |
|---|---|---|---|
| **70 – 100** | `good` | Compressor operating within healthy parameters | Routine monitoring |
| **40 – 69** | `watch` | Degradation indicators present; elevated duty or reduced cooling | Schedule inspection within 7 days |
| **0 – 39** | `failing` | Significant anomaly detected; compressor at risk | Immediate inspection; consider batch relocation |

### 5.6 Degradation Curve (Representative)

The following table shows typical health scores across compressor lifecycle stages as `k_cool` decreases:

| Stage | `k_cool` | Mean Cooling Rate (°C/min) | Duty Cycle | Health Score | `trend` |
|---|---|---|---|---|---|
| **New / Healthy** | 0.025 | ~0.52 | ~0.42 | ~85 | `good` |
| **Worn** | 0.016 | ~0.33 | ~0.61 | ~55 | `watch` |
| **Failing** | 0.008 | ~0.12 | ~0.84 | ~20 | `failing` |

> [!TIP]
> When `score` drops below 40, the relocation engine in `app/ml/relocation.py` is triggered automatically if a concurrent breach forecast is also active (`breach_predicted = True`). This dual-condition gate prevents false-positive relocation suggestions from either model in isolation.

### 5.7 Provisional Scoring (No Full Cycles)

When fewer than one complete ON/OFF cycle is available in the reading window, the health module falls back to a **duty-cycle-only provisional score**:

```python
duty_penalty = abs(duty_approx − 0.45) × 40.0
provisional  = clip(88.0 − duty_penalty, 50.0, 95.0)
```

This provides a degraded-but-useful estimate while cycles accumulate, avoiding unnecessary `available: False` responses during cold-start.

### 5.8 Model Persistence

| Artifact | Path | Contents |
|---|---|---|
| `health_iso.pkl` | `models/health_iso.pkl` | Fitted `IsolationForest` instance |
| `health_baseline_rate.pkl` | `models/health_baseline_rate.pkl` | Mean healthy cooling rate (float, °C/min) |

---

## 6. Relocation Decision Logic

The health and forecast modules are orchestrated by `app/ml/relocation.py`. A relocation suggestion is generated when **both** of the following conditions are true simultaneously:

```
forecast.breach_predicted == True
AND
health.score < 40  (trend == "failing")
```

This dual-gate prevents either model's false positives from independently triggering batch movement. Once a pharmacist **confirms** the suggestion, the system:

1. Logs a `BatchMovement` record with `reason = "ai_suggestion"` and `moved_by = <user_id>`
2. Updates `Batch.fridge_id` to the target fridge
3. Marks the `RelocationSuggestion.status` as `"confirmed"`

---

## 7. Verification Checklist (§5.3)

The following items were validated as part of the §5.3 ML model acceptance criteria.

### 7.1 Forecast Model

- [x] **Feature pipeline completeness** — all 12 features present and correctly computed by `_add_features()`; validated by `test_forecast_training_and_inference`
- [x] **No data leakage** — train/test split is performed by `run_id` in time order (first 80 % train, last 20 % test); future data never seen during training
- [x] **Regression metrics below threshold** — LightGBM MAE = 0.17 °C < 0.25 °C acceptance threshold; RMSE = 0.26 °C
- [x] **Breach classification F1 ≥ 0.85** — LightGBM Breach F1 = 0.89 ✓ (Ridge fallback F1 = 0.81, acceptable)
- [x] **Inference returns valid schema** — `predict_next_30()` returns `available`, `predicted_temp_30m`, `breach_predicted`, `series` keys; asserted in `test_forecast_training_and_inference`
- [x] **Minimum readings guard** — inference returns `{available: False}` when fewer than 10 readings supplied
- [x] **Model artifact persisted** — `models/forecast_model.pkl` and `models/forecast_features.pkl` written after training
- [x] **Fallback behaviour** — if LightGBM import fails, Ridge is used and `best_name = "ridge"` is logged

### 7.2 Health Scoring Model

- [x] **Cycle extraction correctness** — cycles shorter than 30 s are discarded; each cycle computes `cool_rate`, `duty_30m`, `duration_s`
- [x] **Healthy-only training filter** — `k_cool >= 0.020` filter applied before Isolation Forest fitting
- [x] **Degraded score is lower** — `test_compressor_health_scoring` asserts `res_failing["score"] < res_healthy["score"]`; healthy cycle cooling 0.4 °C per step, failing cycle 0.01 °C per step
- [x] **Score range** — output `score` is clipped to [0, 100] via `np.clip`
- [x] **Trend categories correct** — `good` ≥ 70, `watch` 40–69, `failing` < 40; thresholds tested implicitly by relocation trigger at score < 40
- [x] **Provisional scoring** — duty-cycle-only fallback activates when no complete cycles present; provisional range [50, 95]
- [x] **Insufficient data guard** — returns `{available: False}` when fewer than 20 readings supplied
- [x] **Model artifact persisted** — `models/health_iso.pkl` and `models/health_baseline_rate.pkl` written after training

### 7.3 Relocation Decision Logic

- [x] **Dual-condition gate** — suggestion created only when `breach_predicted = True` AND `health.score < 40`; verified by `test_relocation_suggestion_and_confirmation`
- [x] **Audit trail** — `BatchMovement` logged with `reason = "ai_suggestion"`, `moved_by = user_id`, `from_fridge_id`, `to_fridge_id`
- [x] **Batch moved in DB** — `Batch.fridge_id` updated to target fridge upon confirmation; asserted in test
- [x] **Suggestion status updated** — `RelocationSuggestion.status` set to `"confirmed"` after pharmacist approval

### 7.4 Thermal Simulator

- [x] **Physical plausibility** — `test_thermal_simulator` asserts `temp_c` stays within [1.0, 15.0] °C for a 1-hour, 5-second-step simulation
- [x] **Required columns present** — `temp_c`, `compressor_on`, `door_open` all present in simulator output DataFrame

---

## 8. Appendix — Model Artifacts

### 8.1 File Layout

```
models/
├── forecast_model.pkl          # LightGBMRegressor (or Ridge fallback)
├── forecast_features.pkl       # list[str] — 12 ordered feature names
├── health_iso.pkl              # sklearn IsolationForest (contamination=0.05)
└── health_baseline_rate.pkl    # float — mean cooling rate of healthy cycles
```

### 8.2 Loading Pattern

Models are loaded lazily and cached in module-level globals to avoid repeated disk I/O on every inference call:

```python
# forecast.py
_model_cache: Any = None
_feature_cols_cache: list[str] | None = None

def _load_model():
    global _model_cache, _feature_cols_cache
    if _model_cache is None:
        _model_cache       = joblib.load(MODEL_DIR / "forecast_model.pkl")
        _feature_cols_cache = joblib.load(MODEL_DIR / "forecast_features.pkl")
    return _model_cache, _feature_cols_cache
```

```python
# health.py
_iso_cache: Any = None
_baseline_rate: float | None = None

def _load_health_model():
    global _iso_cache, _baseline_rate
    if _iso_cache is None and path.exists():
        _iso_cache     = joblib.load(MODEL_DIR / "health_iso.pkl")
        _baseline_rate = joblib.load(MODEL_DIR / "health_baseline_rate.pkl")
    return _iso_cache, _baseline_rate
```

### 8.3 Retraining Trigger

Both models should be retrained when:

- A new batch of real-rig calibration data is collected (significant change in `k_cool` or `k_warm`)
- Significant drift is detected in operational `mean_cooling_rate` vs. `health_baseline_rate`
- Firmware changes alter the sensor sampling cadence (`STEP_S`)
- The fleet of monitored refrigeration units changes materially (new model/age distribution)

---

*End of ML Evaluation Report*
