"""sim_seed.py ↔ server compatibility + relocation auto-trigger wiring.

Covers:
- A FridgeSim snapshot built through sim_seed's real data path, signed with
  the same stable secret it registers, is ACCEPTED by app.cc_ingestion using
  the DB-stored secret (empty legacy secrets map — proves DB-first lookup).
- Device registration endpoint behaves like the script expects (create → 201,
  duplicate → 409, single GET device → 200 with no secret inside).
- The AI relocation auto-trigger hooks into the ingest path and runs on the
  right cadence (immediately when temp > safe_max, else every 25th reading).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.cc_ingestion import ingest_telemetry
from app.models import Device, Fridge, RelocationSuggestion

from sim_seed import FridgeSim, build_envelope, stable_secret

SIM_DEV = "sim-fridge-01"
SIM_SECRET = stable_secret(SIM_DEV)


@pytest.fixture
def sim_device(application):
    """Register the sim device as if sim_seed's ensure_device had run."""
    with application.state.sessions.begin() as db:
        db.add(Device(device_id=SIM_DEV, name="Sim Fridge", enabled=True,
                      mqtt_password=SIM_SECRET))
    return SIM_DEV


def _mk_engine(application):
    return application.state.sessions


def test_sim_envelope_accepted_through_real_ingestion(application, sim_device):
    """The exact bytes sim_seed publishes are accepted server-side, from DB secret."""
    factory = _mk_engine(application)
    sim = FridgeSim(device_id=SIM_DEV, secret=SIM_SECRET, scenario="normal")

    accepted = 0
    for _ in range(5):
        sim.seq += 1
        d = sim.tick(5.0)
        envelope = build_envelope(SIM_DEV, SIM_SECRET, sim.seq, d)
        res = ingest_telemetry(factory, f"cc/{SIM_DEV}/telemetry", envelope, {})
        assert res.status == "accepted", f"sim message rejected: {res}"
        accepted += 1

    # rows persisted, everything server-side
    with factory() as db:
        n = db.scalar(select(func.count()).select_from(
            __import__("app.models", fromlist=["Reading"]).Reading
        ).where(__import__("app.models", fromlist=["Reading"]).Reading.device_id == SIM_DEV))
        assert n == accepted


def test_sim_roundtrip_field_contract(application, sim_device):
    """Every field the sim sends is in the server's allow-list; none extra."""
    from app.cc_ingestion import ALLOWED_DATA_FIELDS
    sim = FridgeSim(device_id=SIM_DEV, secret=SIM_SECRET, scenario="breach")
    sim.seq = 1
    d = sim.tick(5.0)
    allowed = {
        "temp_c", "door_open", "door_open_s", "compressor_on", "lockout_s",
        "power_source", "mains_present", "battery_pct", "battery_v",
        "state", "red_latched", "sim_mode",
    }
    assert set(d.keys()) == allowed == ALLOWED_DATA_FIELDS
    envelope = build_envelope(SIM_DEV, SIM_SECRET, sim.seq, d)
    res = ingest_telemetry(_mk_engine(application), f"cc/{SIM_DEV}/telemetry", envelope, {})
    assert res.status == "accepted"


def test_registration_api_matches_script_flow(client, application):
    """The script's POST → 409-on-duplicate → GET-single flow works, no secret leak."""
    secret = stable_secret(SIM_DEV)
    headers = {}  # auth via legacy admin login below is not needed for cc — seed token

    from app.models import User
    from app.security import create_tokens, password_hasher
    with application.state.sessions.begin() as db:
        u = User(username="sim_admin", bcrypt_hash=password_hasher.hash("x"), role="admin", active=True)
        db.add(u)
        db.flush()
        headers = {"Authorization": "Bearer " + create_tokens(
            u, application.state.settings.coldchain_jwt_secret)["access_token"]}

    # create (user-set secret path)
    r = client.post("/api/cc/devices", headers=headers, json={
        "device_id": SIM_DEV, "name": "Sim Fridge", "secret": secret, "enabled": True})
    assert r.status_code == 201
    # duplicate → script treats 409 as already-registered success
    assert client.post("/api/cc/devices", headers=headers, json={
        "device_id": SIM_DEV, "name": "Sim Fridge", "secret": secret}).status_code == 409
    # single GET exists & never contains the secret
    r = client.get(f"/api/cc/devices/{SIM_DEV}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["device_id"] == SIM_DEV and body["has_secret"] is True
    assert "secret" not in body and "mqtt_password" not in body


def test_relocation_autotrigger_wired(application, sim_device):
    """The ingest path invokes the relocation trigger on the right cadence."""
    calls = []
    import app.ml.relocation as rel_mod

    real = rel_mod.check_and_trigger_relocation

    def recorder(db, fridge_id, bot_token="", chat_id=""):
        calls.append(fridge_id)
        return real(db, fridge_id, bot_token=bot_token, chat_id=chat_id)

    # both the lazy-import inside cc_ingestion and direct refs see the patch
    monkey_rel = pytest.MonkeyPatch()
    monkey_rel.setattr(rel_mod, "check_and_trigger_relocation", recorder)
    try:
        factory = _mk_engine(application)

        # give the device a fridge so the trigger location resolves
        # (two-way binding, as the CRUD endpoints do)
        fr = Fridge(name="SimFridge", device_id=SIM_DEV)
        with factory.begin() as db:
            db.add(fr)
            dev = db.get(Device, SIM_DEV)
            dev.fridge_id = fr.id

        sim = FridgeSim(device_id=SIM_DEV, secret=SIM_SECRET, scenario="normal")
        hot = FridgeSim(device_id=SIM_DEV, secret=SIM_SECRET, scenario="normal")
        hot.temp_c = 12.0  # above safe_max → immediate trigger path

        for seq in range(1, 6):
            sim.seq = seq
            d = sim.tick(5.0)
            ingest_telemetry(factory, f"cc/{SIM_DEV}/telemetry",
                             build_envelope(SIM_DEV, SIM_SECRET, seq, d), {})
        # normal cadence: only seq=25 multiples trigger → 0 calls so far
        assert calls == []

        sim.seq = 25
        d = sim.tick(5.0)
        ingest_telemetry(factory, f"cc/{SIM_DEV}/telemetry",
                         build_envelope(SIM_DEV, SIM_SECRET, 25, d), {})
        assert len(calls) == 1

        # hot reading → immediate call regardless of seq
        hot.seq = 30
        d = hot.tick(5.0)
        ingest_telemetry(factory, f"cc/{SIM_DEV}/telemetry",
                         build_envelope(SIM_DEV, SIM_SECRET, 30, d), {})
        assert len(calls) == 2
    finally:
        monkey_rel.undo()
