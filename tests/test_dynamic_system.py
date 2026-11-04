"""Tests for the dynamic configuration system, dual forecast, and explorer."""

import json
from datetime import UTC, datetime, timedelta
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.db import build_engine, session_factory
from app.models import Batch, Device, Fridge, Reading, User
from app.thresholds import get_thresholds, update_thresholds


@pytest.fixture
def client_and_db(tmp_path):
    db_file = tmp_path / "test_dynamic.db"
    settings = Settings(database_url=f"sqlite:///{db_file}")
    app = create_app(settings)
    engine = build_engine(settings.database_url)
    from app.db import Base
    Base.metadata.create_all(engine)
    factory = session_factory(engine)

    with factory() as db:
        # Create users
        from pwdlib import PasswordHash
        ph = PasswordHash.recommended()
        admin = User(username="admin_user", bcrypt_hash=ph.hash("pass123"), role="admin", active=True)
        pharma = User(username="pharma_user", bcrypt_hash=ph.hash("pass123"), role="pharmacist", active=True)
        dev = Device(device_id="fridge-T1", name="Test Unit 1", enabled=True, mqtt_password="secret1234567890abcdef1234567890abcdef")
        db.add_all([admin, pharma, dev])
        db.flush()

        fridge = Fridge(name="Test Fridge", capacity_slots=5, device_id="fridge-T1")
        db.add(fridge)
        db.flush()

        batch = Batch(
            code="BCH-TEST", vaccine_name="Test Vac", qty=100,
            fridge_id=fridge.id, exposure_weighted_min=0.0,
            status="OK", discard_latched=False, qr_token="test-token-123"
        )
        db.add(batch)

        # Add 30 dummy readings for forecast
        now = datetime.now(UTC)
        for i in range(30):
            r = Reading(
                device_id="fridge-T1",
                seq=i + 1,
                ts=now - timedelta(seconds=(30 - i) * 5),
                temp_c=4.5 + (0.1 if i % 2 == 0 else -0.1),
                door_open=False,
                door_open_s=0,
                compressor_on=True,
                lockout_s=0,
                power_source="MAINS",
                mains_present=True,
                state="SAFE",
            )
            db.add(r)
        db.commit()

    c = TestClient(app)
    return c, factory


def test_dynamic_thresholds_crud(client_and_db):
    client, _ = client_and_db

    # Login as admin
    res = client.post("/api/cc/auth/login", json={"username": "admin_user", "password": "pass123"})
    assert res.status_code == 200
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Get thresholds
    r = client.get("/api/admin/thresholds", headers=headers)
    assert r.status_code == 200
    th = r.json()
    assert "temp_safe_min" in th
    assert "compressor_on_temp" in th
    assert "budget_double_temp" in th

    # Update thresholds dynamically
    r = client.put("/api/admin/thresholds", headers=headers, json={
        "temp_safe_min": 1.5,
        "temp_safe_max": 8.5,
        "compressor_on_temp": 7.5,
        "compressor_off_temp": 2.8,
        "budget_threshold_temp": 8.5,
        "budget_double_temp": 11.5,
    })
    assert r.status_code == 200
    updated = r.json()
    assert updated["temp_safe_min"] == 1.5
    assert updated["budget_double_temp"] == 11.5

    # Verify invalid ranges are rejected with 422
    r_bad = client.put("/api/admin/thresholds", headers=headers, json={
        "temp_safe_min": 9.0,
        "temp_safe_max": 2.0,
    })
    assert r_bad.status_code == 422

    # Reset back to default thresholds
    from app.thresholds import reset_to_defaults
    reset_to_defaults()


def test_device_creation_generates_unique_secret(client_and_db):
    client, _ = client_and_db
    res = client.post("/api/cc/auth/login", json={"username": "admin_user", "password": "pass123"})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

    # Register new device
    dev_res = client.post("/api/devices", headers=headers, json={
        "device_id": "fridge-NEW",
        "name": "New Storage Unit",
    })
    assert dev_res.status_code == 201
    dev_data = dev_res.json()
    assert dev_data["device_id"] == "fridge-NEW"
    # Ensure 64-character hex cryptographic HMAC secret was generated
    assert len(dev_data["mqtt_password"]) == 64
    int(dev_data["mqtt_password"], 16)  # Verify valid hex


def test_telemetry_explorer_and_csv_export(client_and_db):
    client, _ = client_and_db
    res = client.post("/api/cc/auth/login", json={"username": "admin_user", "password": "pass123"})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

    # Query readings list
    r = client.get("/api/readings?limit=10", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert data["total"] >= 30
    assert len(data["items"]) == 10

    # Test filtering by device
    r_dev = client.get("/api/readings?device_id=fridge-T1", headers=headers)
    assert r_dev.status_code == 200
    assert len(r_dev.json()["items"]) > 0

    # Test CSV export
    r_csv = client.get("/api/readings/export?device_id=fridge-T1", headers=headers)
    assert r_csv.status_code == 200
    assert "text/csv" in r_csv.headers["content-type"]
    csv_text = r_csv.text
    assert "id,device_id,seq,timestamp_utc,temp_c" in csv_text
    assert "fridge-T1" in csv_text


def test_dual_scenario_ai_forecast(client_and_db):
    client, _ = client_and_db
    res = client.post("/api/cc/auth/login", json={"username": "admin_user", "password": "pass123"})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

    # Query all fridges forecast
    r = client.get("/api/ml/forecast/all", headers=headers)
    assert r.status_code == 200
    forecasts = r.json()
    assert len(forecasts) >= 1
    f1 = forecasts[0]
    assert f1["available"] is True
    # Dual scenario values present
    assert "predicted_temp_30m" in f1      # Scenario 1 (Normal)
    assert "predicted_temp_30m_off" in f1  # Scenario 2 (Compressor Off)
    assert "scenarios" in f1
    assert "normal" in f1["scenarios"]
    assert "compressor_off" in f1["scenarios"]
    assert len(f1["series"]) >= 10

