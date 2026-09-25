# Deployment readiness audit — IoT Telemetry Hub

**Verdict: Not ready for production deployment or client handover.** Audited locally on 2026-09-26 at Git revision `9e755c540715a56f8591f9df7e41579fffad6b3e` on Windows/Python 3.14. This was a source and isolated-test audit, not a live VM or production-data audit. The shipped example configuration prevents startup if copied with blank health thresholds; the credential lifecycle can silently diverge from Mosquitto; and the production network, TLS, backups, and live integration checks remain unfinished. No application code was changed.

## System overview

FastAPI serves an authenticated admin API and plain HTML/CSS/JavaScript UI (`app/api.py`, `app/templates`, `app/static`). A separate Paho MQTT worker (`app/mqtt_worker.py`) consumes QoS 1 messages, validates and whitelists values (`app/ingestion.py`), then stores transmission records, readings, and deduplication receipts in PostgreSQL through SQLAlchemy/Alembic. The admin can register up to ten devices, manage a global parameter whitelist, inspect records and derived `systemTemp` health, and export CSV. Docker Compose runs PostgreSQL 17, Mosquitto 2, migration, API, and worker (`compose.yaml`). Ubuntu 24.04 VM deployment is intended (`deploy/README.md`, `ROADMAP.md`); the actual VM state, client domain, device network route, health thresholds, backup destination, and retention requirements were unavailable.

Critical journeys are admin bootstrap/login, device registration and MQTT credential issuance, MQTT publish and durable ingestion, stored-data inspection, CSV download, device removal, and backup/restore. The local tests cover portions of these with SQLite and mocks; they do not prove the Compose/PostgreSQL/Mosquitto path.

## Checks and results

| Check / method | Status | Evidence |
|---|---|---|
| Read plans, deployment docs, source, migrations, tests, UI, container definitions | Passed | Reviewed `README.md`, `ROADMAP.md`, `WORKPHASE.md`, `docs/`, `deploy/`, `app/`, `migrations/`, `tests/`; no repository `AGENTS.md` found. |
| Python tests: `.venv\Scripts\python.exe -m pytest -q --tb=short` | Failed | Outside sandbox: **63 passed, 5 failed, 1 warning** in 46.55 s. Failures in `tests/test_api.py` (2), `tests/test_ingestion.py` (1), `tests/test_records.py` (2). First sandbox attempts failed because pytest temp directories were inaccessible; these are environment errors, not additional app failures. |
| Dependency consistency: `.venv\Scripts\python.exe -m pip check` | Passed | `No broken requirements found.` This does not scan advisories. |
| Ruff lint: `.venv\Scripts\python.exe -m ruff check app tests migrations scripts` | Failed | 12 errors, including imports, unused imports and line length. |
| Ruff formatting: `.venv\Scripts\python.exe -m ruff format --check app tests migrations scripts` | Failed | Several files need formatting; local Ruff also panicked while rendering a diff, so this run is not a trustworthy complete formatting inventory. |
| Blank health threshold reproduction: `Settings(system_temp_min="", system_temp_max="", _env_file=None)` | Failed | Pydantic raised two `float_parsing` validation errors. The supplied `.env.example:34-35` contains exactly these blank values. |
| Migration/model check | Passed | `tests/test_migrations.py` passed in the suite using isolated SQLite; PostgreSQL SQL compilation test passed. No live PostgreSQL upgrade/rollback was attempted. |
| Production Compose build and startup | Blocked | `docker` unavailable on this local host; VM was not accessed under this audit's no-external-systems instruction. |
| Real MQTT publish/auth/reload and PostgreSQL ingestion | Blocked | Requires running broker/DB and controlled test devices. Existing worker tests mock the broker. |
| Browser desktop/mobile and keyboard/accessibility testing | Not run | No isolated deployed browser target; source was inspected. |
| Dependency advisory/CVE scan and image scan | Not run | `pip-audit` and a container scanner were unavailable. `pip check` is not a security scan. |
| Backup and restore drill, TLS, DNS, firewall, alerts | Blocked | No approved staging/VM environment or client deployment configuration; no repository backup implementation. |
| Upload/path traversal/SSRF/CORS review | Not applicable | No upload, server-side URL fetch, file-path input, or cross-origin API configuration was found in this application. |

## Detailed findings

Each reproduction below uses disposable local/staging state; do not use production data.

### DR-01 — Blank example thresholds prevent app startup

**Severity:** Critical. **Classification:** Verified bug. **Blocks deployment:** Yes; the documented first-run path copies `.env.example` and leaves these fields blank unless the operator overrides them.

**Evidence:** `.env.example:31-36` explicitly says blank means unknown health; `app/config.py:13-14` declares optional floats without empty-string handling; `app/main.py:3` constructs settings at import. The targeted `Settings(...)` reproduction above raises two validation errors. **Reproduce:** copy `.env.example`, fill only required DB/MQTT secrets, then start the API or worker. **Expected:** empty thresholds become `None` and health is `unknown`. **Actual:** settings validation rejects the empty values, so service initialization fails. **Impact:** the default documented deployment cannot start. **Fix:** use `env_ignore_empty=True` in settings config or a field validator converting `""` to `None`, and test the exact example file in a startup smoke test. **Effort/dependency:** Small; no external dependency. **Acceptance test:** API and worker settings load from a copied example with blank thresholds; numeric limits still validate and min > max still fails.

### DR-02 — Device credential changes may silently fail after database commit

**Severity:** High. **Classification:** Verified bug in error handling; actual broker-file failure in the VM is unverified. **Blocks deployment:** Yes, until real broker add/revoke flows pass.

**Evidence:** `app/api.py:233-247` commits a device before running `mosquitto_passwd`, and only runs it if the file exists; any subprocess error is printed while the API still returns 201. Deletion similarly commits first, suppresses errors, and returns 204 (`app/api.py:270-292`). `compose.yaml:62` mounts the secrets directory into the API; `Dockerfile:9-12` runs it as `appuser`, while `deploy/gen-mqtt-passwords.sh:23-28` creates the file in another container. File write permissions on the target VM were not checked. **Reproduce:** in an isolated app with no `/secrets/mosquitto.passwd`, POST a valid device and observe success despite no broker credential; likewise force `mosquitto_passwd` to fail and observe success. **Expected:** registration/revocation succeeds in both DB and broker or reports a recoverable failure. **Actual:** they can diverge silently. **Impact:** devices cannot connect after successful registration; deleted devices can retain broker login credentials. **Fix:** make the credential-file path and ownership explicit, update it through a controlled provisioner, handle failure with a visible error and reconciliation/rollback strategy, and log structured errors without passwords. Do not make a database transaction depend on an unbounded subprocess. **Effort/dependency:** Medium; requires Compose/Mosquitto integration design. **Acceptance test:** in disposable Compose, add a device and publish under its ID, then delete and verify MQTT authentication is rejected after reload; simulate file failure and verify API reports it.

### DR-03 — API transport and device network path are not production configured

**Severity:** High. **Classification:** Improvement / release gap. **Blocks deployment:** Yes for an Internet-facing or remote-device deployment.

**Evidence:** `compose.yaml:1` calls the file local development only; `compose.yaml:60` publishes HTTP port 8000 on all interfaces; `.env.example:6` sets insecure cookies; `deploy/README.md:77` instructs visiting an `http://` URL. MQTT is bound only to VM loopback (`compose.yaml:32`), while the device ACL expects external publishers (`docker/acl:5`). `ROADMAP.md:82-84` and `WORKPHASE.md:151-155` leave HTTPS and MQTT reachability/protection undone. **Reproduce:** inspect effective Compose port mapping on staging and attempt a publish from the intended device network. **Expected:** HTTPS admin access with secure cookies and a protected, reachable MQTT endpoint. **Actual:** the checked-in configuration provides plain HTTP API access and loopback-only MQTT. **Impact:** login/session exposure if opened publicly, or inability for remote sensors to send. **Fix:** define the client domain, reverse proxy/certificate, secure cookie setting, and an explicit private-network/TLS route for MQTT with firewall allowlist. Bind the API to loopback behind the proxy. **Effort/dependency:** Medium; depends on domain/network ownership. **Acceptance test:** external HTTPS login succeeds, HTTP redirects, cookie has `Secure`, and a test sensor publishes from its real network while unauthorized sources cannot.

### DR-04 — No tested backup/restore or safe deployment rollback

**Severity:** High. **Classification:** Improvement / release gap. **Blocks deployment:** Yes for client handover with retained telemetry.

**Evidence:** `ROADMAP.md:74-78` and `WORKPHASE.md:156-158` explicitly leave backups and restore test undone. `compose.yaml:19-20` holds PostgreSQL in a named volume; `deploy/start.sh:31-36` updates the stack without a data snapshot or rollback plan; `deploy/README.md:93-96` documents update/down commands but no restore. **Reproduce:** request an operator-run restore procedure for a disposable DB; none is provided by the repository. **Expected:** scheduled off-VM backups and an observed restore of a sample dataset before release. **Actual:** no repository automation or evidence of a restore drill. **Impact:** VM/volume corruption or a bad migration can permanently lose client data. **Fix:** add periodic `pg_dump`/verified off-host retention, protect backup credentials, document restore and version rollback, then perform a timed drill. **Effort/dependency:** Medium; backup destination/retention decision required. **Acceptance test:** restore a staging dump to a fresh instance and compare record counts/checksums; document recovery time.

### DR-05 — Unit disappears when parameter is enabled or disabled

**Severity:** Medium. **Classification:** Verified bug. **Blocks deployment:** No if corrected before UI handover; otherwise users silently change data labels.

**Evidence:** the toggle sends only `enabled` (`app/static/app.js:154-158`); `ParameterUpdate.unit` defaults to `None` (`app/schemas.py:67-70`); the endpoint always assigns `parameter.unit = body.unit` (`app/api.py:305-313`). **Reproduce:** create a parameter with `unit="°C"`, then PUT `/api/parameters/{name}` with only `{"enabled":false}` or use the UI switch. **Expected:** only `enabled` changes. **Actual:** `unit` becomes null. **Impact:** table and CSV labels lose units (`app/api.py:347-351`). **Fix:** send the current unit from the UI or implement PATCH/field-set-aware partial updates. **Effort/dependency:** Small. **Regression:** toggle both directions and assert unit is unchanged in API, table, and export header.

### DR-06 — The test suite and export UI describe an obsolete CSV contract

**Severity:** Medium. **Classification:** Verified bug in tests/docs/UI. **Blocks deployment:** Yes as a release gate, since current checks fail and users are told the wrong file shape.

**Evidence:** tests expect long-form `parameter,value` rows (`tests/test_api.py:127`, `tests/test_records.py:158,177`), while the implementation emits `timestamp,device_id,device_name` plus one column per parameter (`app/api.py:343-389`). `tests/test_api.py:102` omits the newly returned `unit`. The export page still promises “4 columns” and one row per sensor value (`app/static/app.js:235-236`). Full suite: 5 failed/63 passed, of which these account for four. **Reproduce:** run the command in Checks and compare exported header to the preview. **Expected:** tests, API contract, docs and UI agree. **Actual:** they diverge. **Impact:** a failing release gate and misleading client handover. **Fix:** define the wide CSV contract, update assertions and preview, document historical-column behavior and excluded `systemTemp`. **Effort/dependency:** Small; agree on final CSV contract. **Regression:** exact header/row tests with multiple parameters, a removed parameter, and a `systemTemp`-only message.

### DR-07 — CSV can contain spreadsheet formulas in device names

**Severity:** Medium. **Classification:** Suspected risk (code path verified; spreadsheet execution not tested). **Blocks deployment:** Conditional if CSVs will be opened in spreadsheet software.

**Evidence:** device names accept arbitrary nonblank text (`app/schemas.py:23-42`); export writes `device_name` verbatim through `csv.writer` (`app/api.py:356-388`). CSV quoting does not necessarily neutralize a cell beginning with `=`, `+`, `-`, or `@`. **Reproduce:** in disposable data, register a device named `=1+1`, ingest a reading, export and inspect the `device_name` cell; then open only in a safe spreadsheet test environment. **Expected:** exported text is treated as data. **Actual:** the CSV contains a formula-like leading character; execution depends on the spreadsheet. **Impact:** a malicious or accidental name may be evaluated when a client opens the file. **Fix:** apply a documented spreadsheet-safe escaping policy to text cells while keeping machine-readable export needs in mind. **Effort/dependency:** Small; client CSV-consumer decision. **Regression:** export names beginning with each trigger character, tab, and ordinary Unicode.

### DR-08 — MQTT passwords are retained and returned in plaintext

**Severity:** Medium. **Classification:** Verified design risk. **Blocks deployment:** Conditional on the client's credential-handling requirements, but should be resolved before handover.

**Evidence:** `app/models.py:18` stores `mqtt_password` in the devices table; `app/schemas.py:53` includes it in every `DeviceOut`; `app/api.py:215-218` returns the list; `app/static/app.js:129` displays all device passwords. Broker passwords are separately hashed in Mosquitto's password file. **Reproduce:** list devices while authenticated and inspect the response/UI. **Expected:** reveal a new secret once, then provide controlled rotation; routine listings omit it. **Actual:** any valid admin session can retrieve all device secrets indefinitely. **Impact:** DB backups, API responses, and shoulder-surfing expose working device credentials; compromise requires rotation of every device. **Fix:** issue once and display only on creation/rotation, store only a hash or encrypted recoverable copy if the product truly requires retrieval, and define rotation/recovery. **Effort/dependency:** Medium; may require device provisioning UX. **Regression:** GET list and update responses never contain passwords; rotation invalidates the old credential.

### DR-09 — Auth and export lack abuse limits; health does not cover ingestion

**Severity:** Medium. **Classification:** Improvement / reliability risk. **Blocks deployment:** Conditional on exposure and expected data volume; at least rate/size limits should be decided pre-release.

**Evidence:** login has no rate limiter (`app/api.py:142-160`); date range only checks order (`app/api.py:67-76`); export streams an unbounded time range with a DB session held for the full response (`app/api.py:335-398`), and the browser materializes the entire file as a Blob (`app/static/app.js:247-264`). `/health/ready` checks only the DB (`app/api.py:135-140`); Compose healthcheck watches only this (`compose.yaml:66-70`) while worker broker rejection/failure is separate (`app/mqtt_worker.py:38-74`). **Reproduce:** staging load test with a long export, invalid login burst, and stopped broker. **Expected:** bounded resource use, sensible throttling, and an actionable ingestion alarm. **Actual:** source has no such guardrail; actual capacity/alert behavior is unmeasured. **Impact:** avoidable resource exhaustion and silent telemetry outage. **Fix:** add login rate limiting at proxy/app, cap or async-queue exports, stream downloads where possible, and expose worker/broker health or alert on ingestion lag. **Effort/dependency:** Medium; define volume and operations target. **Verification:** load and failure-injection tests with thresholds and alerts.

### DR-10 — Deployment documentation and reproducibility need repair

**Severity:** Medium. **Classification:** Improvement. **Blocks deployment:** Yes for repeatable client handover.

**Evidence:** `deploy/README.md:41-48,94` presents manual device-password commands despite the UI auto-generation path (`app/api.py:233-247`); `deploy/README.md:102` says MQTT is internal-only although Compose publishes it to VM loopback (`compose.yaml:32`). `deploy/README.md:12` executes a remote script from a moving `main` branch, and `deploy/setup-vm.sh:34` pulls latest; container tags and Python base are unpinned (`compose.yaml:16,30`, `Dockerfile:1`). No `.github` CI workflow or LICENSE file was found. **Reproduce:** follow the guide in disposable staging and compare listed steps with UI-created credentials; inspect exact image digests before and after a rebuild. **Expected:** a versioned, reproducible install and one documented credential workflow. **Actual:** instructions and implementation differ; moving dependencies can change deploy behavior. **Impact:** operator errors, difficult rollback, and unclear handover/legal distribution terms. **Fix:** pin release revision/image digests, use reviewed install commands, reconcile credential steps, add CI gates, an operator guide and an explicit license/ownership decision. **Effort/dependency:** Small–medium; release process and owner approval. **Verification:** a new operator follows the guide on a fresh staging VM and records a successful smoke test.

### DR-11 — Malformed message-ID rule is undefined and one test fails

**Severity:** Low. **Classification:** Verified test failure; product defect depends on intended MQTT contract. **Blocks deployment:** No by itself, but contributes to the failed suite.

**Evidence:** `tests/test_ingestion.py:81-87` expects `message_id="invalid"` to raise `InvalidMessage`; `app/schemas.py:100-103` accepts any 1–36-character string, so the case is accepted. The existing `docs/mqtt-contract.md` should be made authoritative on UUID versus opaque ID. **Reproduce:** run `test_malformed_payloads` with that case. **Expected:** either UUID-only rejection or a test that accepts opaque IDs. **Actual:** implementation and assertion disagree. **Impact:** devices and deduplication can use IDs outside the presumed contract. **Fix:** decide format; if UUID required, use a UUID field/validator and test canonical behavior; otherwise correct the test/docs. **Effort/dependency:** Small; protocol decision. **Regression:** accepted/rejected ID boundary cases plus duplicate receipt behavior.

## Improvement opportunities

**Necessary before release:** DR-01–04 and DR-06/10; decide DR-07–09 based on exposure and client data volume. Preserve a small stack: these changes do not require a front-end framework. Add CI for tests/lint and a disposable Compose integration job; update the release checklist whenever the CSV or MQTT contract changes.

**Soon after release:** index/query-plan review for record pagination and global `DISTINCT` parameter scans (`app/api.py:400-422`); test CSV and page behavior with realistic row counts. Add data-retention policy, backup monitoring, and credential rotation. Use `ruff check` as a lightweight code-quality gate; 12 current violations are routine cleanup, not a need for heavy tooling.

**Optional UX/accessibility:** validate the current mobile table, dialog focus, 320–820 px layout, keyboard navigation and screen reader announcements in real browsers. Source includes responsive navigation and escaped HTML (`app/static/app.js:8,270-294`), but visual and assistive testing was not performed. Fix the export preview before handover. A specialist should review privacy/retention terms and distribution/license terms; this audit is not a legal compliance determination.

## Deployment and client handover checklist

| Gate | State | Required action / evidence |
|---|---|
| Example configuration starts API and worker | **Fail** | Fix DR-01; load the exact `.env.example` with placeholder-only secrets in staging. |
| Automated tests and lint | **Fail** | Resolve five pytest failures and 12 Ruff findings; rerun in CI. |
| PostgreSQL migration and real MQTT end-to-end | **Unknown** | Run fresh-install and upgrade migration, credential add/revoke, authorized/unauthorized publish, duplicate delivery and reconnect tests in disposable Compose. |
| HTTPS, secure cookies, protected MQTT route | **Fail** | Implement DR-03 and test from real client/device networks. |
| Backup, restore and rollback | **Fail** | Implement DR-04 and record a staging restore drill. |
| Device credential consistency and rotation | **Fail** | Resolve DR-02/08, including file permissions and broker reload verification. |
| CSV contract, formula policy and sample export | **Fail** | Resolve DR-06/07; give client an approved sample. |
| VM health, monitoring and alert ownership | **Unknown** | Verify worker/broker and DB alerts, disk space, logging, restart behavior. |
| Client handover documents and release artifact | **Fail** | Update deployment/operations guide; pin release, document owners and credentials process. |

After deploying to staging, smoke-test: login/logout and cookie flags; create parameter with unit; toggle it; create device and authenticate MQTT; publish a valid and a duplicate message; inspect record/health; export date-bounded CSV excluding `systemTemp`; disable/delete the device and confirm MQTT rejection; restore from backup; record a rollback to the previous pinned release. Use only disposable data.

## Prioritized remediation plan

1. **Before deployment (small, 0.5–1 day):** fix blank threshold handling and align the CSV/API/message-ID tests; update the misleading export UI. Acceptance: exact-example startup and clean pytest/Ruff gates.
2. **Before deployment (medium, 1–3 days):** make device MQTT credential add/revoke reliable and observable; settle plaintext retention and rotation. Acceptance: disposable Compose add/publish/delete/reject tests, including simulated file failure.
3. **Before deployment (medium, 1–3 days, infrastructure dependent):** configure HTTPS, secure cookies, a protected device route, firewall and pinned release artifact. Acceptance: independent client-network smoke test and reviewed effective Compose config.
4. **Before handover (medium, 1–2 days, destination dependent):** implement off-host backups, alerting and a tested restore/rollback; rewrite the operator guide. Acceptance: signed-off restore drill and repeatable fresh staging install.
5. **Soon after (small–medium):** load/abuse tests, export limits, login throttling, query-plan review and browser accessibility checks. Acceptance: measured limits and documented client expectations.

## Limitations and unverified areas

Docker and the actual Ubuntu VM were not used; no production data, external services, or secret values were accessed. Thus image build compatibility, Mosquitto file ownership/reload behavior, PostgreSQL transaction/concurrency behavior, firewall/TLS, physical sensors, restore, and container health are unverified. Local tests use SQLite; the PostgreSQL migration check only compiles SQL. The first sandbox pytest runs were invalidated by Windows temp-directory permissions; the reported 63/5 result is from a permitted run outside that sandbox. Ruff formatting crashed while rendering its diff, so only its partial result is available. No type checker, CVE scanner, container scanner, browser automation, coverage report, load test, or penetration test was run. Vulnerability status is **unknown** despite `pip check` passing. No client domain, device connectivity plan, temperature health range, data volume, retention period, recovery objective, or compliance requirements were supplied. Any of these could change severity or release conditions.

**Release recommendation:** Do not hand this revision to the client as production-ready. Release only after the startup and credential defects are fixed, checks pass, HTTPS/private MQTT networking and backups are in place, and the full staging smoke/restore sequence above is recorded against a pinned release.
