import csv
import io
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.ingestion import ingest
from app.models import AdminSession, utcnow
from app.security import token_digest
from tests.test_ingestion import TOPIC, payload


@pytest.mark.parametrize(
    "path",
    [
        "/api/devices",
        "/api/parameters",
        "/api/telemetry",
        "/api/telemetry/export",
        "/api/auth/me",
    ],
)
def test_auth_required(client, path):
    assert client.get(path).status_code == 401


def test_login_expiration_and_logout(application, client):
    for username in ("admin", "missing"):
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "username": username,
                    "password": "incorrect",
                },
            ).status_code
            == 401
        )
    login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "test-password-123"}
    )
    assert login.headers["cache-control"] == "no-store"
    token = login.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.get("/api/auth/me").json()["username"] == "admin"
    with application.state.sessions.begin() as db:
        stored = db.scalar(select(AdminSession))
        assert stored.token_hash == token_digest(token)
        assert stored.token_hash != token
        stored.expires_at = utcnow() - timedelta(seconds=1)
    assert client.get("/api/auth/me").status_code == 401
    token = client.post(
        "/api/auth/login",
        json={
            "username": "admin",
            "password": "test-password-123",
        },
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_devices_and_capacity(authenticated_client):
    client = authenticated_client
    for number in range(10):
        response = client.post("/api/devices", json={"device_id": f"s{number}", "name": "Sensor"})
        assert response.status_code == 201
    assert (
        client.post("/api/devices", json={"device_id": "extra", "name": "Extra"}).status_code == 409
    )
    assert (
        client.post("/api/devices", json={"device_id": "s0", "name": "Duplicate"}).status_code
        == 409
    )
    assert len(client.get("/api/devices").json()) == 10
    assert (
        client.put("/api/devices/s0", json={"name": "Changed", "enabled": False}).json()["enabled"]
        is False
    )
    assert client.put("/api/devices/none", json={"name": "X", "enabled": True}).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"device_id": "bad/topic", "name": "Invalid"},
        {"device_id": "ok", "name": "  "},
        {"device_id": "=formula", "name": "Invalid"},
    ],
)
def test_invalid_devices(authenticated_client, body):
    assert authenticated_client.post("/api/devices", json=body).status_code == 422


def test_parameter_conflict(seeded, authenticated_client):
    assert (
        authenticated_client.post("/api/parameters", json={"name": "temperature"}).status_code
        == 409
    )
    assert authenticated_client.get("/api/parameters").json() == [
        {"name": "temperature", "enabled": True}
    ]


def test_export_dates_pagination_and_empty_range(seeded, authenticated_client):
    client = authenticated_client
    for hour in (10, 11, 12):
        ingest(seeded, TOPIC, payload(timestamp=f"2026-09-25T{hour}:00:00Z"))
    first = client.get("/api/telemetry", params={"limit": 2}).json()
    second = client.get("/api/telemetry", params={"limit": 2, "before_id": first[-1]["id"]}).json()
    assert len(first) == 2 and len(second) == 1
    assert first[0]["timestamp"].endswith("Z")
    response = client.get(
        "/api/telemetry/export",
        params={
            "start": "2026-09-25T16:00:00+06:00",
            "end": "2026-09-25T18:00:00+06:00",
        },
    )
    assert response.status_code == 200
    records = list(csv.DictReader(io.StringIO(response.text)))
    assert len(records) == 2
    assert records[0]["timestamp"] == "2026-09-25T10:00:00+00:00"
    assert records[0]["device_id"] == "sensor-01"
    assert records[0]["value"] == "23.5"
    empty = client.get(
        "/api/telemetry/export",
        params={
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-02T00:00:00Z",
        },
    )
    assert empty.text == "timestamp,device_id,parameter,value\r\n"


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-09-25T10:00:00", "2026-09-25T11:00:00Z"),
        ("2026-09-25T10:00:00Z", "2026-09-25T10:00:00Z"),
        ("2026-09-25T11:00:00Z", "2026-09-25T10:00:00Z"),
    ],
)
def test_invalid_export_dates(authenticated_client, start, end):
    assert (
        authenticated_client.get(
            "/api/telemetry/export",
            params={
                "start": start,
                "end": end,
            },
        ).status_code
        == 422
    )


def test_health(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_clear_device_telemetry_removes_all_data(seeded, authenticated_client):
    """Clearing device telemetry deletes readings, records, and receipts."""
    from sqlalchemy import func, select
    from app.ingestion import ingest
    from app.models import IngestedMessage, Telemetry, TelemetryRecord

    # Ingest two transmissions so there is data to delete.
    ingest(seeded, TOPIC, payload())
    ingest(seeded, TOPIC, payload())

    with seeded() as db:
        assert db.scalar(select(func.count()).select_from(Telemetry)) == 2
        assert db.scalar(select(func.count()).select_from(TelemetryRecord)) == 2
        assert db.scalar(select(func.count()).select_from(IngestedMessage)) == 2

    response = authenticated_client.delete("/api/devices/sensor-01/telemetry")
    assert response.status_code == 204

    with seeded() as db:
        assert db.scalar(select(func.count()).select_from(Telemetry)) == 0
        assert db.scalar(select(func.count()).select_from(TelemetryRecord)) == 0
        assert db.scalar(select(func.count()).select_from(IngestedMessage)) == 0


def test_clear_device_telemetry_keeps_device_registration(seeded, authenticated_client):
    """The device row itself must survive the data wipe."""
    ingest(seeded, TOPIC, payload())
    authenticated_client.delete("/api/devices/sensor-01/telemetry")

    devices = authenticated_client.get("/api/devices").json()
    assert len(devices) == 1
    assert devices[0]["device_id"] == "sensor-01"
    assert devices[0]["name"] == "Workshop"


def test_clear_device_telemetry_unknown_device(authenticated_client):
    """Clearing data for a non-existent device returns 404."""
    assert (
        authenticated_client.delete("/api/devices/no-such-device/telemetry").status_code == 404
    )


def test_clear_device_telemetry_allows_reingest_same_message_id(seeded, authenticated_client):
    """After clearing, the same message UUID is accepted again (receipts gone)."""
    from app.ingestion import ingest

    message = payload()
    assert ingest(seeded, TOPIC, message).status == "accepted"
    assert ingest(seeded, TOPIC, message).status == "duplicate"

    authenticated_client.delete("/api/devices/sensor-01/telemetry")

    # Deduplication receipt cleared — same UUID should now be re-accepted.
    assert ingest(seeded, TOPIC, message).status == "accepted"


def test_clear_device_telemetry_only_affects_target_device(seeded, authenticated_client):
    """Clearing one device must not touch another device's data."""
    from sqlalchemy import func, select
    from app.ingestion import ingest
    from app.models import Telemetry

    # Register a second device and parameter.
    authenticated_client.post("/api/devices", json={"device_id": "sensor-02", "name": "Field"})
    ingest(seeded, TOPIC, payload())
    ingest(seeded, "devices/sensor-02/telemetry", payload())

    authenticated_client.delete("/api/devices/sensor-01/telemetry")

    with seeded() as db:
        count = db.scalar(
            select(func.count()).select_from(Telemetry).where(Telemetry.device_id == "sensor-02")
        )
        assert count == 1
