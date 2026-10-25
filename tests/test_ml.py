"""Unit and integration tests for ColdChain ML models (forecast, health scoring, relocation)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from app.ml.forecast import predict_next_30, train as train_forecast
from app.ml.health import score_health, train_health
from app.ml.relocation import build_suggestion, confirm_suggestion
from app.ml.simulator import generate_dataset, run_simulation
from app.models import Batch, BatchMovement, Fridge, Reading, RelocationSuggestion, User


def test_thermal_simulator():
    """Simulator produces valid physical trajectories with compressor cycling."""
    df = run_simulation(duration_hours=1.0, step_s=5, k_cool=0.016, run_id=0)
    assert not df.empty
    assert "temp_c" in df.columns
    assert "compressor_on" in df.columns
    assert "door_open" in df.columns

    # Verify temperature stays within plausible bounds
    assert df["temp_c"].min() >= 1.0
    assert df["temp_c"].max() <= 15.0


def test_forecast_training_and_inference():
    """Train forecast model on a small simulated batch and perform inference."""
    dataset = generate_dataset(n_runs=4, duration_hours=0.5, step_s=5)
    results = train_forecast(dataset)

    assert "baseline_mae" in results
    assert "ridge_mae" in results
    assert results["train_samples"] > 0

    # Perform inference with recent synthetic readings
    recent_readings = [
        {
            "t_s": i * 5,
            "temp_c": 5.0 + 0.05 * i,
            "door_open": False,
            "door_open_s": 0,
            "compressor_on": True,
            "lockout_s": 0,
            "power_source": "MAINS",
            "mains_present": True,
            "battery_pct": 100.0,
            "battery_v": 4.18,
            "state": "SAFE",
            "red_latched": False,
            "sim_mode": True,
        }
        for i in range(50)
    ]

    pred = predict_next_30(recent_readings)
    assert pred["available"] is True
    assert "predicted_temp_30m" in pred
    assert isinstance(pred["breach_predicted"], bool)


def test_compressor_health_scoring():
    """Degraded compressor with low cooling rate scores significantly lower."""
    dataset = generate_dataset(n_runs=4, duration_hours=0.5, step_s=5)
    train_health(dataset)

    # 1. Healthy run (fast cooling cycles)
    healthy_readings = []
    t = 0
    for cycle in range(5):
        # 10 steps cooling from 7 to 3
        for step in range(10):
            healthy_readings.append({
                "t_s": t, "temp_c": 7.0 - (step * 0.4), "compressor_on": True,
                "door_open": False, "door_open_s": 0, "lockout_s": 0,
            })
            t += 5
        # 10 steps off warming from 3 to 7
        for step in range(10):
            healthy_readings.append({
                "t_s": t, "temp_c": 3.0 + (step * 0.4), "compressor_on": False,
                "door_open": False, "door_open_s": 0, "lockout_s": 0,
            })
            t += 5

    res_healthy = score_health(healthy_readings)
    assert res_healthy["available"] is True

    # 2. Failing / weak compressor (very slow cooling, high duty cycle)
    failing_readings = []
    t = 0
    for cycle in range(5):
        # 40 steps to barely cool from 7 to 6.5
        for step in range(40):
            failing_readings.append({
                "t_s": t, "temp_c": 7.0 - (step * 0.01), "compressor_on": True,
                "door_open": False, "door_open_s": 0, "lockout_s": 0,
            })
            t += 5
        # 10 steps off
        for step in range(10):
            failing_readings.append({
                "t_s": t, "temp_c": 6.5 + (step * 0.05), "compressor_on": False,
                "door_open": False, "door_open_s": 0, "lockout_s": 0,
            })
            t += 5

    res_failing = score_health(failing_readings)
    assert res_failing["available"] is True
    # Failing score must be substantially lower than healthy
    assert res_failing["score"] < res_healthy["score"]


def test_relocation_suggestion_and_confirmation(application):
    """Triggered relocation creates suggestion and executing it moves the batch."""
    factory = application.state.sessions

    with factory.begin() as db:
        user = User(username="dr_pharmacist", bcrypt_hash="dummy", role="pharmacist", active=True)
        db.add(user)
        db.flush()
        user_id = user.id

        fridge1 = Fridge(name="FailingFridge", capacity_slots=5, device_id="dev-fail")
        fridge2 = Fridge(name="HealthyFridge", capacity_slots=5, device_id="dev-good")
        db.add_all([fridge1, fridge2])
        db.flush()
        f1_id, f2_id = fridge1.id, fridge2.id

        # Seed latest reading for healthy fridge (temp 4.0, compressor healthy, door closed)
        db.add(Reading(
            device_id="dev-good", seq=1, ts=datetime.now(tz=UTC), temp_c=4.0,
            door_open=False, compressor_on=False, lockout_s=0,
            power_source="MAINS", mains_present=True, state="SAFE",
            red_latched=False, sim_mode=True, ingested_at=datetime.now(tz=UTC),
        ))

        batch = Batch(
            code="BATCH-RELO-1",
            vaccine_name="Rabies Vaccine",
            qty=30,
            fridge_id=f1_id,
            status="OK",
            exposure_weighted_min=10.0,
            qr_token="qr-relo-1",
        )
        db.add(batch)
        db.flush()
        batch_id = batch.id

        # Build suggestion triggered by health alert
        forecast_res = {"breach_predicted": True}
        health_res = {"score": 25.0, "trend": "failing"}
        sugg = build_suggestion(db, f1_id, forecast_res, health_res)
        assert sugg is not None
        sugg_id = sugg.id

    # Confirm suggestion
    with factory.begin() as db:
        moves = confirm_suggestion(db, sugg_id, user_id, actor="dr_pharmacist")
        assert len(moves) == 1
        assert moves[0].batch_id == batch_id
        assert moves[0].from_fridge_id == f1_id
        assert moves[0].to_fridge_id == f2_id

    # Verify batch moved in DB and movement logged
    with factory() as db:
        b = db.get(Batch, batch_id)
        assert b.fridge_id == f2_id

        mv = db.scalar(select(BatchMovement).where(BatchMovement.batch_id == batch_id))
        assert mv is not None
        assert mv.reason == "ai_suggestion"
        assert mv.moved_by == user_id

        s = db.get(RelocationSuggestion, sugg_id)
        assert s.status == "confirmed"
