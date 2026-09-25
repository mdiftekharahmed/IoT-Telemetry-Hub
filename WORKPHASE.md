# Project Work Phases

Last updated: 25 September 2026 (evening)

This file is the short, practical status tracker for the IoT Telemetry Hub. The
original requirements remain in `iot_data_logging_project_plan.md`; technical
decisions and longer-term tasks remain in `ROADMAP.md`.

Status key:

- `[x]` Done and locally verified
- `[~]` In progress or implemented but awaiting verification
- `[ ]` Not started
- `[?]` Needs a project decision

## Current focus

The current work phase is **Stored Data restructuring**. The data explorer must
show one MQTT transmission per row, with the registry ID, device details,
timestamp, each approved parameter in its own column, and device health derived
from the `systemTemp` value included in that transmission.

`systemTemp` is device-health metadata. It must be visible in the Stored Data
screen but excluded from CSV exports.

## Phase 1 — Project foundation

- [x] Create the FastAPI Python project structure.
- [x] Add environment-based configuration and ignored secret files.
- [x] Add SQLAlchemy database models.
- [x] Add versioned Alembic database migrations.
- [x] Add Dockerfile and Docker Compose services for the API, worker,
  PostgreSQL, and Mosquitto.
- [x] Add local Windows development instructions.
- [x] Add a separate synthetic demo database and preview mode.
- [ ] Repair the repository's broken Git `HEAD` before the first commit/push.
- [ ] Verify the complete Compose stack on a machine with Docker.

## Phase 2 — Authentication and user details

- [x] Store password hashes separately from profile information.
- [x] Create expiring admin sessions and logout support.
- [x] Support bearer authentication for API clients.
- [x] Support HttpOnly, SameSite browser session cookies.
- [x] Add custom-header protection for browser write requests.
- [x] Add the admin creation/password-reset command.
- [x] Add the separate `user_profiles` table in the same database.
- [x] Add fields for full name, email, created time, and updated time.
- [x] Add self-service profile read/update endpoints.
- [x] Add the sidebar profile editor.
- [~] Run the complete regression suite after the new profile migration.
- [ ] Add login rate limiting before public deployment.

## Phase 3 — Device and parameter management

- [x] Register up to ten devices.
- [x] Edit device names and enable/disable devices.
- [x] Reject telemetry from unknown or disabled devices.
- [x] Add, remove, enable, and disable globally allowed parameters.
- [x] Preserve historical readings when a parameter is disabled or removed.
- [x] Keep broker credentials separate from application device registration.
- [ ] Confirm the final list of parameters and display units from the real
  device firmware.
- [ ] Confirm whether parameter display labels/groups need admin configuration.

## Phase 4 — MQTT ingestion and storage

- [x] Subscribe to `devices/<device_id>/telemetry` using a separate worker.
- [x] Validate UTF-8 JSON payloads and accept finite numeric values only.
- [x] Filter values through the parameter whitelist.
- [x] Store approved values transactionally in PostgreSQL-compatible tables.
- [x] Deduplicate retries using device ID plus message UUID.
- [x] Acknowledge QoS 1 messages after successful processing.
- [x] Avoid acknowledging unexpected database/processing failures.
- [x] Store and normalize timestamps in UTC.
- [x] Add a `telemetry_records` registry table so one accepted transmission is
  represented by one record and its parameter values stay grouped together.
- [x] Add a migration that preserves old readings as separate registry records
  because their original message grouping cannot be reconstructed safely.
- [x] Finish and verify the grouped-record ingestion migration and tests.
- [ ] Confirm publishing frequency, retention period, and expected storage size.

## Phase 5 — Admin user interface

- [x] Build a responsive login screen from the supplied visual references.
- [x] Build the shared desktop sidebar and mobile navigation drawer.
- [x] Build Devices and Allowed Parameters pages.
- [x] Build the CSV Export page.
- [x] Add empty, loading, error, and session-expired states.
- [x] Use plain HTML, CSS, local SVG icons, and vanilla JavaScript.
- [x] Store all templates and static assets inside this Git repository.
- [x] Verify the main flows at desktop and phone viewport sizes.
- [x] Replace the current long-form Stored Data view with a matrix table:
  one transmission per row and one parameter per column.
- [x] Add the table heading structure for Registry ID, Device Details,
  Timestamp, parameter columns, and Device Health.
- [x] Show `—` when a transmission does not contain a displayed parameter.
- [x] Keep horizontal scrolling inside the matrix table on mobile screens.
- [x] Recheck pagination after changing from reading rows to registry rows.

## Phase 6 — `systemTemp` device health

- [x] Reserve `systemTemp` as the value used to determine device health.
- [x] Define health as belonging to each transmission, since `systemTemp` is
  included in every transmission and describes the device at that time.
- [x] Add backend health evaluation with `OK`, `Not OK`, and `Unknown` states.
- [ ] Confirm the unit and healthy minimum/maximum thresholds.
- [x] Display `systemTemp` and a Device Health badge in the Stored Data matrix.
- [x] Show `Unknown` if the value or health thresholds are unavailable.
- [x] Exclude `systemTemp` from CSV exports while retaining it in the database.
- [x] Add boundary tests for the chosen healthy range.

## Phase 7 — CSV export

- [x] Select an inclusive start time and exclusive end time.
- [x] Stream the CSV instead of building the whole file in memory.
- [x] Return a header-only CSV for an empty time range.
- [x] Include timestamp, device ID, parameter, and value columns.
- [x] Update export logic and tests to always omit `systemTemp`.
- [?] Decide whether the final CSV remains in long format (one parameter value
  per row) or changes to the same wide format as the Stored Data matrix.

## Phase 8 — Testing and reliability

- [x] Test authentication, device limits, whitelist behavior, malformed data,
  duplicate messages, UTC conversion, CSV boundaries, and rollback behavior.
- [x] Test browser-cookie authentication and UI routes.
- [x] Verify the original backend/UI suite locally before the latest schema work.
- [x] Run and pass the full suite after profile and telemetry-record migrations.
- [x] Add grouped-record and `systemTemp` health tests.
- [ ] Test with live PostgreSQL rather than SQLite only.
- [ ] Test with a live Mosquitto broker and per-device ACL credentials.
- [ ] Test broker disconnects, database outages, redelivery, and restarts.
- [ ] Simulate ten devices and test a large CSV export.
- [ ] Test container and VM reboot persistence.

## Phase 9 — Ubuntu VM deployment

- [ ] Finish preparing the Ubuntu VM.
- [ ] Install Docker Engine and Docker Compose.
- [ ] Clone or copy the repository to the VM.
- [ ] Create production-like PostgreSQL, MQTT, and admin secrets.
- [ ] Start the Compose stack and apply all database migrations.
- [ ] Create the first administrator.
- [ ] Provision separate MQTT credentials for each device.
- [ ] Verify ingestion, management pages, health display, and CSV export.
- [ ] Configure Tailscale/private-network access for development testing.

## Phase 10 — Production deployment and handover

- [ ] Configure the client domain, reverse proxy, and HTTPS.
- [ ] Enable secure cookies in the HTTPS environment.
- [ ] Keep PostgreSQL inaccessible from the public network.
- [ ] Configure MQTT TLS or restrict MQTT to the approved private network.
- [ ] Configure firewall rules.
- [ ] Add automated PostgreSQL and configuration backups.
- [ ] Store backups outside the active database volume.
- [ ] Perform and document a restore test.
- [ ] Pin release container versions/digests and document upgrades.
- [ ] Validate every acceptance criterion on the client VPS.
- [ ] Prepare the operator guide and handover documentation.

## Decisions still needed

1. `systemTemp` unit and the inclusive healthy range that produces `OK`.
2. Final real-device parameter names and their display units.
3. Device publishing interval and data-retention duration.
4. Whether CSV output stays long-form or becomes one transmission per row.
5. Production domain, MQTT exposure method, and backup destination.

## Immediate next actions

1. Decide the `systemTemp` unit and healthy min/max thresholds; set
   `SYSTEM_TEMP_MIN`, `SYSTEM_TEMP_MAX`, and `SYSTEM_TEMP_UNIT` in `.env`.
2. Confirm the final real-device parameter names and display units.
3. Decide whether the CSV remains long-form or becomes one row per transmission.
4. Move to the Ubuntu VM: Docker Engine, Docker Compose, clone repo, run
   migrations, create admin, provision MQTT credentials.
5. Verify ingestion, Stored Data matrix, health badges, and CSV export live.
