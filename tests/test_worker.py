from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.ingestion import InvalidMessage
from app.mqtt_worker import Collector


def message(retain=False):
    return SimpleNamespace(
        topic="devices/sensor-01/telemetry", payload=b"{}", retain=retain, mid=1, qos=1
    )


def test_worker_acknowledges_invalid_but_not_failed_transactions():
    collector = Collector(Settings(_env_file=None), Mock())
    client = Mock()
    with patch("app.mqtt_worker.ingest", side_effect=InvalidMessage("bad")):
        collector.on_message(client, None, message())
    client.ack.assert_called_once_with(1, 1)
    client.reset_mock()
    with patch("app.mqtt_worker.ingest", side_effect=OperationalError("", {}, Exception())):
        collector.on_message(client, None, message())
    client.ack.assert_not_called()
    assert collector.failed.is_set()


def test_worker_ignores_retained_messages():
    collector = Collector(Settings(_env_file=None), Mock())
    client = Mock()
    with patch("app.mqtt_worker.ingest") as ingest:
        collector.on_message(client, None, message(retain=True))
    ingest.assert_not_called()
    client.ack.assert_called_once_with(1, 1)
