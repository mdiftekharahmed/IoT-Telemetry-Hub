#!/usr/bin/env bash
# Generate the Mosquitto password file and per-device credentials.
# Run ONCE from the project root: bash deploy/gen-mqtt-passwords.sh
#
# Prerequisites: mosquitto-clients installed on the VM
#   sudo apt-get install -y mosquitto-clients
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

source .env 2>/dev/null || true

if [ -z "${MQTT_PASSWORD:-}" ]; then
  echo "ERROR: MQTT_PASSWORD is empty in .env. Set the collector password first."
  exit 1
fi

mkdir -p secrets

PASSWD_FILE="secrets/mosquitto.passwd"

echo "==> Creating collector credentials (user: ${MQTT_USERNAME:-collector})..."
# -c creates/overwrites the file; -b takes the password as an argument (non-interactive)
mosquitto_passwd -c -b "$PASSWD_FILE" "${MQTT_USERNAME:-collector}" "$MQTT_PASSWORD"

echo ""
echo "Per-device credentials:"
echo "  Each device's MQTT username MUST equal its registered device_id."
echo "  Run for each device you register:"
echo ""
echo "    mosquitto_passwd -b $PASSWD_FILE <device_id> <device_password>"
echo ""
echo "  Example:"
echo "    mosquitto_passwd -b $PASSWD_FILE sensor-01 changeme123"
echo ""
echo "Password file written to $PASSWD_FILE"
echo "Restart mosquitto after adding devices: docker compose restart mosquitto"
