# Implementation roadmap

The original [project plan](iot_data_logging_project_plan.md) defines scope. This file
tracks implementation and verification separately. The five admin pages use the
user's supplied image references: navy, emerald, light surfaces and simple tables.
Templates and assets live in this repository; no frontend packages or build step.

## Milestone 1 — Backend foundation (current)

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
- [ ] Verify the full PostgreSQL/Mosquitto stack on Docker.

Exit: an authenticated admin registers a device and parameter; a simulated device
publishes a reading; only approved values appear in the data view and CSV.

## Milestone 2 — Admin UI (implemented)

- [x] Login page.
- [x] Devices page with add/edit form and enabled state.
- [x] Allowed Parameters page with add, enable/disable and removal confirmation.
- [x] Stored Data page with pagination and empty/error states.
- [x] CSV Export page with start/end times, timezone and validation feedback.
- [x] Shared navigation, logout, mobile layout and session-expired flow.
- [x] HttpOnly, SameSite=Strict browser session cookies and custom-header CSRF protection.
- [x] UI/API integration and browser smoke test at desktop and phone widths.
- [x] Separate `user_profiles` table, self-service profile API and sidebar profile form.

## Milestone 3 — Reliability and production preparation

- [ ] Confirm device firmware supports the proposed MQTT contract.
- [ ] Confirm publishing interval and retention/storage requirements.
- [ ] PostgreSQL integration and concurrency tests, including device capacity.
- [ ] Live broker authentication and per-device topic ACL tests.
- [ ] Broker disconnect, database outage, redelivery and restart tests.
- [ ] Representative volume test with ten simulated devices and a large export.
- [ ] Proxy/HTTPS, login rate limiting, MQTT TLS or private-network access.
- [ ] Backup scripts, off-host backup destination and tested restore procedure.
- [ ] Pin container versions/digests for a release and document upgrades.

Exit: recovery and access controls verified on the Ubuntu VM; no public database;
data survives restart and a backup can be restored.

## Milestone 4 — VPS delivery

- [ ] Production secrets, domain, networking and firewall configuration.
- [ ] Versioned release and deployment to client VPS.
- [ ] Validate original acceptance criteria on the deployed system.
- [ ] Operator guide, backup schedule and handover.

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

## Environment notes

Initial local workstation: Windows with Python 3.14; Docker was not found.
Native SQLite/API tests pass; PostgreSQL SQL generation is checked offline.
Live PostgreSQL/Mosquitto/container tests remain pending. A separate ignored
`demo.db` contains synthetic data for the local preview, visibly marked as demo.
The repository's initial `.git/HEAD` points to `refs/heads/.invalid` and Git reports
a broken branch. Application files can be developed, but branch repair is required
before committing/pushing. Git metadata has not been modified.
