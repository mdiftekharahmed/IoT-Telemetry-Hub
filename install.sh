#!/usr/bin/env bash
# ============================================================
#  ColdChain — Vaccine & Medicine Storage Monitor
#  One-shot Installation Script (Ubuntu 24.04 LTS)
#
#  Interactive (recommended), run as a sudo-capable user (NOT root):
#    bash install.sh
#
#  Piped from GitHub (prompts are read from the terminal):
#    curl -fsSL https://raw.githubusercontent.com/mdiftekharahmed/IoT-Telemetry-Hub/main/install.sh | bash
#
#  Non-interactive / automation — every prompt has an env override:
#    ASSUME_YES=1 DOMAIN=demo.example.org bash install.sh
#    Optional overrides: INSTALL_DIR, REPO_BRANCH, PG_PASS, MQTT_PASS,
#      JWT_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
#      ADMIN_PASSWORDS_CSV="pw1,pw2,pw3,pw4,pw5"
#
#  Re-running is safe: repo is updated, MQTT entries preserved, seed is
#  idempotent. NOTE: .env secrets are regenerated on every run.
# ============================================================
set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[•]${RESET} $*"; }
success() { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
error()   { echo -e "${RED}[✗]${RESET} $*" >&2; exit 1; }
step()    { echo -e "\n${BOLD}${CYAN}══ $* ${RESET}"; }
banner()  {
  echo -e "${BOLD}${CYAN}"
  echo "  ╔══════════════════════════════════════════════════════╗"
  echo "  ║   ColdChain — Vaccine & Medicine Storage Monitor     ║"
  echo "  ║   Ubuntu 24.04 · Docker · PostgreSQL · MQTT · Caddy  ║"
  echo "  ╚══════════════════════════════════════════════════════╝"
  echo -e "${RESET}"
}

# ── Config ────────────────────────────────────────────────────
REPO_URL="https://github.com/mdiftekharahmed/IoT-Telemetry-Hub.git"
REPO_BRANCH="${REPO_BRANCH:-BUBT_IOT_HACKATHON}"   # default to hackathon branch
APP_DIR="${INSTALL_DIR:-/opt/coldchain}"
CURRENT_USER="${SUDO_USER:-$USER}"

gen_pw() { openssl rand -base64 32 2>/dev/null | tr -dc 'A-Za-z0-9' | head -c "${1:-40}"; }

# Ask a question, honouring an env override (VAR=val bash install.sh).
# Falls back to an empty answer when stdin has no TTY so that
# automation keeps running and defaults kick in.
if [ -w /dev/tty ] && [ "${ASSUME_YES:-}" != "1" ]; then TTY_OK=true; else TTY_OK=false; fi

ask() {
  local _var="$1" _prompt="$2" _val=""
  if [ -n "${!_var:-}" ]; then
    _val="${!_var}"
  elif [ "$TTY_OK" = true ]; then
    read -rp "  ${_prompt}: " _val < /dev/tty || _val=""
  fi
  printf -v "$_var" '%s' "$_val"
}

# ── Pre-flight checks ─────────────────────────────────────────
banner

if [ "$EUID" -eq 0 ] && [ -z "${SUDO_USER:-}" ]; then
  error "Run as a regular sudo-capable user, not directly as root.\n  e.g.  sudo -u youruser bash install.sh"
fi

# Check sudo — allow both passwordless and password-based sudo.
# When piped via curl|bash, we need a TTY for password prompt; redirect from /dev/tty.
if ! sudo -n true 2>/dev/null; then
  info "sudo requires a password. You may be prompted now to cache credentials."
  if [ "$TTY_OK" = true ]; then
    sudo -v < /dev/tty || error "sudo failed. Make sure your user has sudo privileges."
  else
    error "sudo requires a password but there is no terminal. Run interactively."
  fi
fi

if ! command -v openssl &>/dev/null; then
  warn "openssl not found yet — it will be installed in step 1."
fi

# ── Gather config from user ───────────────────────────────────
step "Configuration"

DEFAULT_DOMAIN="$(hostname -I 2>/dev/null | awk '{print $1}')"
DEFAULT_DOMAIN="${DEFAULT_DOMAIN:-localhost}"

ask DOMAIN "Server domain or IP"
DOMAIN="${DOMAIN:-$DEFAULT_DOMAIN}"

# Generate secure secrets
DEFAULT_PG_PASS="$(gen_pw 40)"
DEFAULT_MQTT_PASS="$(gen_pw 32)"
DEFAULT_JWT_SECRET="$(openssl rand -hex 32)"

echo ""
warn "Leave passwords blank to use auto-generated secure values (recommended)."
ask PG_PASS "PostgreSQL password   [auto]"
PG_PASS="${PG_PASS:-$DEFAULT_PG_PASS}"

ask MQTT_PASS "MQTT collector password [auto]"
MQTT_PASS="${MQTT_PASS:-$DEFAULT_MQTT_PASS}"

ask JWT_SECRET "JWT secret            [auto]"
JWT_SECRET="${JWT_SECRET:-$DEFAULT_JWT_SECRET}"

# Telegram (optional alerts)
echo ""
info "Telegram alert integration (optional — press Enter to skip)."
ask TELEGRAM_BOT_TOKEN "Telegram Bot Token [blank to skip]"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
ask TELEGRAM_CHAT_ID "Telegram Chat ID   [blank to skip]"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

# Admin users (mehedi1–5)
echo ""
info "Five admin accounts will be created: mehedi1 through mehedi5."
warn "Leave blank to generate random secure passwords for each."
ADMIN_PASSWORDS=()
for i in 1 2 3 4 5; do
  if [ -n "${ADMIN_PASSWORDS_CSV:-}" ]; then
    P="$(echo -n "$ADMIN_PASSWORDS_CSV" | awk -F',' -v n="$i" '{print $n}')"
  else
    ask P "Password for mehedi${i} [auto]"
  fi
  ADMIN_PASSWORDS+=("${P:-$(gen_pw 20)}")
done

echo ""
echo -e "  ${BOLD}Summary${RESET}"
echo "  ├ App directory     : $APP_DIR"
echo "  ├ Repo branch       : ${REPO_BRANCH:-<GitHub default>}"
echo "  ├ Domain / IP       : $DOMAIN"
echo "  ├ PG password       : ${PG_PASS:0:6}…  (${#PG_PASS} chars)"
echo "  ├ MQTT password     : ${MQTT_PASS:0:6}…  (${#MQTT_PASS} chars)"
echo "  ├ JWT secret        : ${JWT_SECRET:0:8}…  (${#JWT_SECRET} chars)"
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  echo "  ├ Telegram          : configured"
else
  echo "  ├ Telegram          : disabled"
fi
echo "  └ Admin users       : mehedi1–mehedi5 (passwords auto-generated)"
echo ""

if [ "${ASSUME_YES:-}" = "1" ]; then
  info "ASSUME_YES=1 — skipping confirmation prompt."
else
  CONFIRM=""
  if [ "$TTY_OK" = true ]; then
    read -rp "  Proceed? [Y/n]: " CONFIRM < /dev/tty || CONFIRM=""
  else
    error "No terminal available for confirmation. Re-run with ASSUME_YES=1 to proceed."
  fi
  CONFIRM="${CONFIRM:-Y}"
  case "$CONFIRM" in
    [Yy]|[Yy][Ee][Ss]) : ;;
    *) info "Aborted."; exit 0 ;;
  esac
fi

# ── 1. System packages ────────────────────────────────────────
step "1 / 11 — System packages"

sudo apt-get update -qq
sudo apt-get install -y -qq \
  ca-certificates curl gnupg lsb-release git openssl mosquitto-clients python3
success "Base packages installed"

# ── 2. Docker Engine ──────────────────────────────────────────
step "2 / 11 — Docker Engine"

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

# Add current user to docker group if not already there
if ! id -nG "$CURRENT_USER" | grep -qw docker; then
  sudo usermod -aG docker "$CURRENT_USER"
  DOCKER_GROUP_ADDED=true
  info "Added $CURRENT_USER to docker group (using sg for this session)"
else
  DOCKER_GROUP_ADDED=false
  info "$CURRENT_USER is already in the docker group"
fi

# Wrapper: run compose through sg docker only when the group membership was
# just added (current session doesn't have it yet). Root and existing members
# can call docker directly.
dc() {
  if [ "$EUID" -eq 0 ]; then
    docker compose -f "$APP_DIR/compose.yaml" "$@"
  elif [ "$DOCKER_GROUP_ADDED" = true ]; then
    sg docker -c "docker compose -f '$APP_DIR/compose.yaml' $*"
  else
    docker compose -f "$APP_DIR/compose.yaml" "$@"
  fi
}

# ── 3. Clone repository ───────────────────────────────────────
step "3 / 11 — Repository"

if [ -d "$APP_DIR/.git" ]; then
  info "Repo already exists — updating to latest..."
  sudo git -C "$APP_DIR" fetch --all --prune
  if [ -n "$REPO_BRANCH" ]; then
    sudo git -C "$APP_DIR" reset --hard "origin/${REPO_BRANCH}"
  else
    # Follow the remote default branch (origin/HEAD), falling back to main/master.
    REMOTE_BRANCH="$(sudo git -C "$APP_DIR" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||' || true)"
    REMOTE_BRANCH="${REMOTE_BRANCH:-main}"
    sudo git -C "$APP_DIR" reset --hard "origin/${REMOTE_BRANCH}" 2>/dev/null \
      || sudo git -C "$APP_DIR" reset --hard "origin/main" \
      || sudo git -C "$APP_DIR" reset --hard "origin/master"
  fi
elif [ -d "$APP_DIR" ] && [ -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
  error "Directory $APP_DIR exists and is not an empty git repo.\n  Move it aside first:  sudo mv $APP_DIR ${APP_DIR}.bak"
else
  info "Cloning from GitHub..."
  CLONE_ARGS=()
  [ -n "$REPO_BRANCH" ] && CLONE_ARGS=(-b "$REPO_BRANCH")
  sudo git clone "${CLONE_ARGS[@]+"${CLONE_ARGS[@]}"}" "$REPO_URL" "$APP_DIR"
fi
sudo chown -R "$CURRENT_USER":"$CURRENT_USER" "$APP_DIR"
success "Repo ready at $APP_DIR"

cd "$APP_DIR"

# ── 4. Write .env ─────────────────────────────────────────────
step "4 / 11 — Environment file"

if [ -f "$APP_DIR/.env" ]; then
  warn "Existing .env found — it will be overwritten with freshly generated secrets."
fi

cat > "$APP_DIR/.env" <<ENVEOF
# ColdChain — Generated by install.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# DO NOT commit this file — it contains secrets.

# ── Application ───────────────────────────────────────────────
SECURE_COOKIES=true
DEMO_MODE=false
DEMO_TIME_SCALE=1.0
HMAC_TS_WINDOW_S=60

# ── Database ──────────────────────────────────────────────────
# (Used by docker-compose; DATABASE_URL is built from this in compose.yaml)
POSTGRES_PASSWORD=${PG_PASS}

# ── MQTT broker ───────────────────────────────────────────────
MQTT_HOST=mosquitto
MQTT_PORT=1883
MQTT_USERNAME=collector
MQTT_PASSWORD=${MQTT_PASS}

# ── ColdChain JWT & device security ──────────────────────────
# COLDCHAIN_JWT_SECRET is REQUIRED — compose.yaml will refuse to start without it
COLDCHAIN_JWT_SECRET=${JWT_SECRET}

# Initial device HMAC secrets (empty JSON object = no pre-registered secrets)
# Add devices via admin panel after install to populate this.
DEVICE_SECRETS_JSON={}

# ── Telegram alerts (optional) ────────────────────────────────
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
ENVEOF

chmod 600 "$APP_DIR/.env"
success ".env written (600 permissions)"

# ── 5. Mosquitto password file ────────────────────────────────
step "5 / 11 — MQTT credentials"

mkdir -p "$APP_DIR/secrets"
# mosquitto_passwd: -c = create (only on first run), -b = batch (non-interactive).
# Without -c on re-runs, previously registered device credentials are preserved.
if [ -f "$APP_DIR/secrets/mosquitto.passwd" ]; then
  mosquitto_passwd -b "$APP_DIR/secrets/mosquitto.passwd" collector "$MQTT_PASS"
else
  mosquitto_passwd -c -b "$APP_DIR/secrets/mosquitto.passwd" collector "$MQTT_PASS"
fi
# Permissions matter here — three different UIDs need access:
#   • mosquitto broker runs as uid 1883 → must READ the file (0644 world-read)
#     (600 breaks it: with allow_anonymous false every MQTT auth fails)
#   • api container runs as appuser uid 1000 → must REWRITE the file in-place
#     when devices are registered/removed (owned by 1000:1000, dir 0775)
# mosquitto_passwd rewrites the file in place, so these permissions persist.
sudo chown -R 1000:1000 "$APP_DIR/secrets"
sudo chmod 0775 "$APP_DIR/secrets"
sudo chmod 0644 "$APP_DIR/secrets/mosquitto.passwd"
success "Mosquitto password file written to secrets/mosquitto.passwd"

# ── 6. Update Caddyfile domain ────────────────────────────────
step "6 / 11 — Caddy configuration"

# Replace the hardcoded demo domain with the user's domain/IP.
# The Caddyfile keeps `tls internal` (self-signed yet fully working over HTTPS)
# so the install works for IPs and unconfigured domains alike. For a trusted
# Let's Encrypt certificate, point a real domain at the server and remove the
# single `tls internal` line from the Caddyfile, then restart the stack.
if [[ "$DOMAIN" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  info "IP address detected — Caddy will use internal (self-signed) TLS."
else
  info "Hostname detected — Caddy will use internal TLS by default."
  info "(To switch to Let's Encrypt later, remove 'tls internal' from the Caddyfile.)"
fi
sed -i "s/telemetry\.durnibar\.tech/$DOMAIN/g" "$APP_DIR/Caddyfile"
sed -i "s/telemetry\.durnibar\.tech/$DOMAIN/g" "$APP_DIR/compose.yaml"

success "Caddyfile & compose.yaml patched for domain: $DOMAIN"

# ── 7. Build and start the stack ──────────────────────────────
step "7 / 11 — Build & start Docker Compose stack"

dc pull 2>/dev/null || true
dc build --pull
dc up -d --remove-orphans

success "Stack started (migrations running in background...)"

# ── 8. Wait for the API to become healthy ─────────────────────
step "8 / 11 — Health check"

info "Waiting for the API to become ready (up to 300 s)..."
ELAPSED=0
HEALTH_OK=false
while [ "$ELAPSED" -lt 300 ]; do
  # Primary: through the Caddy proxy (the path a real browser will use).
  if curl -sf "http://localhost/health/ready" -o /dev/null 2>/dev/null; then
    HEALTH_OK=true; break
  fi
  # Fallback: probe the API directly inside the compose network
  # (port 8000 is intentionally not published on the host).
  if dc exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=3)" 2>/dev/null; then
    HEALTH_OK=true; break
  fi
  sleep 5
  ELAPSED=$((ELAPSED + 5))
  printf "."
done
echo ""

if [ "$HEALTH_OK" = false ]; then
  warn "API did not become healthy within 300 s. Check logs:"
  dc logs --tail=50 api migrate db || true
  error "Installation failed at health check. Fix the issue above and re-run."
fi
success "API is healthy"

# ── 9. Seed demo data ─────────────────────────────────────────
step "9 / 11 — Seed demo data & ML training"

info "Running ColdChain seed script (users, fridges, batches, synthetic readings)..."
if dc exec -T api python -m scripts.seed_coldchain; then
  success "Demo data seeded"
else
  warn "Seed script returned non-zero; it may have already run (data already exists)."
fi

info "Training ML forecast & compressor-health models..."
dc up -d --wait --wait-timeout 600 2>/dev/null || true
if dc run --rm --build ml-train; then
  success "ML models trained"
else
  warn "ML training exited with an error — check compose logs for 'ml-train'."
fi

# ── Create mehedi1–5 admin users via HTTP API ─────────────────
info "Creating admin users via API (mehedi1-mehedi5)..."

# Note: go through the Caddy proxy on port 80 — port 8000 is not published.
ADMIN_TOKEN=""
for _attempt in 1 2 3; do
  ADMIN_TOKEN="$(curl -sf -X POST "http://localhost/api/cc/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"admin123"}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)"
  [ -n "$ADMIN_TOKEN" ] && break
  sleep 3
done

if [ -z "$ADMIN_TOKEN" ]; then
  warn "Could not obtain admin JWT — skipping mehedi1–5 user creation."
  warn "You can create them manually later from the admin panel."
else
  for i in 1 2 3 4 5; do
    IDX=$((i - 1))
    PASS="${ADMIN_PASSWORDS[$IDX]}"
    HTTP_CODE="$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST "http://localhost/api/users" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $ADMIN_TOKEN" \
      -d "{\"username\":\"mehedi${i}\",\"password\":\"${PASS}\",\"role\":\"admin\"}" || echo 0)"
    if [[ "$HTTP_CODE" == "201" ]]; then
      success "  Created admin: mehedi${i}"
    elif [[ "$HTTP_CODE" == "409" ]]; then
      info "  mehedi${i}: already exists (password unchanged)"
    else
      warn "  mehedi${i}: HTTP ${HTTP_CODE} — set the password from the admin panel."
    fi
  done
fi

# ── 10. Smoke tests ───────────────────────────────────────────
step "10 / 11 — Smoke tests"

# Dashboard through Caddy (HTTPS / HTTP fallback)
FRONT_CODE="$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/ 2>/dev/null || true)"
if [ "$FRONT_CODE" = "000" ]; then
  FRONT_CODE="$(curl -s -o /dev/null -w '%{http_code}' http://localhost/ || true)"
fi
if [ "$FRONT_CODE" = "200" ]; then
  success "Dashboard responds (HTTP $FRONT_CODE)"
else
  warn "Dashboard check returned HTTP ${FRONT_CODE:-000} (expected 200)"
fi

# MQTT broker with the collector credentials
if mosquitto_sub -h localhost -p 1883 -u collector -P "$MQTT_PASS" \
     -t 'cc/#' -t 'devices/#' -C 1 -W 5 >/dev/null 2>&1; then
  success "MQTT broker reachable and collector credentials accepted"
else
  warn "MQTT broker check failed (auth or port) — verify 'docker logs coldchain-mosquitto-1'."
fi

# ── 11. Systemd service ───────────────────────────────────────
step "11 / 11 — Systemd auto-start"

sudo tee /etc/systemd/system/coldchain.service > /dev/null <<SVCEOF
[Unit]
Description=ColdChain Vaccine Storage Monitor (Docker Compose)
Wants=network-online.target
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=600
User=${CURRENT_USER}
Environment=HOME=/home/${CURRENT_USER}

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable coldchain.service
success "coldchain.service enabled (will auto-start on boot)"

# Open firewall only when ufw is already active — never enable it here.
if command -v ufw >/dev/null 2>&1 && sudo ufw status 2>/dev/null | head -n1 | grep -q "active"; then
  info "ufw is active — allowing 80, 443, 1883, 8883/tcp..."
  for p in 80 443 1883 8883; do
    sudo ufw allow "${p}/tcp" >/dev/null 2>&1 || true
  done
  success "Firewall ports opened"
fi

# ── Final summary ─────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║            ✓  Installation Complete!                 ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${RESET}"

DISPLAY_URL="https://${DOMAIN}  (Caddy internal CA — accept the browser warning)"
# If HTTPS did not answer, point at plain HTTP instead
if [ "${FRONT_CODE}" != "200" ]; then
  DISPLAY_URL="http://${DOMAIN}"
fi

echo -e "${BOLD}  Access${RESET}"
echo "  ├ Dashboard              : ${DISPLAY_URL}"
echo "  ├ API docs (via proxy)   : https://${DOMAIN}/api/docs"
echo "  └ MQTT broker            : ${DOMAIN}:1883  (MQTTS: ${DOMAIN}:8883 once certs exist)"
echo ""
echo -e "${BOLD}  Credentials${RESET}"
echo "  ├ Seeded admin            : admin  /  admin123   ← CHANGE THIS"
echo "  ├ Seeded pharmacist       : pharmacist1  /  pharma123"
echo "  ├ Seeded inspector        : inspector1   /  inspect123"
for i in 1 2 3 4 5; do
  IDX=$((i - 1))
  echo "  ├ mehedi${i}                 : ${ADMIN_PASSWORDS[$IDX]}"
done
echo ""
echo -e "${BOLD}  Secrets (keep these safe!)${RESET}"
echo "  ├ PostgreSQL password     : ${PG_PASS}"
echo "  ├ MQTT collector password : ${MQTT_PASS}"
echo "  ├ JWT secret              : ${JWT_SECRET:0:16}… (full value in .env)"
echo "  └ Secrets file            : ${APP_DIR}/.env"
echo ""
if [ "${DOCKER_GROUP_ADDED:-false}" = true ]; then
  warn "Docker group was added this session — log out and back in (or run 'newgrp docker')"
  warn "before using plain 'docker' commands."
fi
echo -e "${BOLD}  Useful commands${RESET}"
echo "  ├ View logs               : docker compose -f ${APP_DIR}/compose.yaml logs -f"
echo "  ├ Restart stack           : sudo systemctl restart coldchain"
echo "  ├ Re-train ML models      : docker compose -f ${APP_DIR}/compose.yaml run --rm ml-train"
echo "  ├ Re-seed demo data       : docker compose -f ${APP_DIR}/compose.yaml exec api python -m scripts.seed_coldchain"
echo "  └ Update (pull & restart) : git -C ${APP_DIR} pull && sudo systemctl restart coldchain"
echo ""
warn "Remember to:"
warn "  1. Change the default admin/pharmacist/inspector passwords from the admin panel."
warn "  2. Register your ESP32 device IDs and HMAC secrets in the admin panel → Devices."
warn "  3. Add device HMAC secrets to DEVICE_SECRETS_JSON in ${APP_DIR}/.env and restart."
[ -z "$TELEGRAM_BOT_TOKEN" ] && warn "  4. Configure Telegram alerts in ${APP_DIR}/.env (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)."
echo ""
success "ColdChain is running. Happy cold-chaining! 🧊💉"
