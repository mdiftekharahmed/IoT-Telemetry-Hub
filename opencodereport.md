# Parameter Usage & Relocation Report — IoT-Telemetry-Hub

Generated: 2026-11-04 · Scope: firmware (`.ino`), ingest pipeline, budget engine, ML modules, API, React frontend

---

## 1. Parameter Usage Report

### Legend

| Column | Meaning |
|---|---|
| **Registry** | Registered in `app/parameters_seed.py` → seeded into the `parameters` table (`is_permanent=True`, cannot be deleted/disabled — the "locked" status in the admin UI) |
| **FW** | Published by `firmware/coldchain/coldchain.ino` telemetry payload |
| **Ingest** | Accepted into the `readings` table via `app/cc_ingestion.py` `ALLOWED_DATA_FIELDS` |
| **API** | Returned by `_reading_dict()` / CSV export in `app/api.py` |
| **UI** | Rendered somewhere in `frontend/src` |
| **Logic** | Consumed by alerts, ML, budget engine, or FSM logic |

### The 18 parameters

| Key | Registry | FW | Ingest | API | UI | Logic | Verdict |
|---|---|---|---|---|---|---|---|
| `battery_pct` | ✅ | ✅ | ✅ | ✅ | ✅ FridgeCard (battery runtime estimate), FridgeDetailPage, TelemetryPage | — | **Fully wired** |
| `battery_v` | ✅ | ✅ | ✅ | ✅ | ❌ (declared in `types.ts:21` only) | — | ⚠️ **Stored but never shown** |
| `compressor_on` | ✅ | ✅ | ✅ | ✅ | ✅ FridgeCard, FridgeDetailPage, TelemetryPage | ✅ forecast features (`duty_30m`, `since_switch` in `app/ml/forecast.py:35-38`), health scoring | **Fully wired** |
| `device_power_status` | ✅ | ❌ | ❌ | ❌ | ❌ (only a "Node Power" badge in AdminPage:713) | — | 🔴 **Dead — registered only, no data ever flows** |
| `door_open` | ✅ | ✅ | ✅ | ✅ | ✅ all pages | ✅ door alarm alerts (`app/mqtt_worker.py:202`), relocation candidate filter, forecast feature | **Fully wired** |
| `door_open_s` | ✅ | ✅ | ✅ | ✅ | ✅ live-ticking timer in FridgeCard | ✅ door alarm threshold vs `door_alarm_s`, forecast feature | **Fully wired** |
| `heat_budget_minutes` | ✅ | ❌ | ❌ | ❌ | ❌ | ⚠️ see §2 | 🔴 **Dead as a telemetry key — the budget exists per-batch under different names** |
| `lockout_s` | ✅ | ✅ | ✅ | ✅ | ✅ FridgeDetailPage:114, TelemetryPage:234 | ✅ `SET_CONFIG` downlink (`app/thresholds.py:136`) | **Fully wired** |
| `mains_present` | ✅ | ✅ | ✅ | ✅ | ✅ FridgeCard, FridgeDetailPage, TelemetryPage | ✅ `power_fail` alert (`app/mqtt_worker.py:212`) | **Fully wired** |
| `node_mains_ok` | ✅ | ❌ | ❌ | ❌ | ❌ (AdminPage badge only) | — | 🔴 **Dead** |
| `node_power` | ✅ | ❌ | ❌ | ❌ | ❌ (AdminPage badge only) | — | 🔴 **Dead** |
| `power_source` | ✅ | ✅ (alias `"MAINS"/"BATTERY"`, `coldchain.ino:713`) | ✅ | ✅ | ⚠️ `types.ts` only; UI shows `mains_present` instead | — | ⚠️ **Stored, never directly rendered** |
| `red_latched` | ✅ | ✅ | ✅ | ✅ | ⚠️ `types.ts` only | ✅ `LATCH_RED`/`RESET_RED` downlink commands (`app/budget_engine.py:106,145`, `coldchain.ino:650-655`), drives firmware `nodeState="DISCARD"` + red LED/buzzer | **Backend-strong, no direct UI render** |
| `sim_mode` | ✅ | ✅ (`SET_SIM` command) | ✅ | ✅ CSV export | ❌ | ✅ `SET_SIM` downlink, tests | ⚠️ **Wired but not displayed** |
| `state` | ✅ | ✅ (SAFE/WARNING/BREACH/DISCARD, `coldchain.ino:388-408`) | ✅ | ✅ | ✅ readings table in FridgeDetailPage | — | **Fully wired** |
| `temp_c` | ✅ | ✅ | ✅ | ✅ | ✅ everywhere | ✅ budget engine, forecast, health, breach alert, relocation filter | **Fully wired** (the core) |

> Note: `device_power_status` / `node_power` / `node_mains_ok` look like leftovers from an older naming scheme — their live equivalents are `power_source` + `mains_present`.

### Summary

- **14 of 18 parameters flow end-to-end** (firmware → HMAC ingest → DB → API → UI/logic).
- **4 are registry-only dead weights**: `heat_budget_minutes`, `device_power_status`, `node_power`, `node_mains_ok`. None of these is published by the firmware, none is in `ALLOWED_DATA_FIELDS` (`app/cc_ingestion.py:43-47`), none is in the `Reading` model — they only exist as rows in the `parameters` table and as the "Node Power" badge in the Admin page.
- `battery_v` is fully stored but never rendered anywhere in the UI (only `battery_pct` is).

---

## 2. `heat_budget_minutes` — Per-Batch Analysis

**Premise:** *"Remaining safe heat exposure budget minutes above 8°C threshold is related to each batch of vaccine; it may be different for different batches of vaccine in same fridge."*

**Verdict: correct — and the codebase agrees, just under different names.** The budget is 100% **per-batch, not per-fridge**.

### Where the budget actually lives

`app/models.py:140-161` — the budget lives on each `Batch` row:

```python
exposure_weighted_min: Mapped[float]   # accumulated weighted minutes
last_exposure_ts:      Mapped[datetime|None]
status:                Mapped[str]     # OK / AT_RISK / DISCARD
discard_latched:       Mapped[bool]

def remaining_pct(self) -> float:
    return max(0.0, 100.0 * (1.0 - self.exposure_weighted_min / 60.0))
```

`app/budget_engine.py:53-117` — after every accepted reading, `update_exposure()` loops over **all non-DISCARD batches in that fridge** and accumulates each one independently:

- Weight: `0` at ≤8°C, `1` at 8–12°C, `2` above 12°C (weights & thresholds from `config/system_thresholds.json`)
- `dt` is computed **per batch** from `batch.last_exposure_ts`, capped at 2 min (`DT_CAP_MINUTES`)
- The key line: `for batch in batches: batch.exposure_weighted_min += added`

### Why two batches in the same fridge differ

1. They start accumulating from **different timestamps** (`last_exposure_ts = None` until their first reading), so their exposure history windows differ.
2. `exposure_weighted_min` **persists and travels with the batch** when it is moved fridge-to-fridge (`fridge_id` is just reassigned, budget keeps counting against the new fridge's temperature).
3. Different batches may have lived through different excursions at different times.

So there is genuinely no single "fridge budget" — exposing `heat_budget_minutes` as a flat system telemetry parameter is conceptually wrong.

### Gaps found

1. 🔴 The `heat_budget_minutes` parameter key itself is **dead** — firmware never sends it, backend never publishes it. The "remaining budget" users actually see is `batch.remaining_pct` (Inventory page, FridgeCard, QR public page, budget alerts). Either delete the key or rewire it.
2. ⚠️ **Hardcode inconsistency:** `Batch.remaining_pct` (`app/models.py:161`) divides by a hardcoded `60.0`, while `budget_engine.py:92` uses the configurable `th["budget_total_minutes"]`. If an admin changes the total budget in the thresholds file, the engine recomputes with the new value but the API/UI still divides by 60. Same hardcoded `60` in `frontend/src/components/BudgetBar.tsx:10`.
3. ⚠️ The budget model (60 weighted min, 8/12°C weights) is **global** — there is **no per-vaccine-type budget**. If different vaccine categories (e.g., OPV vs HPV) need different budgets or different threshold temps, that requires a schema change (a per-batch or per-vaccine `budget_total` column) — currently not supported.

### Status transition ladder (per batch)

| Remaining budget | Batch status | Side effects |
|---|---|---|
| > 20% | `OK` | — |
| < 20% | `AT_RISK` | audit `BATCH_AT_RISK`, Telegram `at_risk` alert |
| 0% (60 weighted min used) | `DISCARD` | **latched**, audit `BATCH_DISCARD`, downlink `LATCH_RED` → red LED/buzzer on device; unwritable until admin reset (`POST /api/batches/{id}/reset`, admin-only, clears latch, downlinks `RESET_RED`) |

---

## 3. How Vaccine Relocation Works

### Designed flow: semi-automatic (suggestion → human confirmation)

It is **suggestion → human confirmation**, *not* fully automatic. Reading `app/ml/relocation.py`:

**Trigger conditions** (evaluated in `check_and_trigger_relocation()`, `relocation.py:217-221`): after a reading arrives, the system runs the 30-min ML forecast (`breach_predicted`) and the compressor health scorer, and acts when **either** condition holds:

- forecast predicts a breach above 8.0°C within 30 min, **OR**
- compressor health score < 40

> ⚠️ The docs (`docs/ML_EVALUATION_REPORT.md:284`, `USER_MANUAL.md`) describe this as an AND/dual gate; the code implements **OR** (`if not breach_predicted and not health_low: return None`). One of the two should be fixed.

**Batch ranking** (`relocation.py:68-72`): most exposed first (`lowest remaining_pct`) → nearest expiry → largest quantity.

**Target fridge filter** (`relocation.py:75-88`): candidate must be
- not the trigger fridge,
- have free capacity slots,
- latest reading **2–8°C**,
- door **closed**.

> Note: does **not** check `mains_present` on the target.

**What happens automatically:** a `RelocationSuggestion` row is saved with `plan_json` (status `pending`), audit entry `RELOCATION_SUGGESTED`, Telegram/SSE alerts fired (🔮 predicted breach / 🔧 health low). **Nothing physically moves at this point — by design.**

**Human step:** pharmacist/admin opens the **AI Insights page** → "AI Autonomous Relocation Plan" card → clicks **"✓ 1-Click Execute Relocation"** → `POST /api/ml/relocation/{id}/confirm` (`app/api.py:1063`) → `confirm_suggestion()` (`relocation.py:134-170`) moves every batch in one transaction, writes `BatchMovement` rows with `reason="ai_suggestion"`, marks the suggestion `confirmed`, writes audit `RELOCATION_CONFIRMED`.

**Fully manual options that also exist:**
- `POST /api/batches/{id}/move` (Pharmacist/Admin, `app/api.py:833`)
- `PATCH /api/batches/{id}` (`app/api.py:824`)

### 🔴 Reality check: the automatic trigger is not wired up

Repo-wide grep result: **`check_and_trigger_relocation()` is never called by anything.** Its docstring says *"Called from the ingest pipeline after each accepted reading"* — but `app/cc_ingestion.py` and `app/mqtt_worker.py` never invoke it. It appears only in its own definition.

Consequences in the current codebase:

- **No relocation suggestion will ever be generated automatically in production.** `build_suggestion()` is only called from `tests/test_ml.py:165`.
- The AI Insights relocation card will always show "Chamber conditions stable / No batch evacuations necessary" — not because things are fine, but because nothing creates pending suggestions.
- Relocation is effectively **manual-only today**: the manual move endpoint, plus the confirm endpoint (which would work *if* a suggestion existed).

**Answer to "does it work automatically?":** by design it's auto-suggest + one-click human confirm (the system never auto-moves batches — sensible for cold chain, since a wrong model call shouldn't physically evacuate a fridge), **but the auto-suggest half is currently orphaned code.** Fix is a small hook: call `check_and_trigger_relocation(db, device.fridge_id)` after `update_exposure(...)` in `app/cc_ingestion.py:206-210`.

### Other issues noticed

- ⚠️ `PATCH /api/batches/{batch_id}` (`app/api.py:824-831`) can change `fridge_id` **without** writing a `BatchMovement` row or audit entry — bypasses the movement audit trail.
- ⚠️ `_free_slots()` (`app/ml/relocation.py:25-36`) has a dead first query (unused variable `used`).
- ⚠️ Docs/code mismatch on the trigger gate (OR in code, AND in docs) — see §3 designed flow.

---

## 4. Recommended Fixes (priority order)

| # | Fix | Where |
|---|---|---|
| 1 | Wire the orphaned relocation trigger: call `check_and_trigger_relocation()` after each accepted telemetry | `app/cc_ingestion.py` (telemetry + sync handlers) |
| 2 | Remove or rename the 3 dead "Node Power" parameters (`device_power_status`, `node_power`, `node_mains_ok`) — or implement them for real | `app/parameters_seed.py`, firmware |
| 3 | Make `heat_budget_minutes` real or delete it — e.g., publish per-batch `remaining_pct` in the dashboard payload instead of a fake flat telemetry key | `app/parameters_seed.py` |
| 4 | Unify the budget denominator: `Batch.remaining_pct` should use the configured `budget_total_minutes`, not hardcoded `60`; same for `BudgetBar.tsx` | `app/models.py`, `frontend/src/components/BudgetBar.tsx` |
| 5 | Add `BatchMovement` + audit on `PATCH /api/batches/{id}` fridge_id changes | `app/api.py` |
| 6 | Align docs with code on the relocation trigger gate (OR vs AND) | `docs/ML_EVALUATION_REPORT.md`, `USER_MANUAL.md` |
| 7 | Render `battery_v` and `sim_mode` in the UI, or drop them from the Reading surface | `frontend/src` |
| 8 | Consider per-vaccine-type budgets/thresholds for heat exposure (schema change) | `app/models.py` (Batch), `app/budget_engine.py` |
