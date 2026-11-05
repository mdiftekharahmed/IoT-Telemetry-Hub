"""CRUD tests for ColdChain fridge & device registry (DB-backed HMAC secrets).

Covers:
- Fridge: create / read / update (incl. device re-binding) / delete + RBAC
- Device: create (generated or user-set secret) / list / patch (set secret,
  rotate, rebind) / reveal / delete (+force purge) + RBAC
- Secret provenance: ingestion accepts telemetry signed with the DB-stored
  secret even when no legacy env-style secrets map is provided at all.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cc_ingestion import ingest_telemetry
from app.models import Device, Fridge, Reading, User
from app.security import create_tokens, canonical_json, hmac_sign, password_hasher

USER_SECRET = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
USER_SECRET_NEW = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"


@pytest.fixture
def cc_session(application):
    """Seed 3 ColdChain users + 2 devices and return (client-accessible) tokens."""
    with application.state.sessions.begin() as db:
        users = {
            role: User(username=f"crud_{role}",
                       bcrypt_hash=password_hasher.hash("pass"),
                       role=role, active=True)
            for role in ("admin", "pharmacist", "inspector")
        }
        for u in users.values():
            db.add(u)
        db.add(Device(device_id="fridge-A", name="Fridge A", enabled=True,
                      mqtt_password=USER_SECRET))
        db.add(Device(device_id="fridge-B", name="Fridge B", enabled=True))
        db.flush()
        secret = application.state.settings.coldchain_jwt_secret
        tokens = {role: create_tokens(u, secret)["access_token"]
                  for role, u in users.items()}
    return {"tokens": tokens, "factory": application.state.sessions}


def _client(client: TestClient, session: dict, role: str) -> TestClient:
    client.headers["Authorization"] = f"Bearer {session['tokens'][role]}"
    return client


def _admin(client: TestClient, session: dict) -> TestClient:
    return _client(client, session, "admin")


# ── Fridge CRUD ───────────────────────────────────────────────────────────────

def test_fridge_create_read_update_delete(client, cc_session):
    c = _admin(client, cc_session)

    # CREATE with device binding
    r = c.post("/api/fridges", json={
        "name": " Pharmacy Store A", "capacity_slots": 8,
        "location": "Ward 1", "device_id": "fridge-A",
    })
    assert r.status_code == 201
    fridge = r.json()
    assert fridge["name"] == "Pharmacy Store A"  # trimmed
    assert fridge["device_id"] == "fridge-A"
    fid = fridge["id"]

    # Two-way binding is consistent in the DB
    with cc_session["factory"]() as db:
        dev = db.get(Device, "fridge-A")
        assert dev.fridge_id == fid

    # READ (any role)
    r = _client(client, cc_session, "inspector").get(f"/api/fridges/{fid}")
    assert r.status_code == 200
    assert r.json()["capacity_slots"] == 8
    assert r.json()["batches"] == []
    c = _admin(client, cc_session)  # restore admin header (shared TestClient instance)

    # UPDATE fields
    r = c.patch(f"/api/fridges/{fid}", json={"name": "Store A-2", "capacity_slots": 12})
    assert r.status_code == 200
    assert r.json()["name"] == "Store A-2"
    assert r.json()["capacity_slots"] == 12

    # READ after update
    r = c.get(f"/api/fridges/{fid}")
    assert r.json()["name"] == "Store A-2"

    # UPDATE: re-bind to another device
    r = c.patch(f"/api/fridges/{fid}", json={"device_id": "fridge-B"})
    assert r.status_code == 200
    assert r.json()["device_id"] == "fridge-B"
    with cc_session["factory"]() as db:
        assert db.get(Device, "fridge-A").fridge_id is None      # old unbound
        assert db.get(Device, "fridge-B").fridge_id == fid       # new bound
        assert db.get(Fridge, fid).device_id == "fridge-B"

    # UPDATE: unbind completely
    r = c.patch(f"/api/fridges/{fid}", json={"device_id": None})
    assert r.status_code == 200
    assert r.json()["device_id"] is None
    with cc_session["factory"]() as db:
        assert db.get(Device, "fridge-B").fridge_id is None

    # DELETE
    r = c.delete(f"/api/fridges/{fid}")
    assert r.status_code == 204
    assert c.get(f"/api/fridges/{fid}").status_code == 404

    # Audit trail recorded the whole lifecycle
    r = c.get("/api/audit", params={"per_page": 20})
    actions = {e["action"] for e in r.json()["entries"]}
    assert {"FRIDGE_CREATED", "FRIDGE_UPDATED", "FRIDGE_DELETED"} <= actions


def test_fridge_rbac(client, cc_session):
    c = _admin(client, cc_session)
    r = c.post("/api/fridges", json={"name": "R1"})
    fid = r.json()["id"]

    # pharmacist / inspector cannot mutate fridges
    for role in ("pharmacist", "inspector"):
        cl = _client(client, cc_session, role)
        assert cl.post("/api/fridges", json={"name": "nope"}).status_code == 403
        assert cl.patch(f"/api/fridges/{fid}", json={"name": "x"}).status_code == 403
        assert cl.delete(f"/api/fridges/{fid}").status_code == 403
    # but can read
    assert _client(client, cc_session, "inspector").get(f"/api/fridges/{fid}").status_code == 200


# ── Device CRUD ───────────────────────────────────────────────────────────────

def test_device_create_generated_secret(client, cc_session):
    c = _admin(client, cc_session)
    r = c.post("/api/cc/devices", json={"device_id": "fridge-C", "name": "Fridge C"})
    assert r.status_code == 201
    body = r.json()
    secret = body["secret"]
    assert len(secret) == 64 and int(secret, 16) >= 0      # valid 64-hex
    assert body["has_secret"] is True
    # scrubbed on subsequent listings
    r = c.get("/api/cc/devices")
    listed = next(d for d in r.json() if d["device_id"] == "fridge-C")
    assert "secret" not in listed and listed["has_secret"] is True


def test_device_create_user_set_secret(client, cc_session):
    c = _admin(client, cc_session)
    r = c.post("/api/cc/devices", json={
        "device_id": "fridge-C", "name": "Fridge C",
        "secret": USER_SECRET.upper(),          # case-insensitive → stored lowercase
    })
    assert r.status_code == 201
    assert r.json()["secret"] == USER_SECRET.lower()
    with cc_session["factory"]() as db:
        assert db.get(Device, "fridge-C").mqtt_password == USER_SECRET.lower()


def test_device_create_rejects_bad_secret(client, cc_session):
    c = _admin(client, cc_session)
    bad = {"device_id": "fridge-X", "name": "X", "secret": "short"}
    assert c.post("/api/cc/devices", json=bad).status_code == 422
    assert c.post("/api/cc/devices", json={
        "device_id": "fridge-A", "name": "dup"}).status_code == 409
    # device with fridge binding to an occupied fridge
    fr = c.post("/api/fridges", json={"name": "F1", "device_id": "fridge-A"}).json()
    assert c.post("/api/cc/devices", json={
        "device_id": "fridge-Y", "name": "Y", "fridge_id": fr["id"]}).status_code == 409


def test_device_edit_secret_and_ingestion_uses_db(client, cc_session):
    """Patch the secret → DB value is the one used by ingestion (no env map)."""
    c = _admin(client, cc_session)
    # fridge-A already exists with USER_SECRET; replace with a new user secret
    r = c.patch("/api/cc/devices/fridge-A", json={"secret": USER_SECRET_NEW})
    assert r.status_code == 200
    assert r.json()["secret"] == USER_SECRET_NEW
    with cc_session["factory"]() as db:
        assert db.get(Device, "fridge-A").mqtt_password == USER_SECRET_NEW

    def signed(secret: str, seq: int, nonce: str) -> bytes:
        data = {"temp_c": 4.0, "compressor_on": False, "door_open": False,
                "door_open_s": 0, "lockout_s": 0, "power_source": "MAINS",
                "mains_present": True, "battery_pct": 99.0, "battery_v": 4.2,
                "state": "SAFE", "red_latched": False, "sim_mode": True}
        parts = ["fridge-A", str(seq), str(time.time()), nonce, canonical_json(data)]
        return json.dumps({"v": 1, "dev": "fridge-A", "seq": seq, "ts": parts[2],
                           "nonce": nonce, "d": data, "sig": hmac_sign(secret, parts)}).encode()

    # accepted with the NEW db-stored secret and NO env-style secrets map
    res = ingest_telemetry(cc_session["factory"], "cc/fridge-A/telemetry",
                           signed(USER_SECRET_NEW, 1, "n1"), {})
    assert res.status == "accepted"
    # rejected with the OLD (pre-edit) secret
    res = ingest_telemetry(cc_session["factory"], "cc/fridge-A/telemetry",
                           signed(USER_SECRET, 2, "n2"), {})
    assert res.status == "rejected"


def test_device_rotate_and_reveal(client, cc_session):
    c = _admin(client, cc_session)
    with cc_session["factory"]() as db:
        old = db.get(Device, "fridge-A").mqtt_password

    r = c.patch("/api/cc/devices/fridge-A", json={"rotate": True})
    assert r.status_code == 200
    rotated = r.json()["secret"]
    assert rotated != old and len(rotated) == 64

    # reveal endpoint returns the stored secret
    r = c.get("/api/cc/devices/fridge-A/secret")
    assert r.status_code == 200
    assert r.json()["secret"] == rotated

    # audit chain logs rotation + viewing but never a secret value
    r = c.get("/api/audit", params={"per_page": 10})
    entries = [e for e in r.json()["entries"]
               if e["action"].startswith("DEVICE_SECRET")]
    assert any(e["action"] == "DEVICE_SECRET_ROTATED" for e in entries)
    assert any(e["action"] == "DEVICE_SECRET_VIEWED" for e in entries)
    for e in entries:
        assert len(json.dumps(e["payload"])) < len(rotated)  # no 64-hex blob inside

    # RBAC: vendor-staff roles cannot rotate / reveal
    for role in ("pharmacist", "inspector"):
        cl = _client(client, cc_session, role)
        assert cl.patch("/api/cc/devices/fridge-A", json={"rotate": True}).status_code == 403
        assert cl.get("/api/cc/devices/fridge-A/secret").status_code == 403


def test_device_patch_rebind_and_update(client, cc_session):
    c = _admin(client, cc_session)
    fr = c.post("/api/fridges", json={"name": "R2"}).json()
    r = c.patch("/api/cc/devices/fridge-B", json={"fridge_id": fr["id"], "enabled": False})
    assert r.status_code == 200
    assert r.json()["fridge_id"] == fr["id"]
    assert r.json()["enabled"] is False
    with cc_session["factory"]() as db:
        assert db.get(Device, "fridge-B").fridge_id == fr["id"]
        assert db.get(Fridge, fr["id"]).device_id == "fridge-B"
    # a device bound to another fridge cannot be stolen via fridge patch
    fr3 = c.post("/api/fridges", json={"name": "R3", "device_id": "fridge-A"}).json()
    r = c.patch(f"/api/fridges/{fr['id']}", json={"device_id": "fridge-A"})
    assert r.status_code == 409
    # clean up: unbind then delete spare fridge
    assert c.patch(f"/api/fridges/{fr3['id']}", json={"device_id": None}).status_code == 200
    assert c.delete(f"/api/fridges/{fr3['id']}").status_code == 204


def test_device_delete_guards_history(client, cc_session):
    c = _admin(client, cc_session)
    factory = cc_session["factory"]
    # give fridge-A one reading through direct DB insert
    with factory.begin() as db:
        db.add(Reading(device_id="fridge-A", seq=1, ts=__import__("datetime").datetime.now(
            __import__("datetime").UTC), temp_c=4.0))

    assert c.delete("/api/cc/devices/fridge-A").status_code == 409
    assert c.delete("/api/cc/devices/fridge-A", params={"force": "true"}).status_code == 204
    with factory() as db:
        assert db.get(Device, "fridge-A") is None
        assert db.scalars(select(Reading).where(Reading.device_id == "fridge-A")).all() == []

    # device without history deletes cleanly
    assert c.delete("/api/cc/devices/fridge-B").status_code == 204
    with factory() as db:
        assert db.get(Device, "fridge-B") is None
