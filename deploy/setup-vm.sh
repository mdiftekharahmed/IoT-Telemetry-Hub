#!/usr/bin/env bash
# IoT Telemetry Hub — VM bootstrap script
# Run once on a fresh Ubuntu 24.04 VM as root or a sudo user.
# Usage: bash setup-vm.sh
set -euo pipefail

REPO_URL="https://github.com/mdiftekharahmed/IoT-Telemetry-Hub.git"
APP_DIR="/opt/iot-telemetry-hub"
APP_USER="telemetry"

echo "==> [1/6] Installing Docker Engine..."
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg lsb-release
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker

echo "==> [2/6] Creating app user and directory..."
id -u "$APP_USER" &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
usermod -aG docker "$APP_USER" || true
mkdir -p "$APP_DIR"

echo "==> [3/6] Cloning repository..."
if [ -d "$APP_DIR/.git" ]; then
  echo "    Repo already exists — pulling latest..."
  git -C "$APP_DIR" pull
else
  git clone "$REPO_URL" "$APP_DIR"
fi
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

echo ""
echo "==> Next: Set up secrets and .env, then run: cd $APP_DIR && bash deploy/start.sh"
echo ""
echo "Bootstrap done. Docker $(docker --version) installed."
