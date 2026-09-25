# Testing Guide

Last updated: 25 September 2026

This document covers automated testing (pytest), manual browser testing, and
the local development login credentials.

---

## Local development credentials

The project has **two local SQLite databases**. Which one the server uses depends
on whether a `.env` file exists.

### Default (no `.env` file) — `telemetry.db`

When no `.env` file is present, `Settings` defaults to `sqlite:///./telemetry.db`.
This is the database the dev server uses out of the box.

| Detail | Value |
|---|---|
| **URL** | `http://localhost:8000` |
| **Login page** | `http://localhost:8000/login` |
| **Username** | `admin` |
| **Password** | `admin123admin123` |

### Optional — `demo.db` (pre-seeded data)

The repo includes a pre-seeded `demo.db` with devices, parameters, and 84
telemetry records. To use it, create a `.env` file:

```ini
DATABASE_URL=sqlite:///./demo.db
```

Then restart the server. The demo account credentials are:

| Field | Value |
|---|---|
| Username | `demo` |
| Password | `demo123demo123` |

### Starting the dev server

```powershell
# From the repo root (activate venv first if needed)
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### Resetting the demo password

```powershell
$env:DATABASE_URL = "sqlite:///./demo.db"
.venv\Scripts\python.exe -m app.cli demo --reset-password
```

### Applying migrations to demo.db

If the server returns errors after a schema change, run migrations:

```powershell
$env:DATABASE_URL = "sqlite:///./demo.db"
.venv\Scripts\python.exe -m alembic upgrade head
```

Check the current migration version:

```powershell
$env:DATABASE_URL = "sqlite:///./demo.db"
.venv\Scripts\python.exe -m alembic current
```

---

## Automated tests

### Stack

| Tool | Role |
|---|---|
| **pytest** | Test runner |
| **FastAPI `TestClient`** | In-process HTTP client (no real server needed) |
| **SQLite in `tmp_path`** | Isolated throwaway database per test session |
| **Alembic** | Migrations are run to `head` before each test DB is used |

### Running the suite

```powershell
# Full suite — from the repo root
.venv\Scripts\python.exe -m pytest tests/ -v

# One file
.venv\Scripts\python.exe -m pytest tests/test_records.py -v

# One test
.venv\Scripts\python.exe -m pytest tests/test_records.py::test_csv_excludes_system_temp -v

# Show full diffs on failure
.venv\Scripts\python.exe -m pytest tests/ -vv
```

**Current result: 63 passed, 0 failed** (SQLite, all platforms).

---

## Test fixtures (`tests/conftest.py`)

| Fixture | Scope | What it provides |
|---|---|---|
| `application` | function | Full FastAPI app, fresh SQLite DB at `head` migration, one `admin` user (password `test-password-123`) |
| `client` | function | `TestClient` wrapping `application` |
| `authenticated_client` | function | `client` already logged in as `admin`; `Authorization` header set |
| `seeded` | function | `authenticated_client` used, plus device `sensor-01` (name `Workshop`) and parameter `temperature` already registered; returns the session factory |

The test admin credentials used **only in the automated suite** are:

| Field | Value |
|---|---|
| Username | `admin` |
| Password | `test-password-123` |

These are never written to `demo.db`.

---

## Test files

### `tests/test_api.py` — API and authentication

| Test | What it checks |
|---|---|
| `test_auth_required` | All protected endpoints return 401 without a token (parametrized over 5 routes) |
| `test_login_expiration_and_logout` | Correct and incorrect passwords; token stored as hash; session expiry; logout clears cookie and DB row |
| `test_devices_and_capacity` | Register up to 10 devices; 11th rejected; duplicate ID rejected; edit name/enabled; 404 for unknown device |
| `test_invalid_devices` | Rejects bad IDs (`bad/topic`, `=formula`) and blank names |
| `test_parameter_conflict` | Duplicate parameter name returns 409 |
| `test_export_dates_pagination_and_empty_range` | CSV export with timezone-aware dates; pagination with `before_id`; header-only CSV for empty range |
| `test_invalid_export_dates` | Rejects naive timestamps; rejects equal start/end and reversed ranges |
| `test_health` | `/health/live` and `/health/ready` return 200 |

---

### `tests/test_ingestion.py` — MQTT ingestion pipeline

| Test | What it checks |
|---|---|
| `test_filters_and_deduplicates` | Unknown parameters filtered out; exact duplicate message (same UUID) silently skipped |
| `test_disabled_and_unknown_devices` | Unknown device ID rejected; disabled device rejected; no rows written |
| `test_disabled_parameters_and_empty_approved_set` | Disabled parameter skipped; re-enabling allows new messages; duplicate UUIDs still deduplicated |
| `test_invalid_values_do_not_write` (parametrized × 9) | Empty dict; string value; boolean; null; NaN; Infinity; array; overflow int; invalid param name — all raise `InvalidMessage` and write nothing |
| `test_malformed_payloads` (parametrized × 7) | Non-JSON; invalid UTF-8; JSON array; missing fields; oversized payload; invalid UUID; duplicate JSON key |
| `test_topic_and_timestamps` | Wrong topic suffix rejected; naive timestamp rejected; timezone-aware timestamp normalised to UTC |
| `test_parameter_removal_preserves_history` | Deleting a parameter stops new storage but leaves historical rows intact |
| `test_failed_commit_rolls_back_receipt_and_readings` | DB outage during flush rolls back both `IngestedMessage` and `Telemetry`; same UUID succeeds on retry |

---

### `tests/test_migrations.py` — Schema migrations

| Test | What it checks |
|---|---|
| `test_migrations_match_models_and_are_reversible` | `alembic check` passes (models match migrations); downgrade to `base` leaves only `alembic_version`; upgrade back to `head` restores all tables |
| `test_postgres_migration_sql_compiles` | Offline SQL generation for PostgreSQL compiles without error; output contains `TIMESTAMP WITH TIME ZONE` and `CREATE TABLE telemetry` |

---

### `tests/test_profiles.py` — User profile management

| Test | What it checks |
|---|---|
| `test_profile_requires_authentication` | `GET /api/profile` returns 401 without a session |
| `test_profile_details_are_separate_and_persist` | Read/write full name and email; whitespace trimmed; empty string clears field; `password_hash` never appears in response; persisted to `user_profiles` not `admins` |
| `test_profile_validation` | Invalid email format → 422; name > 120 chars → 422; unknown field (`username`) → 422 |
| `test_profile_cannot_read_or_change_another_account` | Logged-in admin only reads/writes their own profile; another account's data unchanged |
| `test_migration_creates_profiles_for_existing_accounts` | Downgrade to `0001`, upgrade to `head` → existing `admin` account gets an empty `user_profiles` row |

---

### `tests/test_records.py` — Transmission records, health, CSV exclusion

#### `/api/telemetry/records` matrix endpoint

| Test | What it checks |
|---|---|
| `test_records_endpoint_returns_matrix` | Response contains `columns`, `records`; `systemTemp` absent from `columns`; each row has `registry_id`, `device_id`, `device_name`, `timestamp`, `values`, `health` |
| `test_records_one_row_per_transmission` | Two separate ingest calls produce exactly two rows |
| `test_records_missing_parameter_absent_from_values` | Parameter not sent in a transmission has no key in that row's `values` dict |
| `test_records_pagination` | 15 records ingested; first page of 5 has `next_cursor`; second page IDs all less than the cursor |
| `test_records_health_rule_returned` | Response always includes `health_rule` with `parameter`, `min`, `max`, `unit` |

#### `device_health()` boundary tests

| Test | What it checks |
|---|---|
| `test_health_ok_within_range` | Values at and between `system_temp_min` and `system_temp_max` → `"ok"` |
| `test_health_not_ok_outside_range` | Values just outside either boundary → `"not_ok"` |
| `test_health_unknown_when_no_thresholds` | Both thresholds `None` → `"unknown"` even if `systemTemp` present |
| `test_health_unknown_when_no_system_temp` | Empty dict or dict without `systemTemp` → `"unknown"` |
| `test_health_with_only_min_threshold` | Only `SYSTEM_TEMP_MIN` set; values below → `"not_ok"`, above → `"ok"` |
| `test_health_with_only_max_threshold` | Only `SYSTEM_TEMP_MAX` set; values above → `"not_ok"`, below → `"ok"` |

#### `systemTemp` CSV exclusion

| Test | What it checks |
|---|---|
| `test_csv_excludes_system_temp` | Transmission with `temperature` + `systemTemp`; CSV has `temperature` row but no `systemTemp` row |
| `test_csv_only_system_temp_yields_header_only` | Only `systemTemp` ingested; export returns header row only |

---

### `tests/test_ui.py` — Browser session and page routing

| Test | What it checks |
|---|---|
| `test_browser_cookie_and_csrf` | Login sets `HttpOnly; SameSite=strict` cookie; write request without `X-Requested-With` header → 403; with header → 201; logout deletes cookie and DB session |
| `test_ui_pages_and_assets` | All six page routes return 200 HTML with `viewport` meta, `X-Frame-Options: DENY`, and CSP `script-src 'self'`; all five static assets (CSS, JS, icons, favicon) return 200 |
| `test_workspace_summary` | `/api/summary` returns correct counts for devices, enabled devices, parameters, enabled parameters, readings, records, and `last_received_at` |

---

### `tests/test_worker.py` — MQTT worker behaviour

| Test | What it checks |
|---|---|
| `test_worker_acknowledges_invalid_but_not_failed_transactions` | `InvalidMessage` → QoS ack sent (bad message safely discarded); `OperationalError` → ack NOT sent (message redelivered), `failed` event set |
| `test_worker_ignores_retained_messages` | Retained MQTT messages are acked without calling `ingest` |

---

## Manual browser checklist

Run through this after any UI change before committing.

### Authentication
- [ ] `/login` — correct credentials → redirected to `/data`
- [ ] `/login` — wrong password → error message shown, no redirect
- [ ] Session cookie is `HttpOnly` (not readable from JS console)
- [ ] Sign out → redirected to `/login`; back-button does not re-authenticate

### Stored data (`/data`)
- [ ] Matrix table renders: columns are Registry ID, Device, Timestamp, one column per active parameter, Device Health
- [ ] Transmissions with a missing parameter show `—` in that column
- [ ] Device Health badge shows **OK** (green), **Not OK** (red), or **Unknown** (grey)
- [ ] Hovering the health badge shows the raw `systemTemp` value in the tooltip
- [ ] Pagination: Next / Previous navigate correctly; Previous disabled on first page
- [ ] Refresh button reloads from page 1
- [ ] Table scrolls horizontally on narrow screens (mobile); rest of layout stays put
- [ ] Empty state shown when no transmissions exist

### Devices (`/devices`)
- [ ] Add device — form validates ID and name; new row appears
- [ ] Enable / disable toggle updates immediately
- [ ] Edit device name saves correctly
- [ ] Capacity badge updates; Add button disabled at 10 devices

### Allowed parameters (`/parameters`)
- [ ] Add parameter — name validated (letter-first, alphanum+underscore)
- [ ] Enable / disable toggle works
- [ ] Remove parameter — confirmation dialog; row removed; historical data intact

### CSV export (`/export`)
- [ ] Quick-select buttons (24 h, 7 d, 30 d) populate fields
- [ ] Download triggers file save; filename is `telemetry.csv`
- [ ] Downloaded CSV does **not** contain any `systemTemp` rows
- [ ] Empty range produces a file with headers only
- [ ] Invalid range (end ≤ start) shows an error, no download

### Profile editor
- [ ] Sidebar profile button opens dialog with current values
- [ ] Full name and email save and appear in the sidebar avatar initials
- [ ] Blank name / email clears the field (not stored as empty string)
- [ ] Invalid email format shows validation error

### Responsive layout
- [ ] Desktop (≥ 821 px): sidebar always visible; matrix table scrolls inside its container
- [ ] Mobile (≤ 820 px): hamburger menu opens sidebar drawer; matrix table scrolls horizontally inside `.table-scroll`
