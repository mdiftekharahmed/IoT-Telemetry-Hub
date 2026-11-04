# ColdChain — Requirements Compliance Report (`opencodefullreport`)

**Project:** IoT-Telemetry-Hub — ColdChain Vaccine & Medicine Storage Monitor (spec: 100 marks)
**Generated:** 2026-11-04 · Scope: full stack audit — ESP32 firmware, MQTT ingest, budget engine, ML, FastAPI API, React SPA, tests, docs

**Verdict up front:** **~90 / 100 (estimated 88–92).** Every requirement is traceable to real code. 3 spec items have gaps worth fixing before submission: (1) the AI relocation **auto-trigger is orphaned code**, (2) **publish-on-door-change** is missing from firmware, (3) the **power-failure simulation button** is not implemented. Details below.

---

## 0. Executive Scorecard

| # | Task | Marks (est. weights) | Score | Status |
|---|---|---|---|---|
| 1 | Fridge Node (ESP32) | 20 | **18.5** | 🟢 near-complete — door-change publish missing |
| 2 | Heat-Exposure Budget | 15 | **14.5** | 🟢 complete — minor hardcode inconsistency |
| 3 | Power Failure & Offline Mode | 15 | **11.5** | 🟡 buffer + sync + alerts solid; power-fault sim button missing |
| 4 | ColdChain Web Application | 30 | **28.5** | 🟢 complete — WS feed not wired, minor auth-hasher deviation |
| 5 | AI Breach Prediction & Relocation | 20 | **17.5** | 🟡 models excellent; auto-suggestion pipeline orphaned |
| | **Total** | **100** | **≈ 90.5** | |

> Scores are an engineering self-assessment against the spec text, not official marks. Each line below is backed by a file:line reference.

---

## 1. Fridge Node — 18.5 / 20

### Espousal of requirements → evidence

| Requirement | Status | Evidence |
|---|---|---|
| ESP32 for two fridges | 🟢 | `firmware/coldchain/coldchain.ino` (one sketch per node identity); backend fleet supports N fridges; `scripts/seed_coldchain.py:58-88` seeds `fridge-A` + `fridge-B` devices/fridges. One binary hardcodes `DEVICE_ID="fridge-A"` (`coldchain.ino:43`) — a second unit needs a per-device flash (identity not NVS-provisioned). |
| Temperature sensor | 🟢 | DS18B20 on 1-Wire, non-blocking async (`coldchain.ino:62, 214-236, 307-324`); simulated thermal model fallback sim-mode (`:290-305`). |
| Door switch | 🟢 | Reed switch GPIO27, active-low pullup, 50 ms debounce, open-duration timer (`:256-284`). |
| Compressor relay | 🟢 | GPIO25 active-high relay driven by FSM, plus hardware-safe behavior: compressor **cannot start and force-stops on mains loss** (`:349-378`). |
| LEDs | 🟢 | Red (breach: blink / discard: solid latch), yellow (warning), green (safe) (`:412-435`). |
| OLED: temperature + Safe/Warning/Breach | 🟢 | SSD1306 128×64, 3 pages — Main (big temp, `STATE:`, compressor status, door timer), Power (mains/battery V/%), Network & buffer (`renderOLED`, `:468-543`). |
| MQTT every 5 seconds | 🟢 | `TELEMETRY_INTERVAL_MS = 5000` (`:89`), timer-driven publish in `loop()` (`:803-810`), QoS 1, HMAC envelope (`:690-750`). |
| **Publish on door-state change** | ❌ | Publish loop is timer-only; door transitions are sampled at the next 5 s tick. No edge-triggered publish anywhere in the sketch. **Gap — this requirement is written verbatim in the spec.** |
| Compressor: ON 7°C / OFF 3°C / 60 s min off | 🟢 | `compOnTemp=7.0`, `compOffTemp=3.0`, `compMinOffS=60` (`:82-84`); anti-short-cycle FSM `COMP_OFF_LOCKOUT → COMP_OFF_READY → COMP_ON` (`:330-381`), `lockout_s` reported to server. Bonus: thresholds are tunable live via admin `SET_CONFIG` downlink (`:665-678`, `app/thresholds.py:120-143`). |

**Other solid engineering:** NVS persistence of `seq`, `red_latched`, `sim_mode` (`:189-208`); hardware watchdog (`:767-769`); NTP time authority; offline→sync on reconnect.

**Fix (small):** in `readDoorStatus()`, set a `doorChanged` flag and trigger an immediate `publishTelemetry()` on transition (debounced), while keeping the 5 s cadence.

---

## 2. Heat-Exposure Budget — 14.5 / 15

The budget is computed **server-side, per batch** (the ESP32 node publishes physical telemetry; the backend owns the batch budget and commands the node's red latch — spec-compatible architecture).

| Requirement | Status | Evidence |
|---|---|---|
| Each batch has a 60-minute budget above 8°C | 🟢 | `app/models.py:140-161` — `Batch.exposure_weighted_min`, `last_exposure_ts`, `status`, `discard_latched`, `remaining_pct`; `app/budget_engine.py:53-117` `update_exposure()` runs **per batch** after every accepted reading. |
| Track exposure + remaining budget | 🟢 | Remaining % exposed via `GET /api/batches`, dashboard `FridgeCard` + `BudgetBar`, Inventory, FridgeDetail, public QR (`app/api.py:182-193`). Alerts on AT_RISK / DISCARD (`app/mqtt_worker.py:216-234`). |
| >12°C counts double | 🟢 | Weight ladder: 0 (≤8), 1 (8→12], 2 (>12) — `budget_engine.py:32-44`, config `config/system_thresholds.json` (`budget_threshold_temp=8`, `budget_double_temp=12`, `budget_total_minutes=60`, `budget_at_risk_pct=20`). Unit-tested: `tests/test_budget.py:14-22`. |
| Below 20%: At Risk | 🟢 | `budget_engine.py:108-114` → `status=AT_RISK`, audit `BATCH_AT_RISK`, Telegram alert. |
| At 0%: Discard + red LED ON until admin reset | 🟢 | `budget_engine.py:95-106` — `status=DISCARD`, `discard_latched`, audit, **downlink `LATCH_RED`** → firmware latches `nodeState="DISCARD"` (persists in NVS across reboots) with solid red LED (`coldchain.ino:388-391, 416-420, 650-655`). Admin-only reset `POST /api/batches/{id}/reset` → `reset_discard()` → downlink `RESET_RED` (`budget_engine.py:120-147`, `app/api.py:851-867`). |

**Gap ( minor):** `Batch.remaining_pct` in `models.py:161` divides by a hardcoded `60.0` while the engine uses the configurable `budget_total_minutes`; the frontend `BudgetBar.tsx:10` also hardcodes 60. If an admin raises the total budget, the API/UI math silently disagrees with the engine.
**Note:** exposure is tracked per cycle with `DT_CAP_MINUTES=2.0` to avoid inflating exposure across sync gaps; full-history recomputation on `cc/sync` (`budget_engine.py:150-173`) keeps occupancy accounting exact.

---

## 3. Power Failure & Offline Mode — 11.5 / 15

| Requirement | Status | Evidence |
|---|---|---|
| Report battery / power status | 🟢 | Mains optocoupler GPIO35, battery voltage divider GPIO34 → V + SoC (`coldchain.ino:238-254`); every 5 s telemetry carries `mains_present`, `power_source`, `battery_pct`, `battery_v`; OLED power page; backend alerts `power_fail` / `mains_restored` (`app/mqtt_worker.py:139-144, 212-215`). |
| Belt-and-braces power behavior | 🟢 | Compressor force-off / no-start on battery (`:349-378`); node `WARNING` state without mains (`:398-404`). |
| Buffer ≥30 min during Wi-Fi loss | 🟢 | `publishTelemetry()` else-branch appends the full HMAC envelope to LittleFS `/offline.log` (`:740-745, 571-578`); no size cap — at 5 s cadence, 30 min ≈ 360 envelopes ≈ 0.2 MB, comfortably within flash. |
| Sync in order, no duplicates | 🟢 | On reconnect the log is replayed in append (chronological) order to `cc/{dev}/sync` QoS 1, then deleted (`:616-631`); server sorts by `seq`, `UNIQUE(device_id, seq)` + nested savepoints reject dupes (`app/cc_ingestion.py:274-287`, `app/models.py:180-185`), and exposure is **recomputed from full history** (`cc_ingestion.py:289-298`). |
| Door >60 s → buzzer + alert | 🟢 | Firmware: pulsed buzzer on BREACH/DISCARD/door>60 s, button-mutable for 5 min (`:437-446, 545-559`); server: `door_open_60s` Telegram alert with per-type cooldown (`app/alerts.py:25-68`, `mqtt_worker.py:202-205`). |
| **Simulate power failure with a button** | ❌ | `PIN_BTN_PWR` (GPIO26) currently **silences the buzzer / toggles the OLED page** — it does not simulate mains loss, and there is no `FAULT_INJECT` handler in firmware (the admin endpoint `POST /api/admin/sim/{dev}` sends it, `app/api.py:1079-1096`, but firmware only handles `RESET_RED / LATCH_RED / SET_SIM / SET_SCALE`). Mains failure can only be demonstrated by hardware (driving GPIO35). **Gap.** |
| "SMS, Telegram, **or** email" | 🟢 | Telegram implemented (`app/alerts.py:56-68`, 3 retries); the spec's "or" is satisfied. No SMS/email adapters exist. |

**Fix (small):** map one long-press of the existing button (or the unhandled `FAULT_INJECT` command) to a simulated `mainsPresent=false` state in sim-mode — ~10 lines in firmware, and the whole demo chain (LED, OLED, battery page, server alert, compressor cut) becomes demonstrable.

---

## 4. ColdChain Web Application — 28.5 / 30

### 4.1 Auth & Roles (6/6 → −0.5 hasher = 5.5)

| Requirement | Status | Evidence |
|---|---|---|
| JWT | 🟢 | HS256 access (30 min) + refresh (7 d) tokens via `python-jose` (`app/security.py:44-95`); endpoints `/api/cc/auth/login`, `/api/cc/auth/refresh`, `/api/cc/me` (`app/api.py:299-341`); brute-force lockout after 10 failed logins (`api.py:308-320`). |
| bcrypt | ⚠️ | Hashing is `pwdlib.PasswordHash.recommended()` = **Argon2id**, stored in a column named `bcrypt_hash` (`app/models.py:117`, `app/api.py:971-972`). Stronger than bcrypt but **not literally bcrypt** — either switch the hasher to pwdlib's Bcrypt backend or rename the column/docs. |
| Admin / Pharmacist / Inspector | 🟢 | All 3 roles exist (`security.py:125-127`, `app/models.py:113`), seeded with demo accounts (`scripts/seed_coldchain.py:46-48`). |
| Permissions enforced **on the server** | 🟢 | `require_role()` FastAPI dependency injects and re-checks the live DB user on every request (`security.py:100-121`). GET endpoints → `AnyRole`; batch create/move/ack → `PharmOrAdmin`; resets/users/sim → `AdminOnly`; audit + security events → admin+inspector only. Verified by `tests/test_rbac.py`. |

### 4.2 Live Dashboard (6 → 5)

| Requirement | Status | Evidence |
|---|---|---|
| Temperature / door / power / compressor / heat-budget | 🟢 | `frontend/src/pages/DashboardPage.tsx` (fridge grid + At-Risk/Discard counters) + `FridgeCard.tsx`: temp gauge, live-ticking door timer, compressor on/off, mains/battery with runtime estimate, per-batch `BudgetBar` bars sorted by remaining budget. FridgeDetailPage adds lockout, history chart with compressor/door overlays. |
| Well-designed UI | 🟢 | Tailwind dark theme, consistent cards/badges (`badge-safe` etc.), animated temp gauge, mobile-responsive grid. |
| "Live" | ⚠️ | 15 s React-Query polling works today, but the WebSocket at `/api/ws/live` exists (`api.py:789-797`) and **nothing ever broadcasts a `reading` event to it** (`_live.broadcast()` has zero call sites, and `useLiveFeed.ts` listens for `type:'reading'`). Realtime push is dead code — polling is the actual mechanism. |

### 4.3 Inventory: manage batches + assign/move between fridges (6 → 5.5)

| Requirement | Status | Evidence |
|---|---|---|
| Manage vaccine batches | 🟢 | `POST /api/batches` (code, vaccine, qty, expiry, fridge assignment, auto QR token; PharmOrAdmin) `api.py:807-822`; listing/edit; discard reset (admin). |
| Move between fridges | 🟢 | Move modal in `InventoryPage.tsx:39, 160-170, 250-267` → `POST /api/batches/{id}/move` writes `BatchMovement` + audit `BATCH_MOVED` (`api.py:833-849`). Heat exposure **travels with the batch**.
| ⚠️ | `PATCH /api/batches/{id}` (`api.py:824-831`) can silently change `fridge_id` with **no `BatchMovement` row and no audit entry** — audit-trail bypass. |
| QR per batch | 🟢 | `qrcode.toDataURL` rendered in Inventory (`InventoryPage.tsx:5,14`). |

### 4.4 Public QR Check (4/4)

| Requirement | Status | Evidence |
|---|---|---|
| Show Safe / At Risk / Discard + expiry, no login | 🟢 | `GET /api/public/batch/{qr_token}` — **no auth dependency**, returns only non-sensitive fields (name, status, remaining %, expiry) (`api.py:870-882`); `PublicQrPage.tsx` renders Safe/At-Risk/**Discard** cards with shield/alert/skull icons, budget bar, expiry, "last checked". |

### 4.5 Device Security (5/5)

| Requirement | Status | Evidence |
|---|---|---|
| HMAC-SHA256 | 🟢 | Firmware: mbedTLS HMAC-SHA256 over `dev‖seq‖ts‖nonce‖canonical_json(d)` (`coldchain.ino:153-174, 720-736`); server: `hmac_verify` constant-time compare (`app/security.py:141-151`, `cc_ingestion.py:102-108`). 32-byte hex device secrets (`app/config.py:37-49`); secret minted at device registration (`api.py:384-409`). |
| Timestamp | 🟢 | ±`hmac_ts_window_s` (default 60 s ±) freshness check, `STALE_TS` rejection (`cc_ingestion.py:96-99`, config `:57`). |
| Nonce | 🟢 | 64-bit `esp_random()` nonce; per-device dedup table with 15-min purge (`cc_ingestion.py:111-120`). |
| Reject **and log** invalid / replayed | 🟢 | Ordered pipeline: allow-list → ts → HMAC → nonce; every rejection writes `security_events` row + hash-chained `SECURITY_*` audit entry (`cc_ingestion.py:64-73, 179-188`). Duplicate `(device_id, seq)` → dedup by DB uniqueness. Extras: JSON duplicate-key detection, top-level field allow-list, 32 KB payload cap, byte-exact canonical-JSON HMAC. |

### 4.6 Tamper-Evident Logs + Verify Integrity (3/3)

| Requirement | Status | Evidence |
|---|---|---|
| Hash chain | 🟢 | `hash_n = SHA256(prev_hash ‖ idx ‖ ts ‖ actor ‖ action ‖ payload)` with genesis block (`app/audit.py:30-84`); fork prevention via row lock; **PostgreSQL trigger blocks UPDATE/DELETE** on `audit_log` (`migrations/versions/0006_coldchain.py:150-164`). Appends cover all significant actions (discards, resets, moves, relocations, threshold changes, logins, security events). |
| Verify Integrity | 🟢 | `GET /api/audit/verify` recomputes the full chain → `{valid, checked, first_broken_idx}` (admin/inspector) (`api.py:936-939`); UI **"Verify Chain"** button shows intact/violation + first broken index (`AuditPage.tsx:26, 54-84`). |

---

## 5. AI Breach Prediction & Relocation — 17.5 / 20

| Requirement | Status | Evidence |
|---|---|---|
| Predict temp 30 min ahead; warn if >8°C | 🟢 | LightGBM (Ridge fallback) over 12 engineered features, cached `.pkl`; **dual-scenario** output: compressor-normal + compressor-off power-cut path, 11-point trajectory, `breach_predicted`, `breach_in_minutes` (`app/ml/forecast.py:133-230`); UI banner "⚠️ Breach Predicted / ✓ Safe Operational Band" + forecast chart (`AiInsightsPage.tsx:174-191`, `FridgeDetailPage.tsx:55-67`). |
| Compressor health 0–100 | 🟢 | Cycle extraction (cool rate, duty, duration) → IsolationForest vs healthy baseline + provision duty-only fallback; trend `good/watch/failing`; gauge on AI Insights + fridge detail (`app/ml/health.py:21-120`, `AiInsightsPage.tsx:19-34`). |
| Suggest which batches → which fridge | 🟢 | Ranker: most exposed → nearest expiry → largest qty; target filter: free slots, latest temp 2–8°C, door closed; greedy assignment; persisted `RelocationSuggestion` with plan JSON (`app/ml/relocation.py:50-131`). |
| Pharmacist one-click confirm | 🟢 | `POST /api/ml/relocation/{id}/confirm` executes all moves in one transaction, writes `BatchMovement(reason='ai_suggestion')` + `RELOCATION_CONFIRMED` audit; UI "✓ 1-Click Execute Relocation" (`api.py:1063-1074`, `relocation.py:134-170`, `AiInsightsPage.tsx:412-418`). |
| **⚠️ Orphaned auto-trigger** | ❌ | `check_and_trigger_relocation()` — the function that generates suggestions after each reading — is **never called by any production code** (only by its own docstring; `build_suggestion()` is invoked solely from `tests/test_ml.py:165`). In a real deployment the AI Insights relocation card always reads "Chamber conditions stable" because nothing creates pending suggestions. **Fix: call `check_and_trigger_relocation(db, device.fridge_id)` after `update_exposure()` in `cc_ingestion.py:206-210` (2-line hook + de-dup already built in).** |
| Short report (dataset, features, results) | 🟢 | `docs/ML_EVALUATION_REPORT.md`: dataset (200 physics-sim runs, 5 s cadence, 80/20 leak-free split), 12-feature matrix with rationale, results (LightGBM MAE 0.17 °C, F1 0.89 breach classification), verification checklist, model artifacts appendix. |

---

## 6. Known Defect Register (prioritized)

| # | Severity | Defect | Location | Suggested fix |
|---|---|---|---|---|
| 1 | 🔴 High | Relocation auto-trigger orphaned — suggestions never auto-created in production | `app/ml/relocation.py:173`, `app/cc_ingestion.py:206-210` | Call `check_and_trigger_relocation()` after `update_exposure()` |
| 2 | 🔴 Medium | No publish on door-state change (explicit spec line) | `coldchain.ino` (loop, `readDoorStatus`) | Edge-triggered `publishTelemetry()` on door transition |
| 3 | 🔴 Medium | Power-failure simulation button missing; `FAULT_INJECT` downlink unhandled | `coldchain.ino:648-678`, `app/api.py:1079-1096` | Sim-mode mains-fault toggle (button long-press or FAULT_INJECT) |
| 4 | 🟡 Medium | WebSocket live feed never emits events (dashboard silently poll-only) | `app/api.py:72-83, 789-797` | Broadcast `{'type':'reading', ...}` after accepted telemetry |
| 5 | 🟡 Medium | `PATCH /api/batches/{id}` changes fridge without movement record/audit | `app/api.py:824-831` | Route fridge changes through `move_batch` or add BatchMovement |
| 6 | 🟠 Low | `remaining_pct` hardcodes /60 vs configurable `budget_total_minutes` (also frontend `BudgetBar`) | `app/models.py:161`, `frontend/src/components/BudgetBar.tsx:10` | Pass budget total through, or store per-batch total |
| 7 | 🟠 Low | Password hashing is Argon2id in a `bcrypt_hash` column (spec says bcrypt) | `app/models.py:117`, `app/api.py:971` | Use pwdlib Bcrypt backend or rename column + docs |
| 8 | 🟠 Low | Docs say relocation trigger is an AND gate; code is OR | `docs/ML_EVALUATION_REPORT.md:284,260` vs `relocation.py:221` | Align one side |
| 9 | 🟠 Low | 4 dead parameter registry keys (`heat_budget_minutes`, `device_power_status`, `node_power`, `node_mains_ok`) never published/ingested | `app/parameters_seed.py:43-59` | Delete or implement (budget already exists per-batch) |
| 10 | 🟠 Low | `battery_v`, `sim_mode`, `red_latched`, `power_source` stored but not rendered in UI | `frontend/src` | Add to detail page / telemetry table if desired |
| 11 | 🟠 Low | One hardcoded `DEVICE_ID` — no per-unit provisioning for "two fridges" | `coldchain.ino:43` | Move identity/secrets to NVS or build-time macro |

---

## 7. Test & Evidence Inventory

| Test file | Covers |
|---|---|
| `tests/test_budget.py` | exposure weight ladder (0/1/2 at 8/12°C), 60-min accumulation → DISCARD latch, admin reset |
| `tests/test_cc_ingestion.py` | HMAC verify, ts window, nonce replay, seq dedup, allow-lists |
| `tests/test_rbac.py` | role matrix: admin / pharmacist / inspector across endpoints |
| `tests/test_ml.py` | forecast training/inference, health scoring, relocation suggestion → confirm → batch moved |
| `tests/test_coldchain_e2e.py`, `test_api.py`, `test_records.py`, `test_ingestion.py`, `test_worker.py`, `test_ui.py`, `test_dynamic_system.py`, `test_migrations.py`, `test_profiles.py` | end-to-end ingest, API surface, legacy pipeline, worker routing, dynamic thresholds, migrations |
| `docs/ML_EVALUATION_REPORT.md` | Task-5 "short report": dataset / features / results / checklist |
| `scripts/seed_coldchain.py` | 2 fridges, 2 devices, 5 batches (incl. AT_RISK & near-Discard), 3 users, 2 h readings, genesis audit |

**Run:** `pytest` (backend) · `python -m scripts.seed_coldchain` (demo seed) · flash `firmware/coldchain/coldchain.ino` per node.

---

## 8. Architecture Flow (as implemented)

```
ESP32 (×N)                                     Backend                                      Frontend (React)
── DS18B20 / reed / relay / LEDs / buzzer      ── mqtt_worker (QoS1, clean_session=False)    ── DashboardPage (poll 15 s)
── FSM: compressor 7/3/60s, mains-guard        │    ├ cc/+/telemetry → cc_ingestion          ── FridgeCard (temp/door/comp/batts/budget)
── OLED 3 pages · NVS latch & seq · watchdog   │    │   HMAC → ts → nonce → UNIQUE           ── FridgeDetail (chart, lockout, health)
── LittleFS /offline.log on Wi-Fi loss         │    │   → Reading.row + exposure per batch   ── Inventory (create/move/batches + QR PNG)
   └ reconnect: replay cc/+/sync (ordered)     │    ├ cc/+/sync → ordered dedup + recompute  ── PublicQrPage (/api/public, no auth)
   └ cmd ← cc/{dev}/cmd (LATCH/RESET_RED,      │    ├ alerts → Telegram (+ cooldowns)         ── AiInsights (forecast chart, health gauge,
     SET_SIM/SET_SCALE/SET_CONFIG)             │    ├ audit hash-chain (PG immutable)                              1-click relocation confirm)
                                               │    └ WS /api/ws/live (unused emissions)      ── Admin (thresholds→SET_CONFIG, params, users)
                                               ── FastAPI: JWT RBAC · budget engine ·
                                                          forecast LightGBM+Ridge · health IsoForest ·
                                                          relocation suggester (⚠ trigger unwired)
```

### Bottom line
The system is spec-complete end to end; the three named gaps (relocation auto-trigger hook, door-change publish, power-fault sim button) are all ≤20-line fixes and are the difference between a paper feature and a demonstrated one for the machine-breakage and door-change demo flows.
