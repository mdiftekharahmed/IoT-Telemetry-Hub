#!/usr/bin/env bash
# IoT Telemetry Hub — start / update the Compose stack
# Run from the project root: bash deploy/start.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

# ── Preflight checks ─────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill in secrets."
  exit 1
fi

source .env 2>/dev/null || true   # load vars for validation only

for VAR in POSTGRES_PASSWORD MQTT_PASSWORD; do
  if [ -z "${!VAR:-}" ]; then
    echo "ERROR: $VAR is empty in .env. Set a strong random value."
    exit 1
  fi
done

if [ ! -f "secrets/mosquitto.passwd" ]; then
  echo "ERROR: secrets/mosquitto.passwd not found."
  echo "  Run: bash deploy/gen-mqtt-passwords.sh"
  exit 1
fi

# ── Pull latest images and build ─────────────────────────────────────────────
echo "==> Building / pulling images..."
docker compose pull db mosquitto 2>/dev/null || true
docker compose build --pull

# ── Start ─────────────────────────────────────────────────────────────────────
echo "==> Starting stack..."
docker compose up -d --remove-orphans

echo ""
echo "Stack is up. API is reachable at http://$(hostname -I | awk '{print $1}'):${API_PORT:-8000}"
echo ""
echo "To create the first admin user run:"
echo "  docker compose exec api python -m app.cli create-admin"
