"""Thermal simulator: same physics as the firmware SIM_MODE.

dT/dt = (T_amb - T) / tau  -  k * compressor_on  +  d * door_open  +  noise

Generates synthetic runs for ML training.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Generator

import numpy as np
import pandas as pd


@dataclass
class SimParams:
    # Thermal model
    T_amb:       float = 22.0     # ambient °C
    tau:         float = 600.0    # thermal time constant, s
    k_cool:      float = 0.025    # cooling rate per second when compressor ON
    d_door:      float = 0.005    # heating rate per second when door open
    noise_std:   float = 0.02     # °C per step Gaussian noise

    # Compressor FSM
    T_on:        float = 7.0
    T_off:       float = 3.0
    min_off_s:   int   = 60

    # Simulation
    dt_s:        float = 5.0      # step size seconds (matches firmware publish rate)
    duration_s:  float = 3600.0   # default 1 hour


def simulate_run(params: SimParams, seed: int | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = int(params.duration_s / params.dt_s)
    T = params.T_off + (params.T_on - params.T_off) * rng.random()  # random start

    comp_on       = False
    lockout_s     = 0.0
    door_open     = False
    door_timer_s  = 0.0

    records = []
    t = 0.0
    for _ in range(steps):
        # Compressor FSM
        if comp_on and T <= params.T_off:
            comp_on   = False
            lockout_s = params.min_off_s
        elif not comp_on and lockout_s <= 0 and T >= params.T_on:
            comp_on = True
        if lockout_s > 0:
            lockout_s = max(0.0, lockout_s - params.dt_s)

        # Thermal model
        dT = (params.T_amb - T) / params.tau \
             - params.k_cool * float(comp_on) \
             + params.d_door * float(door_open) \
             + rng.normal(0, params.noise_std)
        T += dT * params.dt_s
        T  = max(-5.0, min(35.0, T))

        # State
        if T < 2.0 or T > 8.0:
            state = "BREACH"
        elif T < 2.5 or T > 7.5 or door_open:
            state = "WARNING"
        else:
            state = "SAFE"

        records.append({
            "t_s":          t,
            "temp_c":       round(T, 3),
            "compressor_on": int(comp_on),
            "door_open":    int(door_open),
            "door_open_s":  door_timer_s,
            "lockout_s":    lockout_s,
            "state":        state,
        })
        t += params.dt_s
        door_timer_s = door_timer_s + params.dt_s if door_open else 0.0

    return pd.DataFrame(records)


def generate_dataset(n_runs: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate diverse synthetic runs and concatenate into one DataFrame."""
    rng = random.Random(seed)
    frames = []

    for i in range(n_runs):
        params = SimParams(
            T_amb     = rng.uniform(18.0, 30.0),
            tau       = rng.uniform(400.0, 800.0),
            k_cool    = rng.uniform(0.015, 0.040) * (0.5 if i % 5 == 0 else 1.0),  # weak comp
            d_door    = rng.uniform(0.003, 0.010),
            noise_std = rng.uniform(0.01, 0.05),
            duration_s = rng.uniform(1800.0, 7200.0),
        )
        df = simulate_run(params, seed=seed + i)
        df["run_id"]  = i
        df["k_cool"]  = params.k_cool
        df["T_amb"]   = params.T_amb
        frames.append(df)

    return pd.concat(frames, ignore_index=True)
