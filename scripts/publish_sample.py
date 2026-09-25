"""Publish one QoS 1 sample; set MQTT_USERNAME to the registered device_id."""

import argparse
from datetime import UTC, datetime
from uuid import uuid4

from paho.mqtt.publish import single

from app.config import Settings
from app.schemas import TelemetryPayload

parser = argparse.ArgumentParser()
parser.add_argument("--temperature", type=float, default=23.5)
args = parser.parse_args()
settings = Settings()
if settings.mqtt_username == "collector" or not settings.mqtt_password.get_secret_value():
    parser.error("Set MQTT_USERNAME to the device_id and MQTT_PASSWORD to its broker password")
payload = TelemetryPayload(
    message_id=uuid4(),
    timestamp=datetime.now(UTC),
    values={"temperature": args.temperature},
)
single(
    f"devices/{settings.mqtt_username}/telemetry",
    payload=payload.model_dump_json(),
    qos=1,
    retain=False,
    hostname=settings.mqtt_host,
    port=settings.mqtt_port,
    auth={
        "username": settings.mqtt_username,
        "password": settings.mqtt_password.get_secret_value(),
    },
    tls={"ca_certs": settings.mqtt_ca_file or None} if settings.mqtt_tls else None,
)
print(f"Published message {payload.message_id}")
