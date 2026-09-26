#!/usr/bin/env bash
# ============================================================
#  IoT Telemetry Hub — Installation Script
#  Tested on: Ubuntu 24.04 LTS
#
#  Run as a sudo-capable user (NOT as root):
#    bash install.sh
#
#  Or directly from GitHub:
#    curl -fsSL https://raw.githubusercontent.com/mdiftekharahmed/IoT-Telemetry-Hub/main/install.sh | bash
# ============================================================
set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[•]${RESET} $*"; }
success() { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
error()   { echo -e "${RED}[✗]${RESET} $*"; exit 1; }
step()    { echo -e "\n${BOLD}${CYAN}══ $* ${RESET}"; }
banner()  {
  echo -e "${BOLD}${CYAN}"
  echo "  ╔══════════════════════════════════════════════╗"
  echo "  ║     IoT Telemetry Hub  —  Installer          ║"
  echo "  ║     Ubuntu 24.04 · Docker · PostgreSQL · MQTT║"
  echo "  ╚══════════════════════════════════════════════╝"
  echo -e "${RESET}"
}

# ── Config ────────────────────────────────────────────────────
REPO_URL="https://github.com/mdiftekharahmed/IoT-Telemetry-Hub.git"
APP_DIR="/opt/iot-telemetry-hub"
CURRENT_USER="${SUDO_USER:-$USER}"

# ── Pre-flight ────────────────────────────────────────────────
banner

if [ "$EUID" -eq 0 ] && [ -z "${SUDO_USER:-}" ]; then
  error "Run as a regular sudo-capable user, not directly as root.\n  e.g.  sudo -u youruser bash install.sh"
fi

if ! sudo -n true 2>/dev/null && ! sudo -v 2>/dev/null; then
  error "This script needs sudo access. Make sure your user has sudo privileges."
fi

# ── Gather config from user ───────────────────────────────────
step "Configuration"

# API port
read -rp "  API port [8000]: " API_PORT < /dev/tty
API_PORT="${API_PORT:-8000}"

# Passwords — generate secure defaults, let user override
DEFAULT_PG_PASS="$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 40)"
DEFAULT_MQTT_PASS="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 32)"

echo ""
warn "Leave passwords blank to use auto-generated secure values (recommended)."
read -rp "  PostgreSQL password [auto]: " PG_PASS < /dev/tty
PG_PASS="${PG_PASS:-$DEFAULT_PG_PASS}"

read -rp "  MQTT collector password [auto]: " MQTT_PASS < /dev/tty
MQTT_PASS="${MQTT_PASS:-$DEFAULT_MQTT_PASS}"

# systemTemp health thresholds (optional)
echo ""
info "systemTemp health thresholds (leave blank to skip — shows 'Unknown' in UI)."
read -rp "  SYSTEM_TEMP_MIN [blank]: " SYSTEM_TEMP_MIN < /dev/tty
read -rp "  SYSTEM_TEMP_MAX [blank]: " SYSTEM_TEMP_MAX < /dev/tty
read -rp "  SYSTEM_TEMP_UNIT [blank]: " SYSTEM_TEMP_UNIT < /dev/tty

echo ""
echo -e "  ${BOLD}Summary${RESET}"
echo "  ├ App directory : $APP_DIR"
echo "  ├ API port      : $API_PORT"
echo "  ├ PG password   : ${PG_PASS:0:6}…  (${#PG_PASS} chars)"
echo "  └ MQTT password : ${MQTT_PASS:0:6}…  (${#MQTT_PASS} chars)"
echo ""
read -rp "  Proceed? [Y/n]: " CONFIRM < /dev/tty
CONFIRM="${CONFIRM:-Y}"
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { info "Aborted."; exit 0; }

# ── 1. System packages ────────────────────────────────────────
step "1 / 7 — System packages"

sudo apt-get update -qq
sudo apt-get install -y -qq \
  ca-certificates curl gnupg lsb-release git mosquitto
sudo systemctl stop mosquitto 2>/dev/null || true
sudo systemctl disable mosquitto 2>/dev/null || true
success "Base packages installed"

# ── 2. Docker Engine ──────────────────────────────────────────
step "2 / 7 — Docker Engine"

if command -v docker &>/dev/null; then
  success "Docker already installed: $(docker --version)"
else
  info "Installing Docker Engine..."
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io docker-compose-plugin
  success "Docker Engine installed"
fi

sudo systemctl enable --now docker containerd 2>/dev/null || true

# Add current user to docker group so compose runs without sudo
if ! groups "$CURRENT_USER" | grep -q docker; then
  sudo usermod -aG docker "$CURRENT_USER"
  info "Added $CURRENT_USER to docker group (takes effect after re-login)"
fi

# ── 3. Clone repo ─────────────────────────────────────────────
step "3 / 7 — Repository"

if [ -d "$APP_DIR/.git" ]; then
  info "Repo already exists — pulling latest..."
  sudo git -C "$APP_DIR" pull
else
  info "Cloning from GitHub..."
  sudo git clone "$REPO_URL" "$APP_DIR"
fi
sudo chown -R "$CURRENT_USER":"$CURRENT_USER" "$APP_DIR"
success "Repo ready at $APP_DIR"

# ── 4. Write .env ─────────────────────────────────────────────
step "4 / 7 — Environment file"

cat > "$APP_DIR/.env" <<ENVEOF
# Generated by install.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# DO NOT commit this file.

# Application
SESSION_TTL_HOURS=12
MAX_DEVICES=10
SECURE_COOKIES=true
DEMO_MODE=false

# API port
API_PORT=${API_PORT}

# Database (set automatically for Docker Compose)
POSTGRES_PASSWORD=${PG_PASS}

# MQTT broker
MQTT_HOST=mosquitto
MQTT_PORT=1883
MQTT_USERNAME=collector
MQTT_PASSWORD=${MQTT_PASS}
MQTT_CLIENT_ID=telemetry-hub-collector
MQTT_TLS=false
MQTT_CA_FILE=

# Device health — systemTemp thresholds
SYSTEM_TEMP_MIN=${SYSTEM_TEMP_MIN:-}
SYSTEM_TEMP_MAX=${SYSTEM_TEMP_MAX:-}
SYSTEM_TEMP_UNIT=${SYSTEM_TEMP_UNIT:-}
ENVEOF

chmod 600 "$APP_DIR/.env"
success ".env written (mode 600)"

# ── 5. Mosquitto password file ────────────────────────────────
step "5 / 7 — MQTT credentials"

mkdir -p "$APP_DIR/secrets"
# mosquitto_passwd is provided by the 'mosquitto' package (installed in step 1)
mosquitto_passwd -c -b "$APP_DIR/secrets/mosquitto.passwd" collector "$MQTT_PASS"
chmod 600 "$APP_DIR/secrets/mosquitto.passwd"
success "secrets/mosquitto.passwd created (collector user)"

info "To add a device credential after registration run:"
echo "  mosquitto_passwd -b $APP_DIR/secrets/mosquitto.passwd <device_id> <password>"
echo "  docker compose -f $APP_DIR/compose.yaml restart mosquitto"

# ── 5.5. Generate self-signed certificate for Caddy ───────────
step "5.5 / 7 — HTTPS Certificate"

LOCAL_IP=$(hostname -I | awk '{print $1}')
mkdir -p "$APP_DIR/docker"
if [ ! -f "$APP_DIR/docker/cert.pem" ]; then
  info "Generating self-signed certificate for $LOCAL_IP..."
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "$APP_DIR/docker/key.pem" \
    -out "$APP_DIR/docker/cert.pem" \
    -subj "/CN=${LOCAL_IP}"
  chmod 644 "$APP_DIR/docker/cert.pem" "$APP_DIR/docker/key.pem"
  success "Generated self-signed certificate"
else
  success "Certificate already exists"
fi

# ── 6. Build and start the stack ─────────────────────────────
step "6 / 7 — Docker Compose stack"

cd "$APP_DIR"

# Use sg to pick up docker group without re-login
info "Pulling base images..."
sg docker -c "docker compose pull db mosquitto" 2>/dev/null || true

info "Building application image..."
sg docker -c "docker compose build --pull"

info "Starting all services (migrate → api + worker + mosquitto + postgres)..."
sg docker -c "docker compose up -d --remove-orphans"

# Wait for API healthcheck
info "Waiting for API to become healthy..."
MAX_WAIT=120
ELAPSED=0
until curl -skf "https://${LOCAL_IP}/health/ready" | grep -q '"ok"'; do
  if [ "$ELAPSED" -ge "$MAX_WAIT" ]; then
    warn "API did not become healthy in ${MAX_WAIT}s. Showing recent logs:"
    sg docker -c "docker compose logs --tail=50"
    error "Deployment failed — check the logs above."
  fi
  sleep 5
  ELAPSED=$((ELAPSED + 5))
  echo -n "."
done
echo ""
success "Stack is healthy (${ELAPSED}s)"

# ── 6.5. Systemd auto-start service ───────────────────────────
step "6.5 / 7 — Systemd auto-start service"

info "Creating systemd service for auto-start after reboot..."
cat <<EOF | sudo tee /etc/systemd/system/iot-telemetry-hub.service > /dev/null
[Unit]
Description=IoT Telemetry Hub
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/sg docker -c "docker compose up -d --remove-orphans"
ExecStop=/usr/bin/sg docker -c "docker compose down"
User=$CURRENT_USER

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable iot-telemetry-hub.service
success "Systemd service (iot-telemetry-hub) created and enabled"

# ── 7. Create first admin user ────────────────────────────────
step "7 / 7 — Create admin user"

ADMIN_USER="admin"
ADMIN_PASS="$(openssl rand -base64 16 | tr -dc 'A-Za-z0-9' | head -c 16)"
info "Auto-generating default admin user ($ADMIN_USER)..."
sg docker -c "docker compose exec -e ADMIN_PASSWORD=$ADMIN_PASS -T api python -m app.cli $ADMIN_USER"
success "Admin user created"

# ── Final summary ─────────────────────────────────────────────
LOCAL_IP=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${BOLD}${GREEN}"
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║            🎉  Deployment complete!                      ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"
echo -e "  ${BOLD}Web UI    :${RESET}  https://${LOCAL_IP}"
echo -e "  ${BOLD}Health    :${RESET}  https://${LOCAL_IP}/health/ready"
echo -e "  ${BOLD}Login     :${RESET}  https://${LOCAL_IP}/login"
echo ""
echo -e "  ${BOLD}App dir   :${RESET}  $APP_DIR"
echo -e "  ${BOLD}Logs      :${RESET}  sudo journalctl -u iot-telemetry-hub -f"
echo -e "  ${BOLD}Service   :${RESET}  sudo systemctl restart iot-telemetry-hub"
echo -e "  ${BOLD}Update    :${RESET}  cd $APP_DIR && git pull && bash deploy/start.sh"
echo ""
echo -e "  ${YELLOW}${BOLD}Save these credentials securely — they are not stored elsewhere:${RESET}"
echo -e "  ${BOLD}Admin Username      :${RESET}  ${ADMIN_USER}"
echo -e "  ${BOLD}Admin Password      :${RESET}  ${ADMIN_PASS}"
echo -e "  ${BOLD}PostgreSQL password :${RESET}  ${PG_PASS}"
echo -e "  ${BOLD}MQTT password       :${RESET}  ${MQTT_PASS}"
echo ""
echo -e "  ${CYAN}To add an IoT device MQTT credential:${RESET}"
echo -e "  mosquitto_passwd -b $APP_DIR/secrets/mosquitto.passwd <device_id> <password>"
echo -e "  docker compose -f $APP_DIR/compose.yaml restart mosquitto"
echo ""
