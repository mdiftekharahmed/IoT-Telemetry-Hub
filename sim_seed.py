#!/usr/bin/env python3
"""
ColdChain Live Simulation Seed Script
======================================
Sends realistic simulated telemetry via MQTT to the ColdChain system every 5 s.
Press Ctrl+C to stop.

Usage
-----
  # Minimal — uses defaults (connects to localhost:1883, creates a demo device):
  python sim_seed.py

  # Against deployed VM:
  python sim_seed.py --host 100.108.219.54 --mqtt-pass ColdChainMQTT2024

  # Multiple simulated fridges:
  python sim_seed.py --host 100.108.219.54 --mqtt-pass ColdChainMQTT2024 --fridges 3

  # Trigger a scary scenario (breach + power-fail + door-open):
  python sim_seed.py --host 100.108.219.54 --mqtt-pass ColdChainMQTT2024 --scenario breach

Requirements
-----------
  pip install paho-mqtt requests

The script auto-registers devices via the REST API (admin/admin123) if they
don't exist yet, using a stable per-fridge HMAC secret derived from a local
seed phrase.  No manual DB setup needed.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import math
import random
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

try:
    import paho.mqtt.client as mqtt
except ImportError:
    sys.exit("Install paho-mqtt first:  pip install paho-mqtt")

try:
    import requests
except ImportError:
    sys.exit("Install requests first:  pip install requests")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sim")

# ---------------------------------------------------------------------------
# HMAC helpers (mirror of app/security.py)
# ---------------------------------------------------------------------------

def canonical_json(d: dict) -> str:
    """Deterministic JSON: sorted keys, no spaces, 2-dp floats (matches server)."""
    def _default(obj):
        if isinstance(obj, float):
            return f"{obj:.2f}"
        raise TypeError(type(obj))
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=_default)


def hmac_sign(secret_hex: str, parts: list[str]) -> str:
    """HMAC-SHA256 over '|'.join(parts) — matches app/security.py exactly."""
    key = bytes.fromhex(secret_hex)
    msg = "|".join(str(p) for p in parts).encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def stable_secret(device_id: str, seed: str = "coldchain-sim-seed-2024") -> str:
    """Derive a stable 32-byte hex secret from device_id + seed phrase."""
    h = hashlib.sha256(f"{seed}:{device_id}".encode()).hexdigest()
    return h  # 64 hex chars = 32 bytes


# ---------------------------------------------------------------------------
# Physics / simulation model
# ---------------------------------------------------------------------------

@dataclass
class FridgeSim:
    """
    Single-fridge physics simulator.

    Temperature model:
      - Compressor ON  → temp drifts down toward target_cold  (exponential)
      - Compressor OFF → temp drifts up toward ambient        (exponential)
      - Door open      → adds +1–3 °C/reading of heat ingress
      - Compressor has minimum-off lockout (lockout_s counts down)
    """

    device_id: str
    secret: str

    # Scenario control (changed by --scenario flag or mid-run)
    scenario: str = "normal"           # "normal" | "breach" | "power_fail" | "door_stuck"

    # Physics constants
    ambient_c: float = 25.0           # room temperature
    target_cold: float = 4.5          # compressor target when ON
    safe_min: float = 2.0
    safe_max: float = 8.0
    tau_cool: float = 180.0           # seconds to cool ~63% when compressor ON
    tau_warm: float = 300.0           # seconds to warm ~63% when compressor OFF
    lockout_max_s: int = 90           # compressor min-off lockout seconds
    door_alarm_s: int = 60            # door-open alarm threshold

    # Runtime state
    temp_c: float = field(default=4.5)
    compressor_on: bool = True
    lockout_s: int = 0
    door_open: bool = False
    door_open_s: int = 0
    mains_present: bool = True
    battery_pct: float = 95.0
    battery_v: float = 3.9
    heat_budget_minutes: float = 60.0
    red_latched: bool = False
    seq: int = 0

    # Internal FSM
    _t: float = field(default_factory=time.time)          # last tick time
    _door_timer: float = 0.0
    _breach_ticks: int = 0
    _power_fail_ticks: int = 0
    _scenario_ticks: int = 0

    def __post_init__(self):
        self._t = time.time()

    # ------------------------------------------------------------------ tick
    def tick(self, dt: float) -> dict:
        """
        Advance simulation by dt seconds.
        Returns the full telemetry dict ready for the MQTT 'd' field.
        """
        self._scenario_ticks += 1
        self._run_scenario(dt)
        self._physics(dt)
        self._fsm()
        self.seq += 1
        return self._snapshot()

    # -------------------------------------------------------------- scenario
    def _run_scenario(self, dt: float):
        t = self._scenario_ticks

        if self.scenario == "normal":
            # Occasional 5-second door opens every ~3 min
            if t % 36 == 0:          # every 36 × 5 s = 3 min
                self.door_open = True
            if t % 36 == 1:
                self.door_open = False
            self.mains_present = True

        elif self.scenario == "door_stuck":
            # Door held open for 90 s then closes
            if t % 60 < 18:         # open 90 s, closed 210 s
                self.door_open = True
            else:
                self.door_open = False
            self.mains_present = True

        elif self.scenario == "breach":
            # Simulate a compressor failure: temp climbs to room temp
            self.compressor_on = False
            self.lockout_s = 0
            self.mains_present = True
            if t > 100:
                self.red_latched = True

        elif self.scenario == "power_fail":
            # Mains lost after 10 ticks, battery drains
            if t > 10:
                self.mains_present = False
                self.battery_pct = max(0.0, self.battery_pct - 0.5)
                self.battery_v   = 3.0 + (self.battery_pct / 100.0) * 1.2
            else:
                self.mains_present = True

        elif self.scenario == "cycle":
            # Rotate through all scenarios every 2 min
            phase = (t // 24) % 4
            sub_scenarios = ["normal", "door_stuck", "power_fail", "breach"]
            self.scenario = sub_scenarios[phase]

    # --------------------------------------------------------------- physics
    def _physics(self, dt: float):
        """Simple first-order thermal model."""
        if self.compressor_on:
            # Cool toward target_cold
            alpha = 1 - math.exp(-dt / self.tau_cool)
            self.temp_c += alpha * (self.target_cold - self.temp_c)
        else:
            # Warm toward ambient
            alpha = 1 - math.exp(-dt / self.tau_warm)
            self.temp_c += alpha * (self.ambient_c - self.temp_c)

        # Door heat ingress: +0.05–0.15 °C per second the door is open
        if self.door_open:
            ingress = random.uniform(0.05, 0.15) * dt
            self.temp_c += ingress
            self.door_open_s = int(self.door_open_s + dt)
        else:
            self.door_open_s = 0

        # Add small sensor noise ±0.1 °C
        self.temp_c += random.uniform(-0.1, 0.1)
        self.temp_c = round(self.temp_c, 2)

        # Compressor logic (simple bang-bang with lockout)
        if self.lockout_s > 0:
            self.lockout_s = max(0, int(self.lockout_s - dt))
        else:
            if self.scenario != "breach":
                if self.compressor_on and self.temp_c <= self.target_cold - 0.5:
                    # Switch off — start lockout
                    self.compressor_on = False
                    self.lockout_s = self.lockout_max_s
                elif not self.compressor_on and self.temp_c >= self.safe_max - 0.5:
                    self.compressor_on = True

        # Battery: slowly drains when on battery, charges on mains
        if self.mains_present:
            self.battery_pct = min(100.0, self.battery_pct + 0.1)
        else:
            self.battery_pct = max(0.0, self.battery_pct - 0.3)
        self.battery_v = round(3.0 + (self.battery_pct / 100.0) * 1.2, 2)
        self.battery_pct = round(self.battery_pct, 1)

        # Heat budget (simple: drains when temp > 8 °C)
        if self.temp_c > self.safe_max:
            drain = (dt / 60.0)   # 1 min budget per 1 min over threshold
            self.heat_budget_minutes = max(0.0, self.heat_budget_minutes - drain)
        else:
            # Slowly recover budget (optional — comment out for strict model)
            self.heat_budget_minutes = min(60.0, self.heat_budget_minutes + dt / 600.0)
        self.heat_budget_minutes = round(self.heat_budget_minutes, 2)

    # ------------------------------------------------------------------- fsm
    def _fsm(self):
        """Classify current state."""
        if self.temp_c < self.safe_min or self.temp_c > self.safe_max:
            if not self.red_latched and self.scenario == "breach":
                self.red_latched = True
        # red_latched cleared externally (dashboard reset)

    # --------------------------------------------------------------- snapshot
    def _snapshot(self) -> dict:
        """Build the 'd' telemetry dict."""
        if self.temp_c < self.safe_min or self.temp_c > self.safe_max:
            state = "BREACH"
        elif self.temp_c > self.safe_max - 1.0 or (self.door_open and self.door_open_s > 30):
            state = "WARNING"
        else:
            state = "SAFE"

        power_src = "MAINS" if self.mains_present else "BATTERY"

        return {
            "temp_c":           float(self.temp_c),
            "door_open":        int(self.door_open),
            "door_open_s":      int(self.door_open_s),
            "compressor_on":    int(self.compressor_on),
            "lockout_s":        int(self.lockout_s),
            "power_source":     power_src,
            "mains_present":    int(self.mains_present),
            "battery_pct":      float(self.battery_pct),
            "battery_v":        float(self.battery_v),
            "state":            state,
            "red_latched":      int(self.red_latched),
            "sim_mode":         1,
        }


# ---------------------------------------------------------------------------
# MQTT publisher
# ---------------------------------------------------------------------------

class SimPublisher:
    def __init__(self, host: str, port: int, username: str, password: str):
        self._host = host
        self._port = port
        self._connected = False

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"coldchain-sim-{secrets.token_hex(4)}",
            clean_session=True,
        )
        self._client.username_pw_set(username, password)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("MQTT connect failed: %s", reason_code)
        else:
            self._connected = True
            log.info("✅ MQTT connected to %s:%s", self._host, self._port)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._connected = False
        log.warning("MQTT disconnected: %s — will reconnect", reason_code)

    def connect(self):
        self._client.connect_async(self._host, self._port, keepalive=60)
        self._client.loop_start()
        # Wait up to 5 s for the connection
        for _ in range(50):
            if self._connected:
                return
            time.sleep(0.1)
        log.warning("MQTT not connected yet — continuing anyway (will retry)")

    def disconnect(self):
        self._client.disconnect()
        self._client.loop_stop()

    def publish(self, device_id: str, secret: str, seq: int, d: dict) -> bool:
        """Sign and publish a single telemetry reading. Returns True on success."""
        ts    = int(time.time())
        nonce = secrets.token_hex(8)

        # Only include fields in ALLOWED_DATA_FIELDS — keep d clean
        allowed = {
            "temp_c", "door_open", "door_open_s", "compressor_on", "lockout_s",
            "power_source", "mains_present", "battery_pct", "battery_v",
            "state", "red_latched", "sim_mode",
        }
        d_clean = {k: v for k, v in d.items() if k in allowed}

        d_canon = canonical_json(d_clean)
        sig = hmac_sign(secret, [device_id, str(seq), str(ts), nonce, d_canon])

        msg = json.dumps({
            "v":     1,
            "dev":   device_id,
            "seq":   seq,
            "ts":    ts,
            "nonce": nonce,
            "d":     d_clean,
            "sig":   sig,
        })

        topic = f"cc/{device_id}/telemetry"
        result = self._client.publish(topic, msg, qos=1)
        return result.rc == mqtt.MQTT_ERR_SUCCESS


# ---------------------------------------------------------------------------
# Device auto-registration via REST API
# ---------------------------------------------------------------------------

def ensure_device(api_base: str, device_id: str, secret: str,
                  username: str = "admin", password: str = "admin123") -> bool:
    """
    Login and register a device if it doesn't exist yet.
    Returns True on success, False on any error.
    """
    session = requests.Session()
    session.verify = False  # self-signed cert on lab server

    # 1. Login
    try:
        r = session.post(f"{api_base}/api/cc/auth/login",
                         json={"username": username, "password": password},
                         timeout=10)
        r.raise_for_status()
        token = r.json()["access_token"]
    except Exception as e:
        log.error("Login failed (%s): %s", api_base, e)
        return False

    headers = {"Authorization": f"Bearer {token}"}

    # 2. Check if device exists
    try:
        r = session.get(f"{api_base}/api/cc/devices/{device_id}", headers=headers, timeout=10)
        if r.status_code == 200:
            log.info("Device %s already registered ✓", device_id)
            return True
    except Exception:
        pass

    # 3. Register device
    payload = {
        "device_id":   device_id,
        "name":        f"Sim Fridge — {device_id}",
        "secret":      secret,
        "enabled":     True,
    }
    try:
        r = session.post(f"{api_base}/api/cc/devices", json=payload,
                         headers=headers, timeout=10)
        if r.status_code in (200, 201):
            log.info("Device %s registered ✓", device_id)
            return True
        else:
            log.warning("Device register returned %s: %s", r.status_code, r.text[:200])
            # Try alternate endpoint
            r2 = session.post(f"{api_base}/api/devices", json=payload,
                              headers=headers, timeout=10)
            if r2.status_code in (200, 201):
                log.info("Device %s registered via /api/devices ✓", device_id)
                return True
            log.error("Device register failed: %s", r2.text[:200])
            return False
    except Exception as e:
        log.error("Device register error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Pretty status line
# ---------------------------------------------------------------------------

STATE_ICONS = {"SAFE": "🟢", "WARNING": "🟡", "BREACH": "🔴"}
POWER_ICONS = {"MAINS": "⚡", "BATTERY": "🔋"}

def status_line(sim: FridgeSim, d: dict) -> str:
    state_icon = STATE_ICONS.get(d["state"], "❓")
    power_icon = POWER_ICONS.get(d["power_source"], "❓")
    door = "🚪OPEN " if d["door_open"] else "     "
    comp = "❄️ " if d["compressor_on"] else "  "
    return (
        f"  {sim.device_id:<20} "
        f"seq={sim.seq:<6} "
        f"temp={d['temp_c']:+6.2f}°C "
        f"{state_icon} {d['state']:<8} "
        f"{comp} comp={'ON ' if d['compressor_on'] else 'OFF'} "
        f"lock={d['lockout_s']:>3}s "
        f"{door}"
        f"{power_icon} bat={d['battery_pct']:>5.1f}% "
        f"budget={d['heat_budget_minutes']:>5.1f}min"
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def build_sims(n_fridges: int, scenario: str) -> list[FridgeSim]:
    sims = []
    for i in range(n_fridges):
        dev_id = f"sim-fridge-{i+1:02d}"
        secret = stable_secret(dev_id)
        # Stagger starting temps so they're not all in sync
        sim = FridgeSim(
            device_id=dev_id,
            secret=secret,
            scenario=scenario,
            temp_c=random.uniform(3.5, 6.0),
            battery_pct=random.uniform(80.0, 100.0),
            seq=random.randint(0, 999),
        )
        sims.append(sim)
    return sims


def run(args: argparse.Namespace):
    # Build API base URL — prefer HTTP for IP-only hosts (no valid TLS cert)
    if args.host.startswith("http"):
        api_base = args.host
    elif args.api_http:
        api_base = f"http://{args.host}"
    else:
        api_base = f"https://{args.host}"

    # Suppress urllib3 InsecureRequestWarning for self-signed certs
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Fix Windows console Unicode encoding
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    log.info("=" * 70)
    log.info("  ColdChain Simulation Seed -- %d fridge(s)  scenario=%s",
             args.fridges, args.scenario)
    log.info("  MQTT  -> %s:%d (user=%s)", args.host, args.mqtt_port, args.mqtt_user)
    log.info("  API   -> %s", api_base)
    log.info("  Interval: %.1f s   |   Press Ctrl+C to stop", args.interval)
    log.info("=" * 70)

    # Build simulators
    sims = build_sims(args.fridges, args.scenario)

    # Register devices via API
    log.info("Registering devices via API …")
    for sim in sims:
        ok = ensure_device(api_base, sim.device_id, sim.secret,
                           username=args.api_user, password=args.api_pass)
        if not ok:
            log.warning("  Could not auto-register %s — check if it's already in DB", sim.device_id)
        time.sleep(0.3)

    # Connect MQTT
    publisher = SimPublisher(
        host=args.host,
        port=args.mqtt_port,
        username=args.mqtt_user,
        password=args.mqtt_pass,
    )
    publisher.connect()

    # Warmup info
    log.info("")
    log.info("Starting telemetry loop — Ctrl+C to stop")
    log.info("-" * 70)

    tick_num = 0
    last_print_time = 0.0

    try:
        while True:
            loop_start = time.time()
            tick_num += 1

            print_header = (tick_num == 1) or (loop_start - last_print_time >= 30)
            if print_header:
                ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                print(f"\n{'=' * 70}")
                print(f"  Tick #{tick_num}  |  {ts_str}")
                print(f"{'=' * 70}")
                last_print_time = loop_start

            published = 0
            for sim in sims:
                d = sim.tick(args.interval)
                ok = publisher.publish(sim.device_id, sim.secret, sim.seq, d)
                if ok:
                    published += 1
                    print(status_line(sim, d))
                else:
                    log.warning("  PUBLISH FAILED for %s (MQTT not connected?)", sim.device_id)

            if published < len(sims):
                log.warning("  ⚠  Only %d/%d readings published", published, len(sims))

            # Sleep exactly `interval` seconds accounting for processing time
            elapsed = time.time() - loop_start
            sleep_s = max(0.0, args.interval - elapsed)
            time.sleep(sleep_s)

    except KeyboardInterrupt:
        log.info("")
        log.info("🛑  Stopped by user (Ctrl+C).")
    finally:
        publisher.disconnect()
        log.info("MQTT disconnected. Goodbye!")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ColdChain live simulation seed — sends MQTT telemetry every 5 s.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host",       default="100.108.219.54",  help="MQTT broker / API host")
    p.add_argument("--mqtt-port",  type=int, default=1883,    help="MQTT broker port")
    p.add_argument("--mqtt-user",  default="collector",       help="MQTT username")
    p.add_argument("--mqtt-pass",  default="ColdChainMQTT2024", help="MQTT password")
    p.add_argument("--api-user",   default="admin",           help="API username for device registration")
    p.add_argument("--api-pass",   default="admin123",        help="API password for device registration")
    p.add_argument("--fridges",    type=int, default=1,       help="Number of simulated fridges")
    p.add_argument("--interval",   type=float, default=5.0,   help="Publish interval in seconds")
    p.add_argument(
        "--scenario",
        default="normal",
        choices=["normal", "door_stuck", "breach", "power_fail", "cycle"],
        help=(
            "Simulation scenario:\n"
            "  normal     — steady cold, occasional short door opens\n"
            "  door_stuck — door held open 90 s every 5 min (triggers alarm)\n"
            "  breach     — compressor disabled, temp climbs to room temp\n"
            "  power_fail — mains lost after 10 ticks, battery drains\n"
            "  cycle      — rotates through all scenarios every 2 min"
        ),
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args)
