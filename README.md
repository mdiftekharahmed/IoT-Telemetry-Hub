# IoT Telemetry Hub

A small backend for up to ten MQTT devices, with an authenticated management API,
global parameter whitelist, persistent telemetry and date-range CSV export.

**Current stage:** working backend and responsive admin UI, verified locally.
Production deployment is a later milestone. The frontend uses plain HTML, CSS and
vanilla JavaScript: no React, UI library, Node/npm or frontend build step.

- [Original scope](iot_data_logging_project_plan.md)
- [Tracked roadmap](ROADMAP.md)
- [MQTT contract](docs/mqtt-contract.md)
- [UI design notes](docs/ui-design-brief.md)

## Templates in this repository

- `app/templates/login.html`: split login layout.
- `app/templates/app.html`: shared admin workspace shell.
- `app/static/styles.css`: desktop/mobile layouts and component styling.
- `app/static/app.js`: four authenticated pages and their API interactions.
- `app/static/login.js`: sign-in and password visibility behavior.
- `app/static/icons.svg`, `favicon.svg`: local SVG assets.

Everything is served by FastAPI and packaged in the application image. No remote
fonts, CDNs or design services are required. The user-provided screenshots informed
the navy/emerald palette, sidebar, login composition and table styling.

## Installation

To install and run the full backend (including the PostgreSQL database, MQTT broker, and API) on a Linux server (e.g., Ubuntu), use the automated `install.sh` script.

Run the following command on your server (as a user with sudo privileges):

```bash
curl -fsSL https://raw.githubusercontent.com/mdiftekharahmed/IoT-Telemetry-Hub/main/install.sh | bash
```

The installation script will:
1. Install Docker and its dependencies
2. Clone this repository
3. Help you configure passwords and environment variables
4. Build the Docker images and start all services

Once running, the script will provide you with the final command to create your admin account. For manual setup or more detailed deployment instructions, see the [Deployment Guide](deploy/README.md).

## Native Windows development

Python 3.12+ is required; development is currently tested with Python 3.14.
Run these commands from this repository in PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\telemetry-admin.exe admin
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

The admin command prompts for a password; no default admin is created. To reset a
password and revoke that admin's existing sessions:

```powershell
.\.venv\Scripts\telemetry-admin.exe admin --reset-password
```

SQLite stores local data in ignored `telemetry.db`. It is not the production database.
Use one API process in SQLite mode. Schema creation is explicit through Alembic;
starting the server never silently creates or changes tables.

Open the [admin UI](http://127.0.0.1:8000/login) and sign in with the admin you created.
The browser uses an HttpOnly session cookie; JavaScript never stores a bearer token
in localStorage. Browser writes require a custom same-origin request header, and
cookies use SameSite=Strict. Set `SECURE_COOKIES=true` when serving through HTTPS.

For API-only usage, open [API documentation](http://127.0.0.1:8000/docs).
Call `POST /api/auth/login`,
copy its `access_token`, then use **Authorize** with that token to try protected APIs.
The login body is `{"username":"admin","password":"your chosen password"}`.
Tokens expire after 12 hours by default. Log out with `POST /api/auth/logout`.

## Local design preview

This uses a separate SQLite database with clearly labeled synthetic data. It does
not populate or alter your real `telemetry.db` or PostgreSQL database.

```powershell
.\.venv\Scripts\python.exe scripts/seed_demo.py
$env:DATABASE_URL = 'sqlite:///./demo.db'
$env:DEMO_MODE = 'true'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Visit [the preview](http://127.0.0.1:8000/login), using **demo / local-preview-only**.
Keep this preview bound to loopback. The seed script refuses to overwrite an existing
`demo.db`. Use a fresh terminal for normal development so preview environment values
are not inherited by the real application.

## API surface

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/auth/login` | Exchange username/password for a bearer session |
| POST | `/api/auth/logout` | Revoke the current session |
| GET | `/api/auth/me` | Current admin |
| GET | `/api/summary` | Device, parameter and stored-reading counts |
| GET / PUT | `/api/profile` | View/edit your own name and contact email |
| GET / POST | `/api/devices` | List/register devices |
| PUT | `/api/devices/{device_id}` | Set name and enabled status |
| GET / POST | `/api/parameters` | List/add global whitelist entries |
| PUT / DELETE | `/api/parameters/{name}` | Enable/disable or remove an entry |
| GET | `/api/telemetry?limit=100&before_id=123` | Read telemetry, newest ingested first |
| GET | `/api/telemetry/export?start=...&end=...` | Download CSV for `[start, end)` |
| GET | `/health/live`, `/health/ready` | Process and database readiness |

Only login, health, the UI shell/static assets and API documentation are public.
All stored data and management APIs require authentication. There is intentionally no HTTP
telemetry write endpoint: all device input uses the MQTT ingestion service.
The API readiness endpoint checks the database, not broker/collector readiness.

## User details

User details live in **`user_profiles`**, a separate table in the same database as
telemetry. Its `username` is a one-to-one foreign key to `admins.username`; fields
are `full_name`, `email`, `created_at` and `updated_at`. Password hashes remain only
in `admins`, and login sessions remain in `admin_sessions`.

Click your identity at the bottom of the sidebar to edit your profile. Full name
and email are optional; email is contact information, not a verified login identity
or password-reset destination. Every admin can access only their own profile.
Migration `0002` adds blank profiles for existing accounts without changing credentials.

## Docker development stack

Requires Docker Engine/Desktop with Compose. This configuration is for development,
not public production hosting. PostgreSQL has no published port; API and broker bind
only to `127.0.0.1`. API and worker use the same image in separate processes.

1. Copy `.env.example` to `.env` if needed. Set unique `POSTGRES_PASSWORD` and
   `MQTT_PASSWORD` values. For the database URL, use a randomly generated hex password
   (at least 32 characters) so no URL escaping is needed. Compose provides its own
   PostgreSQL URL, overriding the native SQLite setting.
2. Create a broker password file. In PowerShell:

   ```powershell
   New-Item -ItemType Directory -Force secrets
   docker run --rm -it --mount "type=bind,source=$($PWD.Path)/secrets,target=/secrets" eclipse-mosquitto:2 mosquitto_passwd -c /secrets/mosquitto.passwd collector
   docker run --rm -it --mount "type=bind,source=$($PWD.Path)/secrets,target=/secrets" eclipse-mosquitto:2 mosquitto_passwd /secrets/mosquitto.passwd sensor-01
   ```

   The collector password must match `MQTT_PASSWORD`. The device gets its own
   password. Do not repeat `-c` when adding devices: it overwrites the file. On Linux,
   the mounted file must be readable by the broker user (container UID 1883).
3. Start and initialize:

   ```powershell
   docker compose up --build -d
   docker compose exec api telemetry-admin admin
   docker compose logs -f worker
   ```

   The one-shot migration service must succeed before the API and collector start.
4. In the API docs, log in, register `sensor-01`, and add the `temperature` parameter.
   API device registration and broker credential provisioning are separate steps.
5. Wait for the worker's `MQTT telemetry subscription ready` log, then publish a
   sample from another terminal using this repository's virtual environment:

   ```powershell
   $env:MQTT_USERNAME = 'sensor-01'
   # Set MQTT_PASSWORD privately to the device broker password for this terminal.
   .\.venv\Scripts\python.exe scripts/publish_sample.py --temperature 24.2
   ```

6. Check `/api/telemetry` and export a time interval containing the reading.

Native Python can run the collector with `telemetry-worker` when a broker is
available. Configure `MQTT_HOST`, username/password and optional `MQTT_TLS` first.
Run only one collector per deployment using a stable `MQTT_CLIENT_ID`.

Named volumes preserve PostgreSQL and Mosquitto data across container recreation.
Do not use `docker compose down -v` unless you intend to delete that stored data.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check app migrations scripts tests
.\.venv\Scripts\ruff.exe format --check app migrations scripts tests
.\.venv\Scripts\alembic.exe check
```

Tests use temporary SQLite databases created through the actual migration, plus
mocked MQTT callbacks. They cover authentication, whitelist enforcement, device
limits, malformed messages, deduplication, UTC handling, CSV boundaries and failed
transaction acknowledgement behavior. They do not replace live PostgreSQL/broker
and container-restart testing, which is tracked in the roadmap.

## Before production

Complete the roadmap's VM verification and deployment tasks: login rate limiting,
HTTPS with secure cookies, MQTT TLS/private access, volume sizing,
backup/restore verification and container version pinning. The current login API
should stay local/private until rate limiting is configured. Secrets belong in the
ignored `.env` and `secrets/` directory, never in source control or Docker images.

Implementation references: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/),
[Paho manual acknowledgements](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html),
and [SQLAlchemy streaming queries](https://docs.sqlalchemy.org/en/20/orm/queryguide/api.html).
