# ColdChain Vaccine & Medicine Storage Monitor

> **Branch:** `BUBT_IOT_HACKATHON`  
> **Client docs:** [User Manual & Admin Handover](CLIENT_USER_MANUAL.md) | [ESP32 TLS & Firmware Security Guide](docs/tls-firmware-guide.md)

A production-ready, end-to-end cold-chain monitoring platform for vaccine and medicine storage.  
It combines an ESP32 IoT firmware, an MQTT broker, a FastAPI backend, a React dashboard, ML-powered temperature forecasting, and a Caddy HTTPS proxy — all orchestrated with Docker Compose and deployable in one command.

---

## Features

| Category | Details |
|---|---|
| **Dashboard** | Real-time React SPA — temperature charts, device status, batch heat-budget gauges |
| **Cold-Chain FSM** | SAFE / WARNING / BREACH state machine with red-latch discard alert |
| **MQTT Security** | Per-device HMAC-SHA256 signed messages, nonce dedup, timestamp window guard |
| **ML Forecast** | LightGBM temperature forecasting + isolation-forest compressor-health model |
| **Alerts** | Telegram bot alerts for breach, door-open, power-fail, batch at-risk / discard |
| **Role-Based Auth** | JWT — `admin`, `pharmacist`, `inspector` roles |
| **Heat Budget** | Vaccine exposure tracking (VVM-equivalent) per batch per fridge |
| **Auto HTTPS** | Caddy reverse proxy with self-signed cert for IP, or Let's Encrypt for a domain |

---

## One-Line Install (Ubuntu 22.04 / 24.04)

> Works on a **fresh server** — Docker and all dependencies are installed automatically.

```bash
# Install from the hackathon branch (recommended):
REPO_BRANCH=BUBT_IOT_HACKATHON bash <(curl -fsSL \
  https://raw.githubusercontent.com/mdiftekharahmed/IoT-Telemetry-Hub/BUBT_IOT_HACKATHON/install.sh)
```

Or fetch the script first and inspect it, then run:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/mdiftekharahmed/IoT-Telemetry-Hub/BUBT_IOT_HACKATHON/install.sh \
  -o install.sh
bash install.sh
```

The installer will:
1. Install Docker Engine + Compose plugin, `mosquitto-clients`, `curl`, `git`
2. Clone the repo to `/opt/coldchain`
3. Prompt for your server IP / domain, then generate all secrets and write `.env`
4. Create the Mosquitto password file (`secrets/mosquitto.passwd`)
5. Build all Docker images, run DB migrations, seed parameters
6. Train the ML forecast and health models
7. Create default users (`admin`, `pharmacist1`, `inspector1`, `mehedi1`–`mehedi5`)
8. Register a `coldchain.service` systemd unit for auto-start on boot

**Default credentials** (change these in the Admin panel after first login):

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Admin |
| `pharmacist1` | `pharma123` | Pharmacist |
| `inspector1` | `inspect123` | Inspector |
| `mehedi1` … `mehedi5` | `Admin@mehedi1` … `Admin@mehedi5` | Admin |

Access the dashboard at **`https://<your-server-ip>`**.  
The browser shows a TLS warning for the self-signed cert — click **Advanced → Proceed**.

---

## Managing the Service

```bash
sudo systemctl status   coldchain   # check if running
sudo systemctl start    coldchain   # start (containers come up)
sudo systemctl stop     coldchain   # stop (containers go down)
sudo systemctl restart  coldchain   # restart
sudo journalctl -u coldchain -f     # live logs
```

Manage individual containers:

```bash
cd /opt/coldchain
docker compose ps                        # container health & ports
docker compose logs -f api               # API logs
docker compose logs worker | grep -E "outcome|Rejected|rejected|error|ERROR"  # MQTT worker errors
docker compose restart proxy             # reload Caddy config
```

---

## Full Nuke & Reinstall

**Stop & remove the old ColdChain stack completely**, then reinstall:

```bash
# --- NUKE (run on the server) ---
sudo systemctl stop coldchain 2>/dev/null
sudo systemctl disable coldchain 2>/dev/null
sudo rm -f /etc/systemd/system/coldchain.service
sudo systemctl daemon-reload

[ -d /opt/coldchain ] && \
  cd /opt/coldchain && \
  sudo docker compose down -v --rmi all

cd / && sudo rm -rf /opt/coldchain

# --- REINSTALL ---
REPO_BRANCH=BUBT_IOT_HACKATHON bash <(curl -fsSL \
  https://raw.githubusercontent.com/mdiftekharahmed/IoT-Telemetry-Hub/BUBT_IOT_HACKATHON/install.sh)
```

> **Legacy stack cleanup** — if you previously installed the old `iot-telemetry-hub` stack, remove it first:
> ```bash
> sudo systemctl stop iot-telemetry-hub 2>/dev/null
> sudo systemctl disable iot-telemetry-hub 2>/dev/null
> sudo rm -f /etc/systemd/system/iot-telemetry-hub.service
> sudo systemctl daemon-reload
> [ -d /opt/iot-telemetry-hub ] && \
>   cd /opt/iot-telemetry-hub && \
>   sudo docker compose down -v --rmi all
> cd / && sudo rm -rf /opt/iot-telemetry-hub
> ```

---

## Simulation Seed Script (`sim_seed.py`)

`sim_seed.py` publishes realistic simulated fridge telemetry via MQTT every 5 seconds.  
It auto-registers devices via the REST API and signs every message with HMAC-SHA256 — the same as a real ESP32 firmware node. **Press Ctrl+C to stop.**

### Quick start

```bash
# Install dependencies (only needed once)
pip install paho-mqtt requests

# Run against the lab server (1 fridge, normal scenario)
python sim_seed.py \
  --host 100.108.219.54 \
  --mqtt-pass ColdChainMQTT2024 \
  --api-http          # use HTTP for API login (self-signed cert on IP)
```

### Multiple fridges & scenarios

```bash
# 3 fridges, rotating scenario (normal → door stuck → power fail → breach)
python sim_seed.py --host 100.108.219.54 --mqtt-pass ColdChainMQTT2024 \
  --fridges 3 --scenario cycle --api-http

# Simulate a temperature breach (compressor failure)
python sim_seed.py --host 100.108.219.54 --mqtt-pass ColdChainMQTT2024 \
  --scenario breach --api-http

# Door stuck open — triggers door-open alarm after 60 s
python sim_seed.py --host 100.108.219.54 --mqtt-pass ColdChainMQTT2024 \
  --scenario door_stuck --api-http

# Mains power failure — battery drains
python sim_seed.py --host 100.108.219.54 --mqtt-pass ColdChainMQTT2024 \
  --scenario power_fail --api-http
```

### Full CLI reference

```
usage: sim_seed.py [options]

options:
  --host HOST           MQTT broker / API host (default: 100.108.219.54)
  --mqtt-port PORT      MQTT port (default: 1883)
  --mqtt-user USER      MQTT username (default: collector)
  --mqtt-pass PASS      MQTT password
  --api-user USER       API username for device auto-registration (default: admin)
  --api-pass PASS       API password (default: admin123)
  --fridges N           Number of simulated fridges (default: 1)
  --interval SECS       Publish interval in seconds (default: 5.0)
  --api-http            Use plain HTTP for API calls (bypass self-signed TLS on IP)
  --scenario SCENARIO   Simulation scenario:
                          normal      steady cold, brief door opens every 3 min
                          door_stuck  door held open 90 s every 5 min
                          breach      compressor off, temp climbs to room temp
                          power_fail  mains lost, battery drains
                          cycle       rotates through all scenarios every 2 min
```

### Simulated telemetry fields

| Field | Unit | Description |
|---|---|---|
| `temp_c` | °C | Fridge internal temperature (sine + noise, compressor physics) |
| `door_open` | bool | Door state — 1 = open |
| `door_open_s` | s | Cumulative seconds door has been open in current window |
| `compressor_on` | bool | Compressor relay state |
| `lockout_s` | s | Remaining compressor min-off lockout seconds |
| `power_source` | text | `MAINS` or `BATTERY` |
| `mains_present` | bool | 1 = AC present |
| `battery_pct` | % | Backup battery state-of-charge |
| `battery_v` | V | Battery terminal voltage |
| `state` | text | FSM classification: `SAFE` / `WARNING` / `BREACH` |
| `red_latched` | bool | Discard latch (breach scenario) |
| `sim_mode` | bool | Always `1` — marks readings as simulated |

---

## Useful Diagnostic Commands

```bash
# MQTT worker — see if telemetry is accepted or rejected
docker compose logs worker | grep -E "outcome|Rejected|rejected|error|ERROR"

# Check all container health
docker compose ps

# Tail all logs
docker compose logs -f

# Test API health directly
curl http://localhost:8000/health/ready

# Test through Caddy proxy
curl -sk https://localhost/health/ready

# MQTT test publish (from the server)
mosquitto_pub -h localhost -p 1883 \
  -u collector -P ColdChainMQTT2024 \
  -t 'cc/test/status' -m '{"status":"online"}'

# Subscribe to all ColdChain telemetry
mosquitto_sub -h localhost -p 1883 \
  -u collector -P ColdChainMQTT2024 \
  -t 'cc/#' -v
```

---

## Securing with a Free Public TLS Certificate

By default the hub uses a Caddy-managed self-signed cert for the IP address.  
For a trusted HTTPS connection (no browser warning), point a free domain at your server:

1. Register a free subdomain at [DuckDNS](https://www.duckdns.org/) and point it to your IP.
2. Edit the Caddyfile on the server:
   ```bash
   sudo nano /opt/coldchain/Caddyfile
   ```
3. Replace `100.108.219.54` with your domain and remove the `tls internal` line:
   ```caddyfile
   your-project.duckdns.org {
       handle /api/* { reverse_proxy api:8000 }
       handle /health/* { reverse_proxy api:8000 }
       handle /check/* { reverse_proxy frontend:3000 }
       handle /app* { reverse_proxy frontend:3000 }
       handle { reverse_proxy frontend:3000 }
   }
   ```
4. Restart:
   ```bash
   sudo systemctl restart coldchain
   ```
   Caddy auto-requests and renews the Let's Encrypt certificate.

---

## Device Registration & ESP32 Setup

### Step 1 — Register the device in the dashboard

1. Log in → **Admin → Devices → Add Device**
2. Enter a **Device ID** (e.g. `fridge-01`) and a friendly name
3. The dashboard generates an HMAC secret — copy it

### Step 2 — Flash the secret into the ESP32 firmware

The firmware uses HMAC-SHA256 to sign every telemetry message.  
See [docs/tls-firmware-guide.md](docs/tls-firmware-guide.md) for the full firmware setup including TLS (MQTTS on port 8883).

### MQTT topic format (ColdChain)

```
cc/<device_id>/telemetry   # telemetry publish (device → broker)
cc/<device_id>/sync        # offline batch upload
cc/<device_id>/event       # events (mains_restored, door_open, …)
cc/<device_id>/status      # heartbeat / LWT
cc/<device_id>/cmd         # commands (broker → device)
```

### Message format

```json
{
  "v":     1,
  "dev":   "fridge-01",
  "seq":   1042,
  "ts":    1793812849,
  "nonce": "a3f9c1d2e8b74f61",
  "d": {
    "temp_c": 4.72,
    "door_open": 0,
    "door_open_s": 0,
    "compressor_on": 1,
    "lockout_s": 0,
    "power_source": "MAINS",
    "mains_present": 1,
    "battery_pct": 98.5,
    "battery_v": 4.07,
    "state": "SAFE",
    "red_latched": 0,
    "sim_mode": 0
  },
  "sig": "<hmac-sha256-hex>"
}
```

HMAC signing:
```
sig = HMAC-SHA256(device_secret_hex,
        "dev|seq|ts|nonce|canonical_json(d)")
```
where `canonical_json` = sorted keys, no spaces, floats to 2 dp.

---

## Developer Notes

- **Local dev**: Copy `.env.example` to `.env`, fill in secrets, then `docker compose up --build -d`
- **API docs**: `http://localhost:8000/docs` (FastAPI Swagger UI, available when running)
- **Tests**: `pytest` — 105 tests covering ingestion, RBAC, ML, budget engine, E2E
- **ML retrain**: `docker compose run --rm ml-train`
- **DB migrations**: `docker compose run --rm migrate`

---

*BUBT IoT Hackathon 2024 — ColdChain team*
