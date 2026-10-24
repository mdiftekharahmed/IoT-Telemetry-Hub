"""
Simple, standalone script to send simulated sensor telemetry to the MQTT broker.
Works with both Plain MQTT (port 1883) and MQTTS TLS (port 8883).

Prerequisites:
    pip install "paho-mqtt<3"

Usage:
    # 1. Edit the CONFIG section below with your credentials, then run:
    python send_dummy_data.py

    # 2. Or override via command line:
    python send_dummy_data.py --host telemetry.durnibar.tech --port 1883 --device test_device_01 --password YOUR_PASS
"""

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[ERROR] 'paho-mqtt' is not installed.")
    print("Please install it by running: pip install \"paho-mqtt<3\"")
    sys.exit(1)

# ==============================================================================
# CONFIGURATION - Set your default settings here
# ==============================================================================
DEFAULT_HOST = "telemetry.durnibar.tech"
DEFAULT_PORT = 1883             # 1883 for Plain MQTT, 8883 for MQTTS (TLS)
DEFAULT_DEVICE_ID = "test_device_01"
DEFAULT_PASSWORD = "YOUR_MQTT_PASSWORD"
DEFAULT_USE_TLS = False         # Set to True if connecting via port 8883 (TLS)
DEFAULT_INTERVAL = 5            # Seconds between messages
# ==============================================================================


def generate_dummy_payload():
    """Generates a valid telemetry payload adhering to the MQTT contract."""
    return {
        "message_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "values": {
            "temperature": round(random.uniform(22.0, 34.0), 1),
            "humidity": round(random.uniform(45.0, 85.0), 1),
            "soil_moisture": round(random.uniform(30.0, 70.0), 1),
            "systemTemp": round(random.uniform(38.0, 48.0), 1),
            "battery": round(random.uniform(3.7, 4.2), 2),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Send dummy telemetry data to MQTT broker.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Broker host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Broker port (default: {DEFAULT_PORT})")
    parser.add_argument("--device", default=DEFAULT_DEVICE_ID, help=f"Device ID / Username (default: {DEFAULT_DEVICE_ID})")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Device MQTT password")
    parser.add_argument("--tls", action="store_true", default=DEFAULT_USE_TLS, help="Enable TLS (port 8883)")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="Interval in seconds between sends")
    parser.add_argument("--count", type=int, default=0, help="Number of messages to send (0 = infinite)")
    args = parser.parse_args()

    topic = f"devices/{args.device}/telemetry"
    client_id = f"test-sim-{uuid4().hex[:8]}"

    print("==================================================")
    print("         IoT Telemetry Hub - MQTT Tester          ")
    print("==================================================")
    print(f" Broker Host : {args.host}")
    print(f" Broker Port : {args.port}")
    print(f" TLS Mode    : {'Enabled (MQTTS)' if args.tls else 'Disabled (Plain MQTT)'}")
    print(f" Device ID   : {args.device}")
    print(f" Target Topic: {topic}")
    print(f" Interval    : {args.interval}s")
    print("==================================================")

    # Validate password
    if args.password == "YOUR_MQTT_PASSWORD":
        print("\n[WARNING] You are using the placeholder password 'YOUR_MQTT_PASSWORD'.")
        entered = input("Enter device MQTT password (or press Enter to try anyway): ").strip()
        if entered:
            args.password = entered

    # Setup MQTT Client (v2 callback API with v3.1.1 protocol)
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(args.device, args.password)

    connected_flag = False

    def on_connect(c, userdata, flags, reason_code, properties):
        nonlocal connected_flag
        if reason_code.is_failure:
            print(f"[ERROR] Connection failed: {reason_code}")
        else:
            connected_flag = True
            print("[SUCCESS] Connected to MQTT broker successfully!\n")

    def on_disconnect(c, userdata, flags, reason_code, properties):
        print(f"[INFO] Disconnected: {reason_code}")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    if args.tls:
        import ssl
        client.tls_set_context(ssl.create_default_context())

    print(f"Connecting to {args.host}:{args.port}...")
    try:
        client.connect(args.host, args.port, keepalive=60)
        client.loop_start()
    except Exception as e:
        print(f"[FAILED] Could not connect to broker: {e}")
        return 1

    # Wait for connection
    timeout = 10
    start = time.time()
    while not connected_flag and (time.time() - start) < timeout:
        time.sleep(0.1)

    if not connected_flag:
        print("[TIMEOUT] Broker did not respond to connection request within 10s.")
        print("Check if port is open in firewall and credentials are correct.")
        client.loop_stop()
        return 1

    sent_count = 0
    try:
        while True:
            sent_count += 1
            payload = generate_dummy_payload()
            json_str = json.dumps(payload, indent=2)

            print(f"[SEND #{sent_count}] Publishing to {topic}:")
            print(json_str)

            # Publish QoS 1 (with ACK)
            result = client.publish(topic, json.dumps(payload), qos=1, retain=False)
            result.wait_for_publish(timeout=5)

            if result.is_published():
                print(f"--> [ACK RECEIVED] Message {payload['message_id']} confirmed by broker.")
            else:
                print("--> [WARNING] Publish timed out without broker confirmation.")

            print("--------------------------------------------------")

            if args.count > 0 and sent_count >= args.count:
                print(f"[DONE] Sent {sent_count} messages as requested.")
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[STOPPED] User stopped transmission.")
    finally:
        client.disconnect()
        client.loop_stop()
        print("MQTT connection closed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
