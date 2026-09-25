# Implementation roadmap

The original [project plan](iot_data_logging_project_plan.md) defines scope. This file
tracks implementation and verification separately. The five admin pages use the
user's supplied image references: navy, emerald, light surfaces and simple tables.
Templates and assets live in this repository; no frontend packages or build step.

## Milestone 1 — Backend foundation ✓

- [x] Python/FastAPI package, configuration, local setup and ignored secrets.
- [x] SQLAlchemy models and explicit Alembic migration.
- [x] Admin password hashing, expiring bearer sessions, logout and admin CLI.
- [x] Authenticated device management with a ten-device limit.
- [x] Global parameter whitelist management; history survives parameter removal.
- [x] Transactional MQTT ingestion and per-device message deduplication.
- [x] Separate MQTT collector with QoS 1 acknowledgement after commit.
- [x] Paginated telemetry API and streamed date-range CSV export.
- [x] Docker Compose definition for PostgreSQL, Mosquitto, API and collector.
- [x] Pass local automated checks and migration verification.
- [x] `DELETE /api/devices/{id}/telemetry` — clears readings, records and
      deduplication receipts; device registration is preserved. Five tests passing.
- [ ] Verify the full PostgreSQL/Mosquitto stack on Docker (in progress on Proxmox VM).

Exit: an authenticated admin registers a device and parameter; a simulated device
publishes a reading; only approved values appear in the data view and CSV.

## Milestone 2 — Admin UI ✓

- [x] Login page.
- [x] Devices page with add/edit form, enable toggle, and per-device clear-data button.
- [x] Allowed Parameters page with add, enable/disable and removal confirmation.
- [x] Stored Data matrix view — one row per transmission, one column per parameter.
- [x] CSV Export page with start/end times, timezone and validation feedback.
- [x] Shared navigation, logout, mobile layout and session-expired flow.
- [x] HttpOnly, SameSite=Strict browser session cookies and custom-header CSRF protection.
- [x] UI/API integration and browser smoke test at desktop and phone widths.
- [x] Separate `user_profiles` table, self-service profile API and sidebar profile form.
- [x] `systemTemp` device-health badge (OK / Not OK / Unknown) in Stored Data matrix.
- [x] `systemTemp` excluded from CSV exports; retained in the database.

## Milestone 3 — Repository and deployment infrastructure (current)

- [x] Broken Git HEAD repaired — repository re-initialized on `main` branch.
- [x] Initial commit (58 files) pushed to
      `https://github.com/mdiftekharahmed/IoT-Telemetry-Hub`.
- [x] `.env.example` updated: `API_PORT` variable, `SYSTEM_TEMP_*` vars, grouped sections.
- [x] `compose.yaml`: API port driven by `${API_PORT:-8000}`, binds all interfaces.
- [x] `deploy/setup-vm.sh` — installs Docker Engine on Ubuntu 24.04, clones repo.
- [x] `deploy/start.sh` — pre-flight secret validation, image build, `docker compose up`.
- [x] `deploy/gen-mqtt-passwords.sh` — creates `secrets/mosquitto.passwd` for the
      collector and prints per-device credential instructions.
- [x] `deploy/README.md` — step-by-step guide: Docker → .env → passwords →
      start → create admin → verify.
- [ ] SSH into Proxmox VM and run `deploy/setup-vm.sh`.
- [ ] Create `.env` with real `POSTGRES_PASSWORD`, `MQTT_PASSWORD`, `API_PORT`.
- [ ] Run `deploy/gen-mqtt-passwords.sh` to produce `secrets/mosquitto.passwd`.
- [ ] Run `deploy/start.sh` — builds image, runs migrations, starts all services.
- [ ] `docker compose exec api python -m app.cli admin`.
- [ ] Verify `GET /health/ready` → `{"status":"ok"}` and login page loads.
- [ ] Register a test device, enable a parameter, publish a test MQTT message,
      confirm it appears in Stored Data and downloads correctly via CSV export.

Exit: full Compose stack running on Proxmox VM; end-to-end ingestion verified.

## Milestone 4 — Reliability hardening

- [ ] Confirm device firmware supports the proposed MQTT contract.
- [ ] Confirm publishing interval and retention/storage requirements.
- [ ] PostgreSQL integration and concurrency tests, including device capacity.
- [ ] Live broker authentication and per-device topic ACL tests.
- [ ] Broker disconnect, database outage, redelivery and restart tests.
- [ ] Representative volume test with ten simulated devices and a large export.
- [ ] Login rate limiting before public deployment.
- [ ] Backup scripts, off-host backup destination and tested restore procedure.
- [ ] Pin container versions/digests for a release and document upgrades.

Exit: recovery and access controls verified; no public database; data survives
restart and a backup can be restored.

## Milestone 5 — Production delivery

- [ ] Reverse proxy (Nginx) + HTTPS (Let's Encrypt or self-signed for private net).
- [ ] `SECURE_COOKIES=true` once HTTPS is in front.
- [ ] MQTT TLS or restrict broker to approved private-network IPs only.
- [ ] Firewall: only `API_PORT` and (optionally) `1883` exposed.
- [ ] Production domain, secrets, networking confirmed with client.
- [ ] Validate all original acceptance criteria on the live system.
- [ ] Operator guide, backup schedule and handover documentation.

## Working decisions

- Python backend; PostgreSQL is the target database. SQLite is only a native local
  development/test convenience, with a single API process.
- MQTT topic: `devices/<device_id>/telemetry`; identity comes from the topic and
  broker ACL, never from an untrusted payload field.
- Numeric, finite values only initially. Strings, booleans and nested values need
  an explicit schema change if firmware requires them.
- One global whitelist; disabled/unregistered devices are ignored.
- Require a UUID `message_id` and reuse it on retries. Receipts contain no sensor
  values; no raw payload is persisted.
- Accept an optional timezone-aware device timestamp; otherwise use receipt time.
  Device clock accuracy is not validated in this milestone.
- UTC storage; exports use start-inclusive/end-exclusive intervals `[start, end)`.
- One collector process and persistent MQTT session; devices publish QoS 1 without
  retention. Finite broker queues and disk persistence do not imply zero data loss.
- No automatic retention/deletion until the client's retention policy is decided.
- API listen port exposed via `${API_PORT:-8000}` in Compose; configurable in `.env`.
- `secrets/mosquitto.passwd` is gitignored; generated on the VM by
  `deploy/gen-mqtt-passwords.sh` using `mosquitto_passwd`.

## Environment notes

Initial local workstation: Windows with Python 3.14; Docker not available locally.
Native SQLite/API tests pass; PostgreSQL SQL generation checked offline.
Live PostgreSQL/Mosquitto/container tests to be completed on the Proxmox VM.
A separate ignored `demo.db` contains synthetic data for the local preview.
The broken `.git/HEAD` (refs/heads/.invalid) has been resolved: repository
re-initialized, all 58 project files committed on `main`, force-pushed to
`https://github.com/mdiftekharahmed/IoT-Telemetry-Hub`.
