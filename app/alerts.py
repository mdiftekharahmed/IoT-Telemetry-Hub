"""Telegram + internal alert system for ColdChain.

Alert types: door_open_60s, door_closed, breach, warning, at_risk, discard,
power_fail, mains_restored, battery_low, device_offline, device_online,
predicted_breach, health_low.

De-duplication: one alert per (type, device_id) per cooldown window.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, utcnow

logger = logging.getLogger(__name__)

# Cooldown per (type, device_id) – do not spam the same alert
COOLDOWNS: dict[str, timedelta] = {
    "door_open_60s":   timedelta(minutes=10),
    "door_closed":     timedelta(minutes=2),
    "breach":          timedelta(minutes=5),
    "warning":         timedelta(minutes=10),
    "at_risk":         timedelta(hours=1),
    "discard":         timedelta(hours=24),
    "power_fail":      timedelta(minutes=5),
    "mains_restored":  timedelta(minutes=5),
    "battery_low":     timedelta(hours=2),
    "device_offline":  timedelta(minutes=10),
    "device_online":   timedelta(minutes=5),
    "predicted_breach": timedelta(minutes=15),
    "health_low":      timedelta(hours=2),
}
DEFAULT_COOLDOWN = timedelta(minutes=10)


def _is_in_cooldown(db: Session, alert_type: str, device_id: Optional[str]) -> bool:
    cooldown = COOLDOWNS.get(alert_type, DEFAULT_COOLDOWN)
    cutoff = utcnow() - cooldown
    recent = db.scalar(
        select(Alert).where(
            Alert.type == alert_type,
            Alert.device_id == device_id,
            Alert.created_at >= cutoff,
        )
    )
    return recent is not None


def _send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    for attempt in range(3):
        try:
            resp = httpx.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)
            if resp.status_code == 200:
                return True
            logger.warning("Telegram attempt %d failed: %s", attempt + 1, resp.text)
        except Exception as exc:
            logger.warning("Telegram attempt %d error: %s", attempt + 1, exc)
    return False


def fire(
    db: Session,
    alert_type: str,
    message: str,
    device_id: Optional[str] = None,
    batch_id: Optional[int] = None,
    bot_token: str = "",
    chat_id: str = "",
) -> Optional[Alert]:
    """Create an alert record and send Telegram if not in cooldown."""
    if _is_in_cooldown(db, alert_type, device_id):
        logger.debug("Alert %s/%s in cooldown, skipped", alert_type, device_id)
        return None

    sent = _send_telegram(message, bot_token, chat_id)
    alert = Alert(
        type=alert_type,
        device_id=device_id,
        batch_id=batch_id,
        message=message,
        sent_via="telegram" if sent else None,
    )
    db.add(alert)
    db.flush()
    logger.info("Alert fired: %s / %s (telegram=%s)", alert_type, device_id, sent)
    return alert
