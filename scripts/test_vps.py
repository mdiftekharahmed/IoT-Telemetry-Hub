"""Standalone dummy MQTT publisher. Requires paho-mqtt>=2,<3; no app config needed."""

import argparse
import getpass
import json
import random
import re
import ssl
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

import paho.mqtt.client as mqtt

# Enter the MQTT password for the device supplied with --device.
# Leave blank to use the hidden prompt. Do not commit a real password to Git.
DEVICE_MQTT_PASSWORD = "Gh8BbWRCQxLzyM4S"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="MQTT hostname/IP, without https://")
    parser.add_argument("--device", required=True, help="Registered device ID / MQTT username")
    parser.add_argument("--port", type=int, help="Default: 1883, or 8883 with --tls")
    parser.add_argument("--tls", action="store_true", help="Enable verified MQTT TLS")
    parser.add_argument("--ca", help="Custom CA certificate PEM file (requires --tls)")
    parser.add_argument("--count", type=int, default=6, help="Messages to send (default: 6)")
    parser.add_argument("--interval", type=float, default=10, help="Seconds between sends")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without connecting")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.device):
        parser.error("Invalid device ID")
    if args.device == "collector":
        parser.error("Use a device account, not the collector account")
    if args.count < 1 or not 0 < args.interval < float("inf"):
        parser.error("Count and interval must be positive and finite")
    port = args.port if args.port is not None else (8883 if args.tls else 1883)
    if not 1 <= port <= 65535 or (args.ca and not args.tls):
        parser.error("Port must be 1-65535; --ca requires --tls")

    topic = f"devices/{args.device}/telemetry"
    client = None
    loop_started = False
    try:
        if not args.dry_run:
            password = DEVICE_MQTT_PASSWORD or getpass.getpass("Device MQTT password (hidden): ")
            if not password:
                parser.error("Device MQTT password is required")
            ready = threading.Event()
            rejected = []

            def on_connect(client, userdata, flags, reason_code, properties):
                if reason_code.is_failure:
                    rejected.append(str(reason_code))
                    print(f"[CONNECT FAILED] {reason_code}")
                else:
                    print("[CONNECTED] Broker accepted credentials")
                ready.set()

            def on_disconnect(client, userdata, flags, reason_code, properties):
                if reason_code.is_failure:
                    print(f"[DISCONNECTED] {reason_code}")

            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"smoke-{uuid4().hex[:16]}",
                protocol=mqtt.MQTTv311,
            )
            client.username_pw_set(args.device, password)
            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            client.connect_timeout = 10
            if args.tls:
                client.tls_set_context(ssl.create_default_context(cafile=args.ca))
            print(f"[CONNECTING] {args.host}:{port} TLS={args.tls} device={args.device}")
            client.connect(args.host, port, keepalive=30)
            client.loop_start()
            loop_started = True
            if not ready.wait(15):
                raise RuntimeError("No MQTT connection response within 15 seconds")
            if rejected:
                raise RuntimeError(f"Broker rejected connection: {rejected[0]}")

        for index in range(args.count):
            payload = json.dumps({
                "message_id": str(uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "values": {
                    "temperature": round(random.uniform(24, 32), 1),
                    "humidity": round(random.uniform(50, 85), 1),
                    "systemTemp": round(random.uniform(35, 45), 1),
                    "NPK": round(random.uniform(10, 90), 1),
                },
            })
            print(f"[SEND {index + 1}/{args.count}] {topic}\n{payload}")
            if client is not None:
                result = client.publish(topic, payload, qos=1, retain=False)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise RuntimeError(f"Publish failed: {mqtt.error_string(result.rc)}")
                result.wait_for_publish(timeout=15)
                if not result.is_published():
                    raise RuntimeError("No broker PUBACK in 15 seconds; delivery is uncertain")
                print(f"[ACK] Broker acknowledged packet {result.mid}")
            if index + 1 < args.count and not args.dry_run:
                time.sleep(args.interval)
        print("[DONE] Dry run complete." if args.dry_run else
              "[DONE] Refresh Stored Data to confirm database storage. "
              "Broker acknowledgments do not confirm worker/database acceptance.")
        return 0
    except KeyboardInterrupt:
        print("\n[STOPPED] Interrupted by user")
        return 130
    except (OSError, RuntimeError, ValueError) as error:
        print(f"[ERROR] {error}")
        print("Check broker host/port, firewall, TLS settings, device credentials and server logs.")
        return 1
    finally:
        if client is not None:
            client.disconnect()
            if loop_started:
                client.loop_stop()


if __name__ == "__main__":
    raise SystemExit(main())
