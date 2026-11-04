"""MQTT downlink command publisher.

Sends signed downlink commands to nodes on `cc/{device_id}/cmd`:
- LATCH_RED: locks red LED in NVS on Discard
- RESET_RED: clears red LED latch on admin reset
- SET_SIM: enable/disable thermal model simulation
- SET_SCALE: update demo time-scale factor
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

import paho.mqtt.publish as publish

from app.config import Settings
from app.security import canonical_json, hmac_sign

logger = logging.getLogger(__name__)


def publish_command(
    settings: Settings,
    device_id: str,
    cmd_type: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Sign and publish an authenticated command to an edge node."""
    payload = payload or {}
    ts = int(time.time())
    nonce = secrets.token_hex(8)
    d_canon = canonical_json(payload)
    secret = settings.device_secret(device_id) or ""
    sig = hmac_sign(secret, [cmd_type, str(ts), nonce, d_canon]) if secret else "unsigned"

    envelope = {
        "type": cmd_type,
        "cmd": cmd_type,
        "ts": ts,
        "nonce": nonce,
        "d": payload,
        "sig": sig,
    }
    raw = json.dumps(envelope).encode("utf-8")
    topic = f"cc/{device_id}/cmd"

    auth = None
    if settings.mqtt_username and settings.mqtt_password.get_secret_value():
        auth = {
            "username": settings.mqtt_username,
            "password": settings.mqtt_password.get_secret_value(),
        }

    try:
        publish.single(
            topic,
            payload=raw,
            qos=1,
            retain=False,
            hostname=settings.mqtt_host,
            port=settings.mqtt_port,
            auth=auth,
        )
        logger.info("Published downlink command %s to %s", cmd_type, device_id)
        return True
    except Exception as exc:
        logger.warning("Failed to publish command %s to %s: %s", cmd_type, device_id, exc)
        return False
