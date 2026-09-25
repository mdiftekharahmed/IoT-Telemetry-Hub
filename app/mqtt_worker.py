import logging
import signal
import threading

import paho.mqtt.client as mqtt

from app.config import Settings
from app.db import build_engine, session_factory
from app.ingestion import InvalidMessage, ingest

logger = logging.getLogger(__name__)


class Collector:
    def __init__(self, settings, factory):
        self.settings = settings
        self.factory = factory
        self.failed = threading.Event()
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
        self.client.on_connect = self.on_connect
        self.client.on_subscribe = self.on_subscribe
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error("MQTT connection rejected: %s", reason_code)
            return
        client.subscribe("devices/+/telemetry", qos=1)

    def on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            logger.error("MQTT telemetry subscription rejected")
            self.failed.set()
        else:
            logger.info("MQTT telemetry subscription ready")

    def on_message(self, client, userdata, message):
        if self.failed.is_set():
            return
        try:
            if message.retain:
                logger.warning("Ignoring retained telemetry")
            else:
                result = ingest(self.factory, message.topic, message.payload)
                logger.info("Telemetry outcome=%s stored=%s", result.status, result.stored)
        except InvalidMessage:
            # Do not log raw values or validation errors containing unapproved data.
            logger.warning("Rejected invalid telemetry message")
        except Exception:
            # Never acknowledge a failed transaction. Reconnect with the same durable
            # session so QoS 1 messages can be redelivered, without killing the service.
            logger.error("Telemetry processing failed; reconnecting for redelivery")
            self.failed.set()
            return
        client.ack(message.mid, message.qos)

    def start(self):
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=60)
        self.client.loop_start()

    def stop(self):
        self.client.disconnect()
        self.client.loop_stop()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    if not settings.mqtt_password.get_secret_value():
        raise SystemExit("Set MQTT_PASSWORD before running the collector")
    engine = build_engine(settings.database_url)
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
