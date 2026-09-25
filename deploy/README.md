# Deployment guide — IoT Telemetry Hub

Target: Ubuntu 24.04 LTS · Docker Engine · Proxmox VM (or any Linux VM/VPS)

---

## 1 — First time: install Docker and clone the repo

Run as root or a user with sudo on the VM:

```bash
curl -fsSL https://raw.githubusercontent.com/mdiftekharahmed/IoT-Telemetry-Hub/main/deploy/setup-vm.sh | sudo bash
```

This installs Docker Engine + Compose plugin and clones the repo to `/opt/iot-telemetry-hub`.

---

## 2 — Create `.env`

```bash
cd /opt/iot-telemetry-hub
cp .env.example .env
nano .env          # or vim .env
```

Set at minimum:

| Variable | Value |
|---|---|
| `POSTGRES_PASSWORD` | Long random string — e.g. `openssl rand -base64 32` |
| `MQTT_PASSWORD` | Password for the collector MQTT user |
| `API_PORT` | Port to expose (default `8000`) |
| `SECURE_COOKIES` | `true` once HTTPS is in front |

---

## 3 — Generate the Mosquitto password file

```bash
sudo apt-get install -y mosquitto-clients
bash deploy/gen-mqtt-passwords.sh
```

For each IoT device you register in the UI, also add its MQTT credentials:

```bash
mosquitto_passwd -b secrets/mosquitto.passwd <device_id> <device_password>
```

The `device_id` here must **exactly match** the Device ID registered in the admin UI.

---

## 4 — Start the stack

```bash
bash deploy/start.sh
```

This builds the app image, runs Alembic migrations, then starts all services.

---

## 5 — Create the first admin user

```bash
docker compose exec api python -m app.cli admin
```

Follow the prompts to set a username and password.

---

## 6 — Verify

Open `http://<vm-ip>:<API_PORT>` in your browser → you should see the login page.

Check all services are healthy:

```bash
docker compose ps
curl http://localhost:${API_PORT}/health/ready
```

---

## Day-to-day operations

| Task | Command |
|---|---|
| View logs | `docker compose logs -f api` |
| Update after a `git pull` | `bash deploy/start.sh` |
| Add a device MQTT credential | `mosquitto_passwd -b secrets/mosquitto.passwd <id> <pw>` then `docker compose restart mosquitto` |
| Stop the stack | `docker compose down` |
| Full wipe (including data) | `docker compose down -v` ⚠️ deletes the database |

---

## Firewall

Only expose the port you set for `API_PORT`. Keep port `5432` (PostgreSQL) and `1883` (MQTT) **off** the public network — they are already bound to the internal Docker network only.

If devices need to reach the MQTT broker from outside the VM, expose port `1883` in `compose.yaml` and protect it with a firewall rule to known IPs only.
