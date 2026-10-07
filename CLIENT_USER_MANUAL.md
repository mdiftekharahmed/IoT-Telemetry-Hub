# IoT Telemetry Hub
## Client user manual and administrator handover guide

**Document version:** 1.0  
**Prepared:** 30 September 2026  
**Reference:** repository revision `e283ee3` and current working files  
**Audience:** client operators, device technicians, and infrastructure administrators

This guide describes the application currently present in the project repository. The live VPS was not inspected while preparing this document. Complete the installation record below and verify the handover checklist against the deployed version before distributing it as the final site-specific guide. All credentials must be supplied separately through an approved private channel.

## Contents

1. [Installation record and contacts](#1-installation-record-and-contacts)
2. [What the system does](#2-what-the-system-does)
3. [Quick start](#3-quick-start)
4. [Signing in and managing your profile](#4-signing-in-and-managing-your-profile)
5. [Navigating the dashboard](#5-navigating-the-dashboard)
6. [Managing devices](#6-managing-devices)
7. [Managing allowed parameters](#7-managing-allowed-parameters)
8. [Reading stored data and device health](#8-reading-stored-data-and-device-health)
9. [Exporting data](#9-exporting-data)
10. [Routine operator checklist](#10-routine-operator-checklist)
11. [Troubleshooting for users](#11-troubleshooting-for-users)
12. [Device integration and MQTT](#12-device-integration-and-mqtt)
13. [Testing without a physical sensor](#13-testing-without-a-physical-sensor)
14. [Infrastructure and deployment](#14-infrastructure-and-deployment)
15. [Administrator operations](#15-administrator-operations)
16. [Backups, recovery, and upgrades](#16-backups-recovery-and-upgrades)
17. [API reference](#17-api-reference)
18. [Known limitations and release checks](#18-known-limitations-and-release-checks)
19. [Client acceptance and handover](#19-client-acceptance-and-handover)
20. [Glossary](#20-glossary)

## 1. Installation record and contacts

The infrastructure administrator completes this table. A domain configured in source is not proof that the live service or its certificate is working.

| Item | Installation value / action |
|---|---|
| Client / project owner | To be supplied |
| Dashboard URL | Source Caddy configuration: `https://telemetry.durnibar.tech`; confirm live URL |
| MQTT hostname or IP | To be supplied; do not infer it from the dashboard URL |
| MQTT port and transport | Confirm private/plain MQTT or TLS; source exposes TCP 1883 |
| Required VPN / allowed device network | To be supplied |
| VPS installation directory | Examples use `/opt/iot-telemetry-hub`; confirm actual path |
| Deployed version / release date | Record deployed Git revision and container versions |
| Client operator contact | To be supplied |
| Technical support contact | To be supplied |
| Infrastructure / backup owner | To be supplied |
| Device firmware owner | To be supplied |
| Expected reporting interval | Project requirement: once per hour per device; firmware controls this |
| Approved health range and unit | To be confirmed by device owner; current code defaults are 10–50, unit unset |
| Backup schedule, retention, remote destination | To be agreed and verified |
| Recovery time / acceptable data loss | To be agreed; not guaranteed by this manual |

There are three distinct types of login: **dashboard account**, **device MQTT credentials**, and **VPS SSH credentials**. They are not interchangeable. Never put passwords in this manual or support screenshots.

## 2. What the system does

IoT Telemetry Hub collects numeric sensor readings, stores approved measurements, and makes them available through a web dashboard and CSV downloads. It is intended for a small set of environmental monitoring stations.

```text
Sensor device → MQTT broker → collector worker → PostgreSQL database
                                                       ↓
User browser ← HTTPS proxy ← dashboard and API ←────────┘
```

The intended workload is up to six devices, each sending roughly 30 values once per hour. Over 365 days this is 52,560 transmissions and up to 1,576,800 numeric readings. A transmission is one message; a reading is one value inside that message.

The application supports a configurable registration limit of at most ten devices. It does not set the device reporting interval, calibrate sensors, remotely control hardware, or guarantee delivery during network outages. Device firmware and network availability determine when measurements reach the server.

All currently authenticated dashboard accounts have administrative access to the shared workspace. There is no implemented read-only user role or per-device ownership boundary. Give accounts only to trusted operators.

## 3. Quick start

For an installation already commissioned by the technical team:

1. Obtain the confirmed dashboard URL and your dashboard username/password.
2. Open the URL, sign in, and verify that the browser shows a valid HTTPS connection.
3. Open **Devices**. Confirm the station's Device ID and that it is enabled.
4. Open **Allowed parameters**. Confirm the exact parameter names sent by the device are enabled. Include `systemTemp` if device health is needed.
5. Ask the device technician to send a test transmission, or use the Python procedure in section 13.
6. Open **Stored data** and click **Refresh**.
7. Check the device, timestamp, values, and health indicator.
8. Open **CSV export**, choose a UTC range covering the test, and download the file.
9. Confirm that the values are present and `systemTemp` is excluded from the CSV.
10. Stop test publishing and return the real firmware to the agreed hourly reporting interval.

Success means a new row appears in Stored data and expected measurements are present in the CSV. A device log saying “sent” or a broker acknowledgment alone is not sufficient.

## 4. Signing in and managing your profile

### Sign in

1. Open the dashboard URL supplied by your administrator.
2. Enter your **username**, not your optional profile email address.
3. Enter the dashboard password and select **Sign in to workspace**.
4. Use the eye button if you need to check the password temporarily.

There is no public account-registration page or email password-reset workflow. Contact the administrator if credentials are missing or rejected. The default session lifetime is 12 hours from login; the administrator can configure 1–168 hours. An expired session redirects you to sign in again.

### Profile

Use the profile-edit control in the navigation area to open **Your profile**. Change your full name and optional email, then select **Save profile**. The username is fixed. The email is contact information only; it does not change your login or enable password recovery.

### Sign out

Select **Logout** when finished, especially on a shared computer. Logging out invalidates that session. An administrator resetting your password invalidates your existing sessions.

## 5. Navigating the dashboard

| Page / control | Purpose |
|---|---|
| Stored data | Transmission table, parameter values, device health, manual refresh, paging |
| Devices | Register, rename, enable/disable, clear data, and delete stations |
| Allowed parameters | Define the global list of values permitted into storage and their display units |
| CSV export | Download data from all devices within a selected UTC time interval |
| Profile | Edit display name and optional contact email |

On smaller screens, open the navigation menu using the menu button. Wide tables can be scrolled horizontally to see all parameter columns. Use the normal browser zoom and landscape orientation when needed.

The overview shows registered devices, enabled parameters, and stored transmission count. A card labelled **Stored readings** currently uses the number of transmission records, not the number of individual values. Thirty values in one transmission still increase this card by one.

The table does not update continuously by itself. Click **Refresh** to retrieve new records. A successful browser refresh does not prove that the sensors are reporting.

## 6. Managing devices

### Register a station

1. Open **Devices** and select **Add device**.
2. Enter a useful name, such as `Riverside station 1`.
3. Enter the permanent Device ID, for example `MGRV_001`.
4. Leave **Enable data collection for this device** selected if it should begin reporting.
5. Select **Add device**.
6. In the current UI, the generated MQTT password appears in the Devices table. Share it privately with the device technician.
7. Configure the device's MQTT username to exactly match the Device ID and use its generated password.
8. Confirm one real or test reading reaches Stored data before considering the station commissioned.

Device IDs are case-sensitive, 1–64 characters, begin with a letter or digit, and otherwise contain letters, digits, underscores, or hyphens. `collector` is reserved. Names are 1–120 characters and cannot be blank. An ID cannot be renamed after creation. A duplicate ID or reaching the configured device limit prevents registration.

If the MQTT password is blank for an older/imported device, ask the administrator to check broker provisioning. Do not delete a working station just to recover a password: deletion removes its data. If registration gives an error, verify whether the device already appears before trying again.

### Rename or pause a station

Use **Edit** to change its display name. Existing records and future CSV exports show the current name; names are not historical snapshots. Use the enabled switch to pause acceptance of new readings. Existing data remains available. Disabling is an ingestion control, not proof that the physical device disconnected or stopped transmitting. Messages rejected during the disabled period are not automatically recovered later.

### Understand the two destructive actions

| Action | Retained | Removed |
|---|---|---|
| Disable device | Registration, credentials, existing records | New readings are rejected while disabled |
| Clear telemetry data | Device registration, name, enabled state, credentials | All readings, transmission records, and deduplication receipts for that device |
| Delete device and data | Other devices' records | This device's registration, readings, records, receipts; broker credential removal is attempted |

Read the confirmation dialog rather than relying on icon appearance. **Clear data and Delete device have no undo in the dashboard.** Exporting a CSV is useful for analysis but is not a full restorable backup. Request a verified administrator backup before clearing client records. Clearing receipts permits previously used message IDs to be ingested again if resent.

## 7. Managing allowed parameters

Parameters form one **global whitelist shared by all devices**. Only enabled parameters are retained from incoming messages.

1. Open **Allowed parameters** and select **Add parameter**.
2. Enter the exact firmware key, such as `temperature`, `humidity`, or `systemTemp`.
3. Enter an optional display unit, such as `°C`, `%`, or `ppm`.
4. Leave the parameter enabled and save.

Names are case-sensitive, 1–64 characters, must start with a letter, and otherwise contain letters, digits, and underscores. Units are optional text up to 16 characters. `systemTemp` and `systemtemp` are different keys.

Units label values; the system does **not** convert units. If one device sends Celsius and another sends Fahrenheit under the same key, the system cannot correct this. Agree on common units before commissioning devices. Changing a parameter's unit changes current labels for historical values as well, without converting those values.

Disable a parameter to stop saving it while preserving past readings. Removing it also preserves past numeric readings, but its unit metadata is removed. Adding or enabling it later does not recover values previously discarded. The same already-processed transmission ID cannot be replayed to import newly enabled fields.

## 8. Reading stored data and device health

### Table fields

| Field | Meaning |
|---|---|
| Registry ID | Server-generated identifier for a stored transmission; distinct from the device's message ID |
| Device | Current station name and permanent Device ID |
| Timestamp · UTC | Measurement timestamp supplied by the device, or server receipt time if omitted |
| Parameter columns | Approved stored values; an em dash means no stored value for that key in this record |
| Device Health | Evaluation of this transmission's `systemTemp` against the server's configured limits |

The table is newest-ingested-first, which may differ from measurement-time order when old readings arrive late. Columns may include historical parameters that are no longer enabled. A missing value is not zero. Transmissions with no enabled approved values produce no visible record, even though their IDs can be recorded for deduplication.

Use **Next**, **Previous**, and **Refresh** for navigation. Refresh returns to the newest page. The current source has a pagination discrepancy described in section 18; use date-range CSV exports when completeness matters.

### Device health

| Badge | Interpretation |
|---|---|
| OK | `systemTemp` is present and within the configured inclusive limits |
| Not OK | `systemTemp` is below the minimum or above the maximum |
| Unknown | No stored `systemTemp`, or no health limits are configured in the settings object |

The current code defaults to **10 through 50 inclusive**. These are software defaults, not a certified safe operating range for a particular board. The device owner must approve both the limits and unit. Blank environment threshold values fall back to these defaults; they do not disable health evaluation in this version.

Health is calculated for each displayed record using the **current** limits. Changing limits can change badges on older records. An old OK badge does not prove a device is online now, its battery is healthy, or its sensors are accurate. There is no automatic alert, SMS, or email notification implemented for Not OK. Operators must check the reading time and investigate abnormal values.

`systemTemp` must be sent as a numeric value and enabled in Allowed parameters. It is shown as device-health information and excluded from CSV exports. The provided dummy-data scripts simulate it; they do not measure board temperature.

### UTC and Bangladesh time

The application displays and exports UTC. Bangladesh time is UTC+6. For example, 06:00 UTC is 12:00 noon in Bangladesh. Device timestamps with an explicit offset are normalized to UTC. If firmware omits a timestamp, delayed delivery will be recorded at server receipt time rather than the original sampling time.

## 9. Exporting data

1. Open **CSV export**.
2. Choose **Last 24 hours**, **Last 7 days**, **Last 30 days**, or enter a custom range.
3. Enter dates and times in **UTC**, even if your computer uses Bangladesh local time.
4. Ensure the end is later than the start.
5. Select **Download CSV** and wait for the browser download.
6. Open `telemetry.csv` from your browser's download location. Keep an unchanged copy if it is needed for reporting.

The start is included and the end is excluded: `start <= timestamp < end`. To export the Bangladesh calendar day 30 September 2026, enter start `2026-09-29 18:00` UTC and end `2026-09-30 18:00` UTC.

### CSV structure

```csv
timestamp,device_id,device_name,humidity(%),temperature(°C)
2026-09-30T06:00:00+00:00,MGRV_001,Riverside station 1,65.2,27.5
```

The example contains simulated data. Actual columns depend on configured and historically stored parameters. The file has `timestamp`, `device_id`, `device_name`, followed by alphabetically ordered parameter columns. Units appear in parentheses when available. Each row represents one transmission with at least one exportable value, ordered by timestamp and registry ID.

- Exports include all devices in the date range; there is no device-selection filter.
- Registry ID, received-at time, `systemTemp`, and the health badge are not included.
- A message containing only `systemTemp` produces no CSV data row.
- A blank cell means that record has no stored value for that parameter.
- Columns can appear even if they are empty in the selected interval, because column discovery includes historical parameter names.
- No matching readings results in a header-only file.
- Exporting does not delete or modify stored records.

Use your spreadsheet application's UTF-8 import option if unit symbols display incorrectly. Preserve device IDs as text when they contain leading zeros. Some names beginning with spreadsheet formula characters are exported with a leading apostrophe for safer text handling. Split very large exports into smaller time ranges if the browser struggles to download them. There is no CSV import/restore facility in the dashboard.

## 10. Routine operator checklist

**Each working day:** sign in; refresh Stored data; check the latest expected timestamp for each active station; investigate missing intervals and Not OK/Unknown health; record incidents with UTC time and Device ID. At one report per hour, “no new data for several minutes” is normally expected.

**Before changing configuration:** record the previous parameter names/units or station status; confirm the intended effect on all devices; get a verified backup before destructive changes.

**Each reporting period:** export the required UTC range; check expected devices and obvious gaps; save the original CSV with the report's date range; report unexplained missing values to the technician.

**After maintenance:** confirm a new transmission reaches the table and export, rather than relying only on a running-container status.

## 11. Troubleshooting for users

| Symptom | First checks / action |
|---|---|
| Website will not open | Confirm URL, internet/VPN requirement, and whether other users can connect; contact infrastructure support |
| Browser certificate warning | Confirm the correct hostname; ask administrator to repair the certificate rather than bypassing the warning |
| Invalid username/password | Use dashboard credentials, not device/SSH credentials; check typing; request administrator reset |
| Redirected to login | Session may have expired or been invalidated; sign in again |
| Page could not load | Use Try again; confirm network; provide page and timestamp to support |
| Device absent from table | Check registration limit, duplicate ID, and whether registration returned an error |
| Device exists but no readings | Refresh; check device enabled state, exact MQTT topic/username, approved keys, and technician's connection logs |
| Only some parameters appear | Compare case-sensitive keys with whitelist; missing, disabled, or never-sent fields are not stored |
| Health Unknown | Verify enabled `systemTemp` is present in the actual transmission; ask administrator to check configuration |
| Health OK but device is offline | Badge describes that historical transmission; inspect its timestamp |
| Empty CSV | Check UTC range and boundary dates; systemTemp-only records are excluded |
| Time differs by six hours | UI uses UTC; Bangladesh is UTC+6 |
| Data appears missing while paging | See section 18; verify using a date-range CSV export |
| Accidental deletion | Stop further changes and contact administrator immediately; recovery requires an appropriate backup |

Support reports should include the page/action, Device ID, UTC incident time, exact visible error, last successful reading, and a screenshot with passwords hidden. Do not send `.env`, password columns, private keys, or authentication tokens.

## 12. Device integration and MQTT

This section is for firmware and integration technicians.

| Setting | Required value |
|---|---|
| Broker | Confirmed MQTT hostname/IP from installation record |
| Port / transport | Match configured listener; dashboard HTTPS is separate |
| Username | Exact registered Device ID |
| Password | That device's broker password |
| Topic | `devices/<DEVICE_ID>/telemetry` |
| Publish QoS | Use QoS 1 for acknowledgment and retries |
| Retain | `false` |
| Message size | At most 16,384 bytes |

Example payload:

```json
{
  "message_id": "f2e86d8d-b575-493d-8753-649e6b84cda4",
  "timestamp": "2026-09-30T12:00:00+06:00",
  "values": {
    "temperature": 27.5,
    "humidity": 65.2,
    "systemTemp": 41.0
  }
}
```

Generate a new UUID for each new measurement and reuse it only when retrying that exact measurement. The current backend accepts any 1–36-character message ID, but UUIDs satisfy the documented integration convention and avoid counter reuse after reboot. Duplicate `(device_id, message_id)` values are ignored; they do not overwrite readings.

`timestamp` is optional. If provided, it must include `Z` or an explicit timezone offset. `values` must contain 1–100 numeric fields. Numeric strings, booleans, null, arrays, objects, NaN, infinity, extra envelope fields, and duplicate JSON keys are invalid. One invalid value can reject the complete message, even if that key would not have been whitelisted.

Broker authentication, topic authorization, ingestion, and database storage are separate stages. A PUBACK is not a database receipt. Use worker logs and a displayed record to verify end-to-end success. Publish without retention; retained deliveries are deliberately ignored. Firmware must handle network outages and persist pending samples if recovery across power loss is required. The server cannot reconstruct readings that a device never delivered.

## 13. Testing without a physical sensor

Use a separately registered test device when a registration slot is available. Tests add real records to the selected database. Enable `temperature`, `humidity`, and `systemTemp` first, and record the test time range so test data can be distinguished from field data.

On a PC with Python installed, from the project directory:

```powershell
python -m pip install "paho-mqtt>=2,<3"
python scripts/test_vps.py --host YOUR_MQTT_HOST --device TEST_001
```

The script sends six messages at ten-second intervals by default. If `DEVICE_MQTT_PASSWORD` is blank, it prompts privately for the device password. If it contains a value, verify locally that it belongs to the selected device; do not commit that value or distribute a configured copy of the script.

For a broker configured for verified TLS:

```powershell
python scripts/test_vps.py --host YOUR_MQTT_HOST --device TEST_001 --tls --port 8883
```

Add `--ca PATH_TO_CA.pem` only when a custom CA is required. Do not use an HTTPS URL as the MQTT host. Port 8883 is a convention, not proof that a TLS listener exists.

Useful options: `--count 3`, `--interval 10`, and `--dry-run`. Dry run prints payloads without contacting the server. `[CONNECTED]` confirms the broker accepted credentials. `[ACK]` confirms broker acknowledgment. Finally refresh Stored data and download a CSV spanning the test to confirm storage and export.

The Arduino sketches in `firmware/` also generate simulated data. Their default fast interval is for testing, not hourly field operation. Their `systemTemp` is random test data, not a measurement of actual board temperature.

## 14. Infrastructure and deployment

This section is for authorized infrastructure administrators. Operators normally need only the browser.

| Compose service | Purpose | Normal lifecycle |
|---|---|---|
| `proxy` | Caddy HTTPS endpoint and forwarding to the API | Running |
| `api` | FastAPI dashboard, authentication, administration, export | Running |
| `worker` | MQTT subscriber, validation, whitelist filtering, database writes | Running |
| `db` | PostgreSQL data store | Running |
| `mosquitto` | MQTT broker and device authentication | Running |
| `migrate` | Alembic database schema changes | Exits after successful execution |

An exited migration container with code 0 is expected. These are six services, not six separate application codebases: API, worker, and migrations share the application image.

The current Compose file publishes HTTP 80, HTTPS 443, and MQTT 1883. API port 8000 and PostgreSQL are internal to the Docker network. `Caddyfile` determines the web hostname. Device MQTT TLS is not automatically enabled by web HTTPS or by setting the worker's `MQTT_TLS` variable.

The latest supplied VPS inventory also contains cPanel, mail, DNS, MariaDB, PHP, and provider services. Do not assume they are unused. Coordinate ports 80/443, DNS ownership, backups, and maintenance with the infrastructure team before running installers or changing services. Standard shared cPanel access alone is insufficient for this Compose stack.

### Capacity

Six hourly devices represent a light ingestion rate. A previously supplied VM snapshot showed roughly 175 MiB of combined container memory and 2.26% of one CPU core at that instant. This was not a peak-load test or a measurement from the current VPS. An isolated VM allocation of 2 vCPU, 4 GB RAM, and about 50 GB SSD was suggested as comfortable headroom; it is not continuous application consumption. Measure actual growth, export load, Docker image use, and host overhead. Keep backups on separate storage.

### Configuration to verify

| Variable / file | Meaning |
|---|---|
| `.env` | Private runtime configuration; never include in a public repository |
| `POSTGRES_PASSWORD` | PostgreSQL credential used by Compose |
| `MQTT_PASSWORD` | Collector credential; not an individual device password |
| `MAX_DEVICES` | 1–10 registered devices; default 10 |
| `SESSION_TTL_HOURS` | 1–168 hours; default 12 |
| `SECURE_COOKIES` | Set true for the HTTPS deployment |
| `SYSTEM_TEMP_MIN`, `SYSTEM_TEMP_MAX` | Inclusive limits; defaults 10 and 50; blank uses defaults |
| `SYSTEM_TEMP_UNIT` | Health rule label; also maintain the parameter display unit consistently |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_TLS`, `MQTT_CA_FILE` | Worker-to-broker connection; Compose sets host to `mosquitto` |
| `MQTT_CLIENT_ID` | Stable collector client ID; avoid two active collectors sharing it |
| `Caddyfile` | Web hostname and reverse proxy configuration |
| `docker/mosquitto.conf`, `docker/acl` | Broker listener, persistence, authentication and topic permissions |
| `secrets/mosquitto.passwd` | Broker password hashes; readable by broker and writable by the authorized provisioning process |

Older deployment notes mention a public `API_PORT`; the current Compose exposes the website through Caddy on 80/443. Confirm effective configuration rather than relying on an old installer prompt. Do not print `docker compose config` with expanded secrets into support tickets.

For a fresh installation, the infrastructure team should select a reviewed release, install Docker/Compose, provision private configuration and broker credentials, verify mount permissions, configure DNS/TLS/network rules, run migrations and services, create accounts, and perform section 19. Review `install.sh` before use; it makes host and account changes and is not a routine maintenance command.

## 15. Administrator operations

Commands below run over SSH on the server from the confirmed installation directory. They are examples, not evidence that the live VPS has been checked.

### Inspect services and resource use

```bash
cd /opt/iot-telemetry-hub
docker compose ps -a
docker stats --no-stream
docker compose logs --tail=100 api worker mosquitto proxy
df -h /
free -h
```

Use `docker compose logs -f worker` to follow collection; press Ctrl+C to stop following logs without stopping the worker. Do not share unreviewed logs containing credentials or private sensor data.

### Check API readiness

```bash
docker compose exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"
```

`/health/live` checks that the API process responds. `/health/ready` checks database access to the admin schema. Neither proves that the broker is reachable, devices are connected, the collector subscription is working, or every latest migration is applied. Complete the publish-to-dashboard check as well.

### Create or reset dashboard accounts

```bash
docker compose exec api python -m app.cli operator1
```

Here `operator1` is the intended username. Enter a 12–1024-character password at the private prompts. Accounts are administrators with shared access.

```bash
docker compose exec api python -m app.cli operator1 --reset-password
```

Reset invalidates that user's existing sessions. There is no web-based account deletion or role assignment interface. Follow the support process for account removal.

### Restart a component

After confirming the impact, restart only the relevant component, for example:

```bash
docker compose restart worker
```

A restart interrupts that component and does not apply changed environment variables. After an approved `.env` change, recreate affected application containers:

```bash
docker compose up -d api worker
```

Verify readiness and a new sample afterward. Never use volume deletion or Docker pruning as a first response to an application error.

### Diagnose missing readings

Check in this order: device network → TCP/TLS connectivity → broker credentials/topic ACL → worker subscription → payload validation → enabled device/parameters → database write → UTC display/export interval. Worker outcomes include accepted, duplicate, device_rejected, and invalid-message rejection. A zero stored-value count can mean no allowed values matched. A broker connection error before authentication is not evidence of a wrong password.

## 16. Backups, recovery, and upgrades

### What must be protected

A recoverable installation needs the PostgreSQL database, matching broker credentials and configuration, `.env`, Compose/Caddy configuration, release identity, and an appropriate plan for broker persistence/certificates. A CSV does not include accounts, device credentials, complete schema, or `systemTemp`, so it cannot replace a database backup.

Keep backups outside the active VPS as well as any local copy. Restrict access because database dumps include sensitive records and device credentials. Agree on schedule, retention, encryption, restore ownership, and recovery objectives with the client.

### Existing scripts and limitations

`deploy/backup.sh` writes compressed dumps to `/opt/iot-telemetry-hub/backups` and deletes matching local dumps older than seven days. It does not upload them off-server or back up configuration. No schedule should be assumed merely because the script exists. Its pipeline lacks `pipefail`, so a reported success does not reliably prove `pg_dump` succeeded.

`deploy/restore.sh` prompts, stops API/worker, drops the public database schema, restores a dump, and starts the applications. It is destructive. Its pipeline and SQL error handling are not sufficient to certify success. **Do not make this script the client's only recovery procedure without correcting and testing it.**

### Safer manual database backup example

Run in Bash on the server, using the actual project directory. This creates a new dump; it does not delete application data.

```bash
cd /opt/iot-telemetry-hub
set -euo pipefail
umask 077
mkdir -p backups
backup_file="backups/telemetry_$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db pg_dump -U telemetry -d telemetry -Fc > "$backup_file"
test -s "$backup_file"
docker compose exec -T db pg_restore --list < "$backup_file" > /dev/null
printf 'Database archive created: %s\n' "$backup_file"
```

This `.dump` archive uses custom format and is **not input for the existing `.sql.gz` restore script**. Listing the archive checks readability; only a restore rehearsal verifies that data can actually be recovered. Copy it off-server through the client's approved secure process, and protect matching configuration separately. Stop configuration changes while collecting matching database/broker credential backups.

### Recovery sequence for the administrator

1. Record the incident, intended restore point, and expected data loss; obtain the data owner's approval.
2. Preserve the current database and configuration before replacement if possible.
3. Restore into an isolated test instance first, using compatible PostgreSQL and application versions. For custom-format dumps, use `pg_restore` with error stopping; do not pipe them into `psql`.
4. Check accounts, device/parameter counts, representative record values, timestamps, and MQTT credential consistency.
5. Schedule a maintenance window, stop new writes, and perform the approved production recovery procedure.
6. Validate readiness, login, new MQTT ingestion, exports, and configuration before reopening access.
7. Record results and retain the pre-recovery backup. Expect possible loss of records newer than the chosen backup.

### Upgrades and rollback

Choose a reviewed release rather than blindly pulling a moving branch. Record the previous Git revision, image versions, database migration revision, and backup location. Test the release on staging, take a verified backup, then build/run the approved revision during the agreed window. `deploy/start.sh` rebuilds and starts services; schema migrations can change the database. Run the full acceptance check afterward.

Rolling back code alone may not undo a database migration. An authorized administrator must determine schema compatibility or restore the matched pre-upgrade backup. Never delete persistent volumes during routine upgrades. Rehearse rollback before it is needed.

## 17. API reference

Interactive documentation is available at `/docs` on deployments exposing it. Authentication is required for administration and data endpoints. The API accepts a login-issued bearer token or the browser session cookie. Cookie-authenticated modifying requests require `X-Requested-With: telemetry-ui`. Tokens and passwords must not be pasted into tickets.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/login` | Username/password login; returns token and sets session cookie |
| POST | `/api/auth/logout` | Invalidate current session |
| GET | `/api/auth/me` | Current account and workspace settings |
| GET / PUT | `/api/profile` | Read/update current profile |
| GET | `/api/summary` | Aggregate counts and latest receipt timestamp |
| GET / POST | `/api/devices` | List/register devices |
| PUT / DELETE | `/api/devices/{device_id}` | Update/delete device |
| DELETE | `/api/devices/{device_id}/telemetry` | Permanently clear one device's data and receipts |
| GET / POST | `/api/parameters` | List/create allowed parameters |
| PUT / DELETE | `/api/parameters/{name}` | Update/remove a parameter |
| GET | `/api/telemetry` | Individual numeric readings; limit 1–1000 and optional before_id |
| GET | `/api/telemetry/records` | Transmission matrix; limit 1–100, before_id, next_cursor |
| GET | `/api/telemetry/export?start=...&end=...` | UTC-aware date-range CSV |
| GET | `/health/live`, `/health/ready` | Process/database checks |

Typical responses: 401 unauthenticated/expired; 403 cookie request header requirement; 404 missing resource; 409 duplicate or capacity conflict; 422 invalid input/date range; 500 server/provisioning failure; 503 failed database readiness. Use API schema for exact request fields. There is no telemetry-upload HTTP endpoint; devices publish via MQTT.

## 18. Known limitations and release checks

These items are important for interpreting results and must not be described to the client as completed features:

- No charts, map, email/SMS alerts, device control, per-user roles, or automatic sensor calibration are implemented.
- Data refresh is manual; health badges are historical calculations, not live connectivity indicators.
- There is no automatic guarantee of one-year retention, off-server backups, or lossless data delivery. Establish operational policies and device recovery behavior.
- The source currently requests 13 records, displays only 12, and uses the API cursor after the thirteenth. This can omit a record from page traversal and can hide a final thirteenth record. **Use CSV to verify interval completeness and resolve this before sign-off of dashboard completeness.**
- Health defaults are 10–50 in current code, despite some older notes saying blank thresholds mean Unknown. Parameter names/units and limits need client approval.
- MQTT password generation updates a mounted broker file when available; a missing file can still leave a registration without a functioning broker credential. Registration, publish, and revoke must be tested on the actual installation.
- The backup and restore scripts have the validation limitations in section 16. Presence of scripts or success text is not evidence of a tested recovery plan.
- Broker/worker health is not covered by API readiness alone. Monitor collection separately.
- The server uses current device names, current unit labels, and current temperature thresholds when showing historical data.
- Older `docs/mqtt-contract.md` CSV examples describe a long format. Current exports are wide format as documented here; the code accepts string message IDs while the integration convention remains UUID.

This manual is not a new production-readiness audit. Verify the deployed version and complete the open release checks with the application maintainer.

## 19. Client acceptance and handover

Record a date, evidence, owner, and pass/fail result for each item:

| Check | Acceptance criterion | Result / owner |
|---|---|---|
| URL and HTTPS | Confirmed URL loads without certificate warning | Pending |
| Accounts | Each authorized operator can sign in/out; reset process documented | Pending |
| Device registration | Unique test device is enabled and has working broker credentials | Pending |
| Parameter policy | Approved names, units, and global scope agreed | Pending |
| Ingestion | New valid transmission creates expected stored values | Pending |
| Deduplication | Repeating same message ID does not add another record | Pending |
| Filtering | Unapproved field is not stored; disabled station rejected | Pending |
| Health | Approved range and actual systemTemp produce expected badge | Pending |
| CSV | Correct date boundaries, values/units, and systemTemp exclusion | Pending |
| Pagination | More than one page checked without skipped records | Pending |
| Mobile use | Login, navigation, horizontal table scrolling, export checked | Pending |
| Network | Devices reach protected MQTT endpoint; DB is not public | Pending |
| Recovery | Off-server backup restored successfully on isolated instance | Pending |
| Maintenance | Version, rollback process, support owner, alert ownership recorded | Pending |
| Test cleanup | Test publishing stopped; only approved test data cleanup performed | Pending |

Handover pack: this guide, deployment release identifier, installation/contact record, approved device list and parameter/unit list, private credential transfer, network/DNS details, backup/restore evidence, maintenance ownership, and an agreed list of outstanding issues. Store signed acceptance separately from secret credentials.

## 20. Glossary

| Term | Meaning |
|---|---|
| Device ID | Permanent identifier for a sensor station; also its MQTT username |
| Parameter | Named numeric measurement such as temperature |
| Whitelist | Enabled parameter names the collector is allowed to store |
| Transmission / record | One accepted message with at least one approved stored value |
| Reading | One numeric parameter value within a transmission |
| Message ID | Device-generated identifier used to detect retries/duplicates |
| Registry ID | Database-generated identifier shown in the transmission table |
| MQTT broker | Service accepting device messages and forwarding them to subscribers |
| Worker / collector | Background process validating and storing MQTT readings |
| QoS 1 / PUBACK | MQTT acknowledgment/retry mechanism; not confirmation of database storage |
| UTC | Common timestamp reference; Bangladesh time is UTC+6 |
| CSV | Downloadable text table for reporting and analysis |
| Docker Compose | Definition used to run the application's cooperating containers |
| Migration | Versioned database schema change applied during deployment |
| Restore | Recovering database/configuration from a verified backup |

### Maintainer source map

This guide was checked against `app/api.py`, `app/config.py`, `app/schemas.py`, `app/health.py`, `app/cli.py`, `app/security.py`, `app/ingestion.py`, `app/static/app.js`, login templates, `compose.yaml`, `Caddyfile`, and deployment/test scripts. Screen labels, release settings and site-specific values should be reviewed whenever those sources change.
