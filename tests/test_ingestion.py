import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.ingestion import InvalidMessage, ingest
from app.models import IngestedMessage, Telemetry

TOPIC = "devices/sensor-01/telemetry"


def payload(values=None, **extra):
    return json.dumps(
        {
            "message_id": str(uuid4()),
            "values": {"temperature": 23.5} if values is None else values,
            **extra,
        }
    ).encode()


def test_filters_and_deduplicates(seeded):
    message = payload({"temperature": 23.5, "secret": 99})
    assert ingest(seeded, TOPIC, message).stored == 1
    assert ingest(seeded, TOPIC, message).status == "duplicate"
    with seeded() as db:
        rows = db.scalars(select(Telemetry)).all()
        assert [(row.parameter, row.value) for row in rows] == [("temperature", 23.5)]


def test_disabled_and_unknown_devices(seeded, authenticated_client):
    assert ingest(seeded, "devices/unknown/telemetry", payload()).status == "device_rejected"
    authenticated_client.put("/api/devices/sensor-01", json={"name": "Workshop", "enabled": False})
    assert ingest(seeded, TOPIC, payload()).status == "device_rejected"
    with seeded() as db:
        assert db.scalar(select(func.count()).select_from(Telemetry)) == 0


def test_disabled_parameters_and_empty_approved_set(seeded, authenticated_client):
    authenticated_client.put("/api/parameters/temperature", json={"enabled": False})
    message = payload()
    assert ingest(seeded, TOPIC, message).stored == 0
    authenticated_client.put("/api/parameters/temperature", json={"enabled": True})
    assert ingest(seeded, TOPIC, message).status == "duplicate"
    assert ingest(seeded, TOPIC, payload()).stored == 1


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"temperature": "25"},
        {"temperature": True},
        {"temperature": None},
        {"temperature": float("nan")},
        {"temperature": float("inf")},
        {"temperature": []},
        {"temperature": 10**400},
        {"=bad": 1},
    ],
)
def test_invalid_values_do_not_write(seeded, values):
    with pytest.raises(InvalidMessage):
        ingest(seeded, TOPIC, payload(values))
    with seeded() as db:
        assert db.scalar(select(func.count()).select_from(IngestedMessage)) == 0


@pytest.mark.parametrize(
    "message",
    [
        b"not json",
        b"\xff",
        b"[]",
        b"{}",
        b"x" * 16385,
        b'{"message_id":"invalid","values":{"temperature":2}}',
        b'{"message_id":"a","message_id":"b","values":{"temperature":2}}',
    ],
)
def test_malformed_payloads(seeded, message):
    with pytest.raises(InvalidMessage):
        ingest(seeded, TOPIC, message)


def test_topic_and_timestamps(seeded):
    with pytest.raises(InvalidMessage):
        ingest(seeded, "devices/sensor-01/other", payload())
    with pytest.raises(InvalidMessage):
        ingest(seeded, TOPIC, payload(timestamp="2026-09-25T10:00:00"))
    assert ingest(seeded, TOPIC, payload(timestamp="2026-09-25T16:00:00+06:00")).stored == 1
    with seeded() as db:
        assert db.scalar(select(Telemetry.timestamp)).hour == 10


def test_parameter_removal_preserves_history(seeded, authenticated_client):
    ingest(seeded, TOPIC, payload())
    assert authenticated_client.delete("/api/parameters/temperature").status_code == 204
    assert ingest(seeded, TOPIC, payload()).stored == 0
    assert len(authenticated_client.get("/api/telemetry").json()) == 1


def test_failed_commit_rolls_back_receipt_and_readings(seeded):
    original_flush = Session.flush

    def fail_on_telemetry(session, *args, **kwargs):
        if any(isinstance(obj, Telemetry) for obj in session.new):
            raise OperationalError("simulated database outage", {}, Exception())
        return original_flush(session, *args, **kwargs)

    message = payload()
    with patch.object(Session, "flush", fail_on_telemetry):
        with pytest.raises(OperationalError):
            ingest(seeded, TOPIC, message)
    with seeded() as db:
        assert db.scalar(select(func.count()).select_from(IngestedMessage)) == 0
        assert db.scalar(select(func.count()).select_from(Telemetry)) == 0
    assert ingest(seeded, TOPIC, message).stored == 1
