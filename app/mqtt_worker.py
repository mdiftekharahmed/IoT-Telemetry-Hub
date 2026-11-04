"""MQTT worker: subscribes to both legacy and ColdChain topics, routes to ingest handlers."""

from __future__ import annotations

import json
import logging
import signal
import threading
from datetime import UTC, datetime

import paho.mqtt.client as mqtt

from app.config import Settings
from app.db import build_engine, session_factory
from app.ingestion import InvalidMessage, ingest  # legacy handler

logger = logging.getLogger(__name__)


class Collector:
    def __init__(self, settings: Settings, factory):
        self.settings = settings
        self.factory  = factory
        self.failed   = threading.Event()

        # Import here to avoid circular imports at module level
        from app.cc_ingestion import ingest_sync, ingest_telemetry, SecurityRejection
        self._ingest_cc       = ingest_telemetry
        self._ingest_sync     = ingest_sync
        self._SecurityRejection = SecurityRejection

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            clean_session=False,
            manual_ack=True,
        )
        self.client.username_pw_set(
            settings.mqtt_username, settings.mqtt_password.get_secret_value()
        )
        if settings.mqtt_tls:
            self.client.tls_set(ca_certs=settings.mqtt_ca_file or None)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect   = self.on_connect
        self.client.on_subscribe = self.on_subscribe
        self.client.on_message   = self.on_message
        self.client.will_set("cc/collector/status",
                             payload='{"status":"offline"}', qos=1, retain=True)

    # ── Connection ──────────────────────────────────────────────────────────────

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error("MQTT connection rejected: %s", reason_code)
            return
        # Legacy topic
        client.subscribe("devices/+/telemetry", qos=1)
        # ColdChain topics
        for pattern in ("cc/+/telemetry", "cc/+/sync", "cc/+/event",
                        "cc/+/ack", "cc/+/status"):
            client.subscribe(pattern, qos=1)
        logger.info("MQTT subscriptions registered")

    def on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            logger.error("MQTT subscription rejected")
            self.failed.set()
        else:
            logger.info("MQTT subscriptions ready")

    # ── Message routing ─────────────────────────────────────────────────────────

    def on_message(self, client, userdata, message):
        if self.failed.is_set():
            return
        try:
            if message.retain:
                logger.debug("Ignoring retained message on %s", message.topic)
                client.ack(message.mid, message.qos)
                return

            topic = message.topic
            if topic.startswith("devices/"):
                self._handle_legacy(message)
            elif topic.startswith("cc/"):
                self._handle_coldchain(topic, message.payload)
            else:
                logger.debug("Unknown topic: %s", topic)

        except Exception:
            logger.error("Message processing failed; reconnecting", exc_info=True)
            self.failed.set()
            return

        client.ack(message.mid, message.qos)

    def _handle_legacy(self, message):
        try:
            result = ingest(self.factory, message.topic, message.payload)
            logger.info("legacy telemetry outcome=%s stored=%s", result.status, result.stored)
        except InvalidMessage:
            logger.warning("Rejected invalid legacy telemetry")

    def _handle_coldchain(self, topic: str, payload: bytes):
        secrets = self.settings.device_secrets
        window  = self.settings.hmac_ts_window_s

        if "/telemetry" in topic:
            result = self._ingest_cc(self.factory, topic, payload, secrets, window)
            logger.info("cc/telemetry %s accepted=%d dups=%d",
                        result.status, result.accepted, result.duplicates)
            if result.status == "accepted" and result.accepted > 0:
                self._fire_telemetry_alerts(topic, payload)

        elif "/sync" in topic:
            result = self._ingest_sync(self.factory, topic, payload, secrets, window)
            logger.info("cc/sync %s accepted=%d dups=%d",
                        result.status, result.accepted, result.duplicates)

        elif "/event" in topic:
            self._handle_event(topic, payload)

        elif "/status" in topic:
            self._handle_status(topic, payload)

        elif "/ack" in topic:
            logger.debug("cc/ack %s: %s", topic, payload[:64])

    def _handle_event(self, topic: str, payload: bytes):
        try:
            evt = json.loads(payload)
            device_id = topic.split("/")[1] if len(topic.split("/")) >= 3 else "unknown"
            evt_type = evt.get("type", "")
            logger.info("cc/event %s type=%s", topic, evt_type)

            bot_token = getattr(self.settings, "telegram_bot_token", "")
            chat_id   = getattr(self.settings, "telegram_chat_id", "")

            with self.factory() as db:
                from app import alerts as alert_mod
                if evt_type == "mains_restored":
                    alert_mod.fire(db, "mains_restored",
                                   f"✅ Mains power restored on {device_id}",
                                   device_id=device_id, bot_token=bot_token, chat_id=chat_id)
                elif evt_type == "device_online":
                    alert_mod.fire(db, "device_online",
                                   f"🟢 Device {device_id} came online",
                                   device_id=device_id, bot_token=bot_token, chat_id=chat_id)
                db.commit()
        except Exception:
            logger.warning("Unparseable cc/event on %s", topic)

    def _handle_status(self, topic: str, payload: bytes):
        """LWT or heartbeat: update device last_seen and fire offline alert on LWT."""
        try:
            parts = topic.split("/")
            device_id = parts[1] if len(parts) >= 3 else None
            status = json.loads(payload)
            online = status.get("status") == "online"
            if device_id:
                with self.factory() as db:
                    from app.models import Device, utcnow
                    dev = db.get(Device, device_id)
                    if dev:
                        if online:
                            dev.last_seen = utcnow()
                        db.commit()
                if not online:
                    self._handle_lwt_offline(device_id)
        except Exception:
            logger.warning("cc/status handling error", exc_info=True)

    def _fire_telemetry_alerts(self, topic: str, payload: bytes) -> None:
        """Fire alert hooks after a successfully accepted telemetry reading."""
        try:
            import json as _json
            from app import alerts as alert_mod
            msg = _json.loads(payload)
            d = msg.get("d", {})
            device_id = topic.split("/")[1]
            temp_c = float(d.get("temp_c", 5.0))
            door_open = bool(d.get("door_open", False))
            door_open_s = int(d.get("door_open_s", 0))
            mains_present = bool(d.get("mains_present", True))

            bot_token = getattr(self.settings, "telegram_bot_token", "")
            chat_id   = getattr(self.settings, "telegram_chat_id", "")

            from app.thresholds import get_thresholds
            th = get_thresholds()
            safe_min = th.get("temp_safe_min", 2.0)
            safe_max = th.get("temp_safe_max", 8.0)
            door_alarm_s = th.get("door_alarm_s", 60)

            with self.factory() as db:
                # Temperature breach
                if temp_c < safe_min or temp_c > safe_max:
                    alert_mod.fire(db, "breach",
                                   f"🌡️ Temperature breach on {device_id}: {temp_c:.1f}°C (Safe range: {safe_min}–{safe_max}°C)",
                                   device_id=device_id, bot_token=bot_token, chat_id=chat_id)
                # Door open alarm
                if door_open and door_open_s >= door_alarm_s:
                    alert_mod.fire(db, "door_open_60s",
                                   f"🚪 Door open >{door_alarm_s}s on {device_id} ({door_open_s}s)",
                                   device_id=device_id, bot_token=bot_token, chat_id=chat_id)
                # Door closed after open alarm
                if not door_open and door_open_s == 0:
                    alert_mod.fire(db, "door_closed",
                                   f"✅ Door closed on {device_id}",
                                   device_id=device_id, bot_token=bot_token, chat_id=chat_id)
                # Power fail
                if not mains_present:
                    alert_mod.fire(db, "power_fail",
                                   f"⚡ Mains power lost on {device_id}",
                                   device_id=device_id, bot_token=bot_token, chat_id=chat_id)
                # Check batch budget status for at_risk / discard alerts
                from app.models import Device, Batch
                from sqlalchemy import select
                dev = db.get(Device, device_id)
                if dev and dev.fridge_id:
                    batches = db.scalars(
                        select(Batch).where(Batch.fridge_id == dev.fridge_id)
                    ).all()
                    for batch in batches:
                        if batch.status == "AT_RISK":
                            alert_mod.fire(db, "at_risk",
                                           f"⚠️ Batch {batch.code} at risk ({batch.remaining_pct:.0f}% budget remaining)",
                                           device_id=device_id, batch_id=batch.id,
                                           bot_token=bot_token, chat_id=chat_id)
                        elif batch.status == "DISCARD":
                            alert_mod.fire(db, "discard",
                                           f"🚫 Batch {batch.code} DISCARD – heat budget exhausted",
                                           device_id=device_id, batch_id=batch.id,
                                           bot_token=bot_token, chat_id=chat_id)
                db.commit()
        except Exception as _exc:
            logger.warning("Alert hook error: %s", _exc)

    def _handle_lwt_offline(self, device_id: str) -> None:
        """Fire device_offline alert on LWT or heartbeat expiry."""
        bot_token = getattr(self.settings, "telegram_bot_token", "")
        chat_id   = getattr(self.settings, "telegram_chat_id", "")
        try:
            with self.factory() as db:
                from app import alerts as alert_mod
                alert_mod.fire(db, "device_offline",
                               f"🔴 Device {device_id} went offline",
                               device_id=device_id, bot_token=bot_token, chat_id=chat_id)
                db.commit()
        except Exception as _exc:
            logger.warning("Offline alert failed for %s: %s", device_id, _exc)

    # ── Publish (downlink commands) ─────────────────────────────────────────────

    def publish_command(self, device_id: str, cmd_type: str, payload: dict) -> None:
        """Sign and publish a command to a device."""
        import time, secrets as sec
        from app.security import hmac_sign, canonical_json
        ts    = int(time.time())
        nonce = sec.token_hex(8)
        d_str = canonical_json(payload)
        secret = self.settings.device_secret(device_id) or ""
        sig = hmac_sign(secret, [cmd_type, str(ts), nonce, d_str]) if secret else "unsigned"
        msg = json.dumps({"type": cmd_type, "ts": ts, "nonce": nonce, "d": payload, "sig": sig})
        self.client.publish(f"cc/{device_id}/cmd", msg, qos=1)
        logger.info("Published cmd %s to %s", cmd_type, device_id)

    # ── Lifecycle ───────────────────────────────────────────────────────────────

    def start(self):
        self.client.connect_async(
            self.settings.mqtt_host, self.settings.mqtt_port, keepalive=60
        )
        self.client.loop_start()

    def stop(self):
        self.client.disconnect()
        self.client.loop_stop()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    if not settings.mqtt_password.get_secret_value():
        raise SystemExit("Set MQTT_PASSWORD before running the collector")
    engine  = build_engine(settings.database_url)
    factory = session_factory(engine)
    shutdown = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: shutdown.set())
    try:
        while not shutdown.is_set():
            collector = Collector(settings, factory)
            collector.start()
            try:
                while not shutdown.wait(0.5) and not collector.failed.is_set():
                    pass
            finally:
                collector.stop()
            if not shutdown.is_set():
                shutdown.wait(5)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
