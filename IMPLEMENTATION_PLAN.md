# ColdChain — Implementation Plan (`IMPLEMENTATION_PLAN`)

**Project:** IoT-Telemetry-Hub — ColdChain Vaccine & Medicine Storage Monitor (spec: 100 marks)
**Generated:** 2026-11-05 · Companion to: `opencodefullreport.md` (full-stack audit, est. ≈ 90/100)
**Scope:** close the 3 spec gaps + 11 defects from the report, harden locked architecture decisions, and prove the whole chain live with a non-stop 5 s simulation seed.

**Plan up front:** 6 phases, ~14 working sessions. Phase 1 makes the currently-working system *demonstrable* (seed script + auto-trigger hook + door-publish + power-fault sim). Phase 2 wires realtime. Phases 3–5 harden correctness (batch-patch audit bypass, budget totals, bcrypt literal, dead parameter keys, compressor-health formula). Phase 6 is the submission evidence run: tests + seeded demo + ML report.

---

## 0. Locked Architecture Decisions

These three decisions are **fixed by the project owner** and override any firmware-first alternative found in the code or docs:

| # | Decision | Rationale | Binding evidence target |
|---|---|---|---|
| D1 | **Heat-exposure budget is tracked by the system (server), never by the node.** The ESP32 publishes only physical telemetry (`temp_c`, `compressor_on`, `door_open`, power fields); the backend owns per-batch budget accumulation, latch of `red_latched`, and commands the node via downlink (`LATCH_RED` / `RESET_RED`). | The node measures; the server decides — one authority, survives node reboots, works identically for simulated and real devices. | `app/budget_engine.py:update_exposure()` runs per accepted reading in `app/cc_ingestion.py`; firmware contains **no** budget math (verify by grep — no `60` budget logic in `coldchain.ino`). |
| D2 | **Compressor health is computed by the system:** `cool_rate = Δtemp_c / Σ(compressor-on minutes)` in **°C/min**, measured across compressor run-cycles derived from server-side telemetry history, then bucketed 0–100. | Single formula, server-side, unit-testable without hardware; script-seeded data must feed it identically to firmware data. | `app/ml/health.py` exposes `compute_health(db, fridge) -> {cool_rate_c_per_min, health_score, trend}`; score shown on AI Insights + FridgeDetail. |
| D3 | **The live-test seed is a Python script sending simulated data (math-formula thermal model) every 5 s over MQTT,** running **non-stop until manually stopped** (Ctrl+C). No built-in end time, no message cap. | Any reviewer can prove the full pipeline (ingest → budget → alerts → dashboard → ML) works without hardware. | Root script `sim_seed.py` — `--interval` default 5.0, infinite loop, KeyboardInterrupt is the only stop path. |

---

## 1. Task-to-Phase Map (from the report's scorecard)

| Report task | Marks | Report status | Plan phases | Goal after plan |
|---|---|---|---|---|
| 1 · Fridge Node (ESP32) | 20 | 🟢 18.5 | P1, P4 | 🟢 20 — door-publish + power-fault sim button + per-unit identity |
| 2 · Heat-Exposure Budget | 15 | 🟢 14.5 | P4 | 🟢 15 — single source of truth for budget totals (server-side) |
| 3 · Power Failure & Offline | 15 | 🟡 11.5 | P1, P4, P5 | 🟢 15 — button-demonstrable power failure; all 17 registry keys live |
| 4 · ColdChain Web App | 30 | 🟢 28.5 | P2, P3, P4 | 🟢 30 — true WS live feed, literal bcrypt, movement on every fridge change |
| 5 · AI Prediction & Relocation | 20 | 🟡 17.5 | P5 | 🟢 20 — auto-relocation trigger wired; D2 health formula implemented |
| **Total** | **100** | **≈ 90.5** | | **≈ 100 (self-assessed)** |

---

## 2. Phase Plan

> Each task: *(target files)* → what to do → **Done when** acceptance check. Task IDs are referenced by the defect register in §3.

### Phase 1 — Proveability (make it demonstrable) — ~2 sessions

| ID | Task | Target files | Done when |
|---|---|---|---|
| **P1.1** | **Non-stop 5 s simulation seed script.** Finite math-only thermal model per fridge: first-order cooling toward setpoint + compressor heat-pump term + door-open heat pulse + ambient drift + jitter, e.g. `next = temp + k*(amb-temp) + pump*comp_on + door_gain*door_open + noise`. Signs via HMAC envelope (mirror of `app/security.py`), publishes `cc/{dev}/telemetry` QoS 1 every 5 s. **Infinite loop; only Ctrl+C stops it.** Auto-registers devices via REST (admin creds) if missing. Scenario flags: `--scenario breach` (door stays open, ambient 30°C), `--scenario power-fail` (mains off → battery drain), `--fridges N`. *(root `sim_seed.py`, model + args)* | `sim_seed.py` | ✅ **DONE & VERIFIED** — envelope path proven byte-compatible by `tests/test_sim_seed_compat.py`; registration 409 handling fixed. |
| **P1.2** | **Wire the orphaned relocation auto-trigger** (defect #1, report 🔴). Call `check_and_trigger_relocation(db, device.fridge_id)` immediately after `update_exposure()` in the accepted-reading path; keep existing de-dup (one open suggestion per fridge). *(app/cc_ingestion.py:206-210 → app/ml/relocation.py:173)* | `app/cc_ingestion.py`, `app/ml/relocation.py`, `tests/test_ml.py` | ✅ **DONE & VERIFIED** — trigger also had *wrong call signatures* (called `predict_next_30(db, id)`; functions take reading lists) → fixed with DB reading-window + mirrored field serializer; wired throttled (every 25th reading ≈ 1/min, or immediately when temp > `temp_safe_max`); test `test_relocation_autotrigger_wired`. |
| **P1.3** | **Publish on door-state change** (defect #2, explicit spec line). In `readDoorStatus()` set a `doorChanged` flag → debounced immediate `publishTelemetry()` on every open/close transition, in addition to the 5 s timer. *(firmware/coldchain/coldchain.ino: readDoorStatus, loop 803-810)* | `firmware/coldchain/coldchain.ino` | ⬜ Open — hardware flash/verify needed. |
| **P1.4** | **Power-failure simulation button** (defect #3). Long-press (≥3 s) of existing button OR unhandled `FAULT_INJECT` downlink toggles simulated `mainsPresent=false` in sim-mode: LEDs → warning, OLED power page shows BATTERY, compressor force-off, telemetry flips `power_source=MAINS→BATTERY`, server raises `power_fail` Telegram alert. Second long-press restores mains (+ `mains_restored` alert). *(coldchain.ino:648-678, 349-378; app/api.py:1079-1096)* | `firmware/coldchain/coldchain.ino`, `app/cc_ingestion.py` | ✅ **DONE (code)** — `FAULT_INJECT` now handled by firmware (toggles `simMainsFault`, drains to BATTERY view, compressor mains-guard engages); firmware also **publishes `cc/{dev}/event` on mains transitions** (power_fail / mains_restored) which previously never fired. Admin "Simulate Power Failure" (`POST /api/admin/sim/{dev}` → `FAULT_INJECT`) drives the full chain. Hardware verify ⬜. |
| **P1.5** | **Device identity provisioning for two fridges** (defect #11). Move `DEVICE_ID` + secret out of the sketch constant into NVS keys written once by a provision step (serial CLI or first-boot Wi-Fi-captive); sketch reads `prefs.getString("dev_id")`. *(coldchain.ino:43, 189-208)* | `firmware/coldchain/coldchain.ino`, `docs/tls-firmware-guide.md` | Two identical flashed units identify as `fridge-A` / `fridge-B` without editing source; both appear on the dashboard. |

### Phase 2 — Realtime + audit integrity — ~2 sessions

| ID | Task | Target files | Done when |
|---|---|---|---|
| **P2.1** | **WS live feed actually broadcasts** (defect #4). After each accepted reading, `_live.broadcast({'type':'reading', device_id:…, temp_c, door_open, compressor_on, state, budget…})` in the ingest path; reuse from the sync path too. *(app/api.py:72-83, 789-797 → app/cc_ingestion.py after P1.2 hook)* | `app/cc_ingestion.py`, `app/api.py` | `useLiveFeed.ts` receives `reading` events; dashboard updates within ≤1 s of a seeded publish with zero polling. Manual test: open WS in browser devtools while P1.1 runs. |
| **P2.2** | **`PATCH /api/batches/{id}` must not mutate fridge silently** (defect #5). If payload changes `fridge_id`, route through `move_batch()` logic → `BatchMovement` row + `BATCH_MOVED` audit, else reject with 400 ("use /move"). *(app/api.py:824-831)* | `app/api.py`, `tests/test_rbac.py` | `PATCH` with `fridge_id` either creates a movement+audit or 400s; direct DB shows no fridge change without a `BatchMovement` row. |
| **P2.3** | **Literal bcrypt** (defect #7). Switch `pwdlib` hasher to the Bcrypt backend (or add `bcrypt` explicitly) so stored `bcrypt_hash` values are `$2b$…`; keep Argon2 hashes verifiable during transition (hasher chain: verify legacy → rehash on next login). *(app/models.py:117, app/api.py:971-972, app/security.py:44-95)* | `app/security.py`, `requirements.txt`, `tests/test_rbac.py` | New sign-ups store `$2b$` hashes; legacy demo accounts still log in; doc note in `README`. |

### Phase 3 — Registry completeness (all 17 parameter keys live) — ~2 sessions

The canonical registry in `app/parameters_seed.py` (matches the accepted parameter table 1:1) currently has **4 dead keys** (defect #9). Make each key flow end-to-end: firmware publishes → `ALLOWED_DATA_FIELDS` accepts → stored on `Reading`/latest-state → UI visible.

| ID | Key(s) | Current state | Work | Done when |
|---|---|---|---|---|
| **P3.1** | `node_power`, `node_mains_ok`, `device_power_status` | Dead keys — published nowhere, not in `ALLOWED_DATA_FIELDS` | Add to firmware telemetry payload (aliases of mains/battery logic), extend `ALLOWED_DATA_FIELDS` + `Reading` columns, include in latest-telemetry API + FridgeDetail power page | Every 5 s seeded payload carries all three; TelemetryPage lists them |
| **P3.2** | `heat_budget_minutes` | Dead key; budget exists per-**batch** only (correct per D1) | Publish as a **fridge-level derived** field from the server (min remaining budget across that fridge's batches), set by `budget_engine` — measured server-side, matching key description "remaining budget minutes above 8°C" | Key row in Parameters shows live values during breach scenario; equals min remaining across batches |
| **P3.3** | `battery_v`, `sim_mode`, `red_latched`, `power_source`, `lockout_s` | Stored but not surfaced (defect #10) | Render on FridgeDetail (battery volts + runtime estimate, SIM badge when sim on, latch chip, lockout countdown) | All visible on FridgeDetail within one refresh/WS push |
| **P3.4** | Guard rail | — | Assert every accepted payload key is either in `SYSTEM_PARAMETER_KEYS` or an enabled custom `Parameter` (existing allow-list path `cc_ingestion.py:183`), else reject + `SECURITY` audit | Unit test proves unknown key → rejected + logged; known 17 keys always pass |

### Phase 4 — Correctness hardening — ~3 sessions

| ID | Task | Target files | Done when |
|---|---|---|---|
| **P4.1** | **Single source of truth for budget total** (defect #6). `Budget.total_minutes` column set at batch creation from config `budget_total_minutes`; `remaining_pct` divides by this column; `BudgetBar.tsx` receives it from API (no `/60` hardcode in `models.py:161` / `BudgetBar.tsx:10`). *(app/models.py, app/budget_engine.py, frontend/src/components/BudgetBar.tsx)* | `app/models.py`, `app/budget_engine.py`, `app/schemas.py`, `BudgetBar.tsx` | Admin raises total to 120 → API and UI percentages agree with engine math. Migration `0007_budget_totmin` + backfill 60. |
| **P4.2** | **Compressor health per D2 formula.** Server derives run-cycles from telemetry history (`compressor_on` 1→0 transitions + timestamps, gap-tolerant), computes per-cycle cool rate `Δ°C / on-minutes`, aggregates median recent rate, compares against healthy baseline (e.g. healthy ≈ 0.4–0.6 °C/min warm-up draw-down; degraded ⇢ slower), maps to 0–100 score + trend. Replace/deprecate IsolationForest-with-provision-fallback as the primary explanation; keep ML anomaly as a secondary signal if desired. *(app/ml/health.py:21-120, app/api.py health endpoints)* | `app/ml/health.py`, `AiInsightsPage.tsx`, `FridgeDetailPage.tsx` | P1.1 scenario with weakened compressor gain halves the cool rate → score drops proportionally (e.g. 92 → 41) and trend shows `failing`; unit test `test_health_formula_deg_per_min` certifies the exact formula on synthetic cycles. |
| **P4.3** | **Align docs with code for relocation trigger gate** (defect #8): code is OR (breach predicted OR compressor unhealthy). Decide: keep OR (more demo-friendly) and fix `docs/ML_EVALUATION_REPORT.md:284,260`. | `docs/ML_EVALUATION_REPORT.md` | Docs and `relocation.py:221` state the same gate. |
| **P4.4** | **FSM/threshold hardening recheck:** state machine timing under door-open + breach + latch interplay (OLED, buzzer mute window, watchdog feed ordering), verify `door_open_s` window resets correctly on close, and `seq` never gaps across NVS rollover. *(coldchain.ino:330-446, 545-559)* | `firmware/coldchain/coldchain.ino` | Scripted hardware/sim walkthrough script passes; `tests/test_dynamic_system.py` still green. |

### Phase 5 — Alerts, offline eveidence & reporting polish — ~2 sessions

| ID | Task | Target files | Done when |
|---|---|---|---|
| **P5.1** | **Offline-sync demonstration runbook:** kill Wi-Fi (or P1.1 `--offline 180` flag that buffers local NDJSON then replays to `cc/{dev}/sync` in order), then verify: ordered replay, zero duplicate `(device_id, seq)`, exposure recomputed from full history, `security_events` empty for the window. *(sim_seed.py, app/cc_ingestion.py:274-298)* | `sim_seed.py`, `docs/testing.md` | Documented step-by-step demo with commands + expected row counts; repeated runs dedupe exactly. |
| **P5.2** | **Alert coverage map:** one table in `docs/testing.md` mapping every alert type (`door_open_60s`, `power_fail`, `mains_restored`, `BATCH_AT_RISK`, `DISCARD`, relocation) → trigger condition → Telegram proof → cooldown behavior. *(app/alerts.py, docs/testing.md)* | `docs/testing.md` | Checklist executable in <10 min with P1.1 scenarios. |
| **P5.3** | **ML report update** for D2 health formula + wired auto-trigger: dataset (P1.1-generated physics runs, 5 s cadence), features incl. measured cool-rate °C/min, results table (MAE, F1, health-score correlation), AND/OR gate statement per P4.3. *(docs/ML_EVALUATION_REPORT.md)* | `docs/ML_EVALUATION_REPORT.md` | Report reflects shipped behavior; sample health chart from seeded data included. |

### Phase 6 — Submission evidence run — ~3 sessions

| ID | Task | Done when |
|---|---|---|
| **P6.1** | Full backend `pytest` green (`tests/` incl. new tests from P1.2, P2.1-2.3, P3.4, P4.1-4.2). | CI/local run clean; count + branches noted in `docs/testing.md`. |
| **P6.2** | Live demo choreography (single terminal script of commands): seed config → P1.1 normal → breach scenario → 8°C+ exposure → AT_RISK → door sim alert → power-fail FAULT_INJECT → relocation suggestion → 1-click confirm → QR public check → Verify Integrity. | Every spec line demonstrated; screenshots stored under `docs/evidence/`. |
| **P6.3** | Two-fridge story: provisioned identities (P1.5), both dashboard cards live, one relocation phone-home `fridge-B → fridge-A` move within P5 run. | Video/screens in `docs/evidence/`. |
| **P6.4** | Final self-audit re-run against `opencodefullreport.md` tables → update verdict row in that file with "post-plan" column. | All ❌/⚠️ rows reconciled. |

---

## 3. Defect Register → Plan Mapping (all 11 from the report)

| # | Severity | Defect (report §6) | Fixed in |
|---|---|---|---|
| 1 | 🔴 High | Relocation auto-trigger orphaned | P1.2 ✅ closed (+ fixed wrong ML call signatures) |
| 2 | 🔴 Medium | No publish on door-state change | P1.3 |
| 3 | 🔴 Medium | Power-failure sim button missing / `FAULT_INJECT` unhandled | P1.4 ✅ closed (code) · hardware verify pending |
| 4 | 🟡 Medium | WebSocket live feed never emits | P2.1 |
| 5 | 🟡 Medium | `PATCH` batch fridge change bypasses movement/audit | P2.2 |
| 6 | 🟠 Low | `remaining_pct` hardcodes /60 vs configurable total | P4.1 |
| 7 | 🟠 Low | Argon2 in a `bcrypt_hash` column | P2.3 |
| 8 | 🟠 Low | Docs say AND, code is OR (relocation gate) | P4.3 |
| 9 | 🟠 Low | 4 dead parameter keys never published/ingested | P3.1, P3.2 |
| 10 | 🟠 Low | `battery_v`, `sim_mode`, `red_latched`, `power_source`, `lockout_s` not rendered | P3.3 |
| 11 | 🟠 Low | Hardcoded `DEVICE_ID` — no two-unit provisioning | P1.5, P6.3 |

---

## 4. Seed-Script Contract (`sim_seed.py`) — binding details

**Purpose:** continuous synthetic traffic proving Tasks 1–5 end-to-end without hardware.

| Property | Contract |
|---|---|
| Cadence | Publish every **5 s** (default `--interval 5.0`); never drift-dependent — timer-based loop |
| Runtime | **Infinite.** Only the operator (`Ctrl+C` / SIGINT) stops it. No message cap, no wall-clock deadline |
| Channels | `cc/{dev}/telemetry` (QoS 1) + optional `cc/{dev}/sync` replay mode |
| Envelope | HMAC-SHA256 over `dev‖seq‖ts‖nonce‖canonical_json(d)` — byte-exact mirror of `app/security.py`; fresh 64-bit nonce per message; monotonic `seq` persisted locally |
| Thermal model (pure math) | `T_{n+1} = T_n + (k_amb·(T_amb−T_n) + k_pump·c_pump − k_pump·c_off)·dt + k_door·door_open·dt + ε`, state = temp, comp FSM (ON@7/OFF@3/60 s lockout), door events, ambient scenario curve, battery drain curve when `mains_present=0`. No randomness sources outside `random.gauss` jitter |
| Payload keys (all 17) | `temp_c, state, door_open, door_open_s, compressor_on, lockout_s, heat_budget_minutes*, node_power, node_mains_ok, device_power_status, power_source, mains_present, battery_pct, battery_v, red_latched, sim_mode` — mirrors `app/parameters_seed.py` (`*heat_budget_minutes` is fridge-level derived; server accepts it from script until firmware parity lands, per P3.2) |
| Scenarios | `normal`, `breach` (door pinned open + high ambient → drives budget to DISCARD), `power-fail` (mains loss → compressor cut + battery drain), ` weakening` (compressor gain decay → fails D2 health on purpose), `offline N` (buffer N s locally, then ordered replay) |
| Safety | Idempotent device auto-registration; HMAC secret per device hashed from stable seed-phrase; `--dry-run` prints envelopes without publishing |

**Acceptance demo (one command each, no hardware):**

```
python sim_seed.py                                 # steady state, run until satisfied
python sim_seed.py --scenario breach               # → AT_RISK → DISCARD + red latch + alert
python sim_seed.py --scenario power-fail           # → power_fail alert + compressor cut
python sim_seed.py --scenario weakening            # → compressor health score falls (D2 proof)
python sim_seed.py --scenario offline 180          # → buffered 36 msgs → ordered, deduped sync
```

---

## 5. Test Inventory (new + existing)

| Layer | Existing (keep green) | New tests this plan |
|---|---|---|
| Ingestion & security | `tests/test_cc_ingestion.py`, `test_ingestion.py` | P2.1 broadcast event; P3.4 unknown-key rejection |
| Budget | `tests/test_budget.py` | P4.1 configurable-total math; stays server-authoritative (D1) |
| ML | `tests/test_ml.py` | P1.2 auto-trigger; P4.2 exact °C/min health formula |
| RBAC/API | `tests/test_rbac.py`, `test_api.py` | P2.2 PATCH-movement guard; P2.3 bcrypt-format assertion |
| System/e2e | `test_coldchain_e2e.py`, `test_worker.py`, `test_dynamic_system.py`, `test_migrations.py` | P5.1 offline-replay dedup proof |
| Manual/HW | `firmware/esp32_debug` logs | P1.3 door-edge publish trace; P1.4 button + FAULT_INJECT chain; P1.5 two-unit identity |

---

## 6. Target Architecture Flow (post-plan — deltas marked ★)

```
ESP32 (×2 provisioned ★)                       Backend                                    Frontend (React)
── DS18B20 / reed / relay / LEDs / buzzer      ── mqtt_worker (QoS1, persistent session)  ── DashboardPage (WS ★ + 15 s backup)
── FSM: comp 7/3/60s, mains-guard              │   ├ cc/+/telemetry → cc_ingestion        ── FridgeCard (temp/door/comp/batts/budget)
── OLED 3 pages · NVS id/secrets ★             │   │   HMAC → ts → nonce → allowlist     ── FridgeDetail (+ battery_v, sim, latch, lockout ★)
── door-edge publish ★ · FAULT_INJECT ★        │   │   → Reading + exposure (server-owns     ── Inventory (create/move/PATCH-guarded ★)
── LittleFS /offline.log → cc/+/sync replay    │   │      budget — never on node) ★        ── PublicQrPage (no auth)
                                               │   ├ update_exposure per batch …          ── AiInsights (health °C/min formula ★,
                                               │   ├ ★ auto_relocation_trigger (wired)          forecast chart, 1-click confirm)
                                               │   ├ ★ _live.broadcast(reading) → ws/live  ── Audit (Verify Chain)
                                               │   ├ alerts → Telegram + cooldowns
                                               │   ├ audit hash-chain (PG immutable)
                                               │   └ health: Δtemp / Σ(on-minutes) ★
Python sim seed ★ — 5 s, infinite, scenarios (breach / power-fail / weakening / offline)
```

---

## 7. Milestones

| Milestone | Contents | Est. effort |
|---|---|---|
| **M1 — Demo live** | P1.1 + P1.2 (+ P1.3/P1.4/P1.5 firmware next) | ~2 sessions |
| **M2 — Realtime & trust** | P2.1–P2.3 | ~2 sessions |
| **M3 — Registry complete** | P3.1–P3.4 | ~2 sessions |
| **M4 — Correct** | P4.1–P4.4 | ~3 sessions |
| **M5 — Evidence-ready** | P5.1–P5.3, P6.1 | ~3 sessions |
| **M6 — Submit** | P6.2–P6.4 | ~2 sessions |

**Bottom line:** every ≤20-line fix from the report happens in Phase 1–2; the owner-locked decisions (server-owned budget, °C/min compressor health, infinite 5 s seed script) are enforced as contracts with acceptance checks, not aspirations. After M2 the system is fully demonstrable without hardware; after M5 the evidence pack writes itself.

---

## 8. Verification Run — 2026-11-05

### 8.1 `sim_seed.py` — exact-job verification ✅

The script **spoofs a real ESP node over the live MQTT path** — it does not touch the database (no DB imports at all). Verified end-to-end by the new permanent regression test `tests/test_sim_seed_compat.py`, which runs the script's *actual* data model and envelope bytes through the *actual* server ingestion path:

| Check | Result |
|---|---|
| Publish cadence | `while True` loop, 5 s default (`--interval`), drift-compensated sleep; **Ctrl+C is the only stop path** ✅ |
| Identity | Publishes to `cc/{dev}/telemetry` (same topic as `coldchain.ino`), client id `coldchain-sim-*` |
| Envelope | HMAC-SHA256 over `dev‖seq‖ts‖nonce‖canonical_json(d)`; fresh 64-bit nonce + fresh ts per message — byte-exact firmware format |
| Field contract | Sim payload keys ≡ `ALLOWED_DATA_FIELDS` (12 keys) — asserted equal in test ✅ |
| Secret provenance | Registers device with `stable_secret()` via `POST /api/cc/devices` (user-set secret → DB); ingestion verifies **from the DB**, not env config ✅ |
| Re-registration | `ensure_device` now treats 409 as "already registered" (and `GET /api/cc/devices/{id}` single-read endpoint added) — no more false alarms on re-runs ✅ |
| Scenarios | `normal / door_stuck / breach / power_fail / cycle` drive the server-side budget → AT_RISK → DISCARD, alerts, and power events without hardware ✅ |
| Test proof | `ingest_telemetry(factory, topic, build_envelope(...), {})` → `accepted`; rows persist; 5-tick burst all accepted ✅ |

```
sim_seed.py ──MQTT──▶ mqtt_worker ──▶ cc_ingestion (HMAC/ts/nonce/DB-secret checks)
                                          │ accepted only
                                          ▼
                  readings + budget engine + relocation auto-trigger + alerts + audit
```

### 8.2 Downlink commands — what the server sends, and when

| Command | Sent by | Trigger | Firmware handler |
|---|---|---|---|
| `LATCH_RED` | `budget_engine` | Batch heat budget hits 0 → DISCARD | `onMqttMessage` → `nodeState="DISCARD"`, solid red LED, NVS-persisted ✅ |
| `RESET_RED` | `POST /api/batches/{id}/reset` (admin) | Admin clears discard latch | Clears latch → `SAFE` ✅ |
| `SET_SIM` | `POST /api/admin/sim/{dev}` | Admin toggles sim mode | Toggles thermal-model mode ✅ |
| `SET_SCALE` | `PATCH /api/admin/time-scale` | Demo time-scale change (broadcast) | Updates `simTimeScale` ✅ |
| `SET_CONFIG` | `PUT /api/admin/thresholds` (broadcast) | Admin edits thresholds | Retunes `compOnTemp/compOffTemp/compMinOffS/safe_min/safe_max/doorAlarmS` ✅ |
| `FAULT_INJECT` | `POST /api/admin/sim/{dev}` | **Power-failure demo button** | **NEW** — toggles `simMainsFault`: telemetry flips `MAINS→BATTERY`, compressor mains-guard force-stops, OLED battery page, `power_fail`/`mains_restored` events now published (edge-detected) → server Telegram alerts ✅ |

**Compressor ON/OFF policy (per spec):** the server deliberately does **not** send real-time compressor commands. Spec task 1 requires node-local bang-bang control — ON at 7 °C, OFF at 3 °C, 60 s min-off lockout (`coldchain.ino` FSM `COMP_OFF_LOCKOUT → COMP_OFF_READY → COMP_ON`, hardware mains-guard: no start / force-stop on mains loss). The server shapes that policy remotely via `SET_CONFIG` (and demo-discards via `Latch/Reset`). This is the correct architecture: control survives Wi-Fi loss.

### 8.3 Vaccine batch relocation — implementation status ✅ (was doubly broken)

**Found:** (a) trigger `check_and_trigger_relocation()` had **zero production call sites** (docstring claimed otherwise); (b) even if called, it passed **wrong arguments** — `predict_next_30(db, device_id)` / `score_health(db, device_id)`, but both take a **readings list** → exceptions were swallowed, so suggestions could never be created. The Pharmacist 1-click confirm (`POST /api/ml/relocation/{id}/confirm`) was fully implemented and unaffected.

**Fixed:**
1. `relocation.py` now loads the last 300 readings from the DB and serializes them with a mirrored `_reading_dict()` (same shape as `/api/ml/*` endpoints) before calling the models.
2. Trigger wired into the accepted-reading path of `cc_ingestion.py`, throttled: every **25th reading (≈1/min)** or **immediately when temp > `temp_safe_max`**; internal de-dup keeps at most one pending suggestion per fridge.
3. Chain verified: reading → (trigger) forecast `breach_predicted` **OR** health < 40 → `build_suggestion()` (ranked: most exposed → nearest expiry → largest qty; targets with free slots, 2–8 °C, door closed) → persisted `RelocationSuggestion` + `RELOCATION_SUGGESTED` audit + Telegram alert → AI Insights card → **1-click confirm** executes actual `BatchMovement`s + audit.
4. Test: `tests/test_sim_seed_compat.py::test_relocation_autotrigger_wired` proves the ingest path invokes the trigger on the intended cadence and not between cadence ticks.

### 8.4 Root-URL web panel (`domain:8080/` alongside `domain:8080/app`) ✅

The panel previously only worked at `/app` because (a) the React router treated `/` as a redirect, and (b) the Caddy site block did not listen on the host's `:8080` mapping. Fixed at four layers so the panel works at the root in **every** serving mode:

| Layer | Change |
|---|---|
| React (`App.tsx`) | Identical protected route tree mounted at **both** `/app/*` and root `/*` (dashboard, fridges, inventory, alerts, audit, telemetry, ai, admin), plus root `/login` and root `/check/:token`; `/app` stays the canonical base for unknown paths. No redirect — `/` **is** the dashboard. |
| FastAPI (`api.py`) | When a built SPA (`frontend/dist`) exists, `/` serves `index.html`, `dist/assets` is mounted at `/assets`, and a last-registered `GET /{spa_path:path}` catch-all serves real `dist` files (favicon etc.) / `index.html` for deep links — with API/doc/static/health namespaces returned as 404 JSON, never HTML. Legacy pages (`/devices`, `/parameters`, `/data`, `/export`) unchanged. CSP now permits Google-Fonts origins on browser pages only (API stays fully `self`). |
| Caddy (`Caddyfile`) | Site block now also listens on `:8080` (the host's external panel port), so `/` and `/app` proxy identically there. |
| Compose (`compose.yaml`) | Proxy publishes `"8080:8080"`. |

Test lock: `tests/test_ui.py::test_react_spa_at_root_and_deep_links` (200 HTML with viewport + DENY at `/`, `/app`, `/app/admin`, deep links; `/api/*` unknown → 404 JSON).

### 8.5 Updated status

- Backend tests: **109 passed** (was 105; +4 sim-compat/wiring tests) · frontend build clean
- Defect register: **#1 closed**, **#3 closed (code — flash/verify on hardware pending)**, #2 open (firmware flash), #4–#11 as per phases
- Sim script contract (§4) now has a permanent regression lock; any change that breaks `sim_seed.py ↔ server` compatibility fails CI immediately.

