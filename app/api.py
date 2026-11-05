"""ColdChain + legacy IoT Telemetry Hub – unified FastAPI application."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import secrets
import string
import subprocess
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import (
    Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

import app.audit as audit_mod
import app.alerts as alert_mod
from app.budget_engine import reset_discard, update_exposure
from app.config import Settings
from app.db import build_engine, session_factory
from app.device_registry import db_device_secrets, generate_secret, get_device_secret
from app.health import device_health
from app.models import (
    Admin, AdminSession, Alert, AuditLog, Batch, BatchMovement, Device,
    Fridge, IngestedMessage, MlPrediction, Nonce, Parameter, Reading,
    RelocationSuggestion, SecurityEvent, Telemetry, TelemetryRecord,
    User, UserProfile, utcnow,
)
from app.schemas import (
    CcDeviceCreate, CcDeviceUpdate, DeviceCreate, DeviceCreateOut, DeviceOut, DeviceUpdate,
    FridgeCreate, FridgeUpdate, Login, ParameterCreate, ParameterOut, ParameterUpdate,
    ProfileOut, ProfileUpdate, RefreshRequest, TelemetryOut, as_utc,
)
from app.security import (
    DUMMY_HASH, PharmOrAdmin, AdminOnly, AnyRole,
    create_session, create_tokens, decode_access_token,
    decode_refresh_token, password_hasher, token_digest,
)

bearer = HTTPBearer(auto_error=False)

# ─────────────────────────────────────────────────────────────────────────────
# WebSocket connection manager
# ─────────────────────────────────────────────────────────────────────────────

class LiveFeedManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            self._connections = [c for c in self._connections if c is not ws]

    async def broadcast(self, data: dict):
        async with self._lock:
            dead = []
            for ws in self._connections:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.append(ws)
            self._connections = [c for c in self._connections if c not in dead]


_live = LiveFeedManager()


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def db_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as db:
        yield db


def authenticated(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(db_session)],
) -> AdminSession | User:
    """Cookie/bearer session for legacy admin or ColdChain JWT user."""
    token = credentials.credentials if credentials else request.cookies.get("telemetry_session")
    if not credentials and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("X-Requested-With") != "telemetry-ui":
            raise HTTPException(403, "Same-origin request header required")
    if token:
        # Check ColdChain JWT
        try:
            secret = request.app.state.settings.coldchain_jwt_secret
            payload = decode_access_token(token, secret)
            user = db.get(User, int(payload["sub"]))
            if user and user.active:
                return user
        except Exception:
            pass

        # Check legacy AdminSession
        session = db.get(AdminSession, token_digest(token))
        if session and as_utc(session.expires_at) > utcnow():
            return session

    raise HTTPException(401, "Authentication required",
                        headers={"WWW-Authenticate": "Bearer"})


DB   = Annotated[Session, Depends(db_session)]
Auth = Annotated[AdminSession, Depends(authenticated)]


def date_range(
    start: Annotated[AwareDatetime, Query()],
    end:   Annotated[AwareDatetime, Query()],
) -> tuple[datetime, datetime]:
    start, end = as_utc(start), as_utc(end)
    if start >= end:
        raise HTTPException(422, "start must be before end")
    return start, end


def commit(db: Session):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A record with that identifier already exists") from exc


def get_user_or_404(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    return u


def fridge_or_404(db: Session, fridge_id: int) -> Fridge:
    f = db.get(Fridge, fridge_id)
    if not f:
        raise HTTPException(404, "Fridge not found")
    return f


def batch_or_404(db: Session, batch_id: int) -> Batch:
    b = db.get(Batch, batch_id)
    if not b:
        raise HTTPException(404, "Batch not found")
    return b


def _reading_dict(r: Reading) -> dict:
    return {
        "id": r.id, "device_id": r.device_id, "seq": r.seq,
        "ts": as_utc(r.ts).isoformat(),
        "temp_c": r.temp_c, "door_open": r.door_open,
        "door_open_s": r.door_open_s, "compressor_on": r.compressor_on,
        "lockout_s": r.lockout_s, "power_source": r.power_source,
        "mains_present": r.mains_present, "battery_pct": r.battery_pct,
        "battery_v": r.battery_v, "state": r.state,
        "red_latched": r.red_latched, "sim_mode": r.sim_mode,
        "ingested_at": as_utc(r.ingested_at).isoformat(),
    }


def _batch_dict(b: Batch) -> dict:
    return {
        "id": b.id, "code": b.code, "vaccine_name": b.vaccine_name,
        "qty": b.qty,
        "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
        "fridge_id": b.fridge_id,
        "exposure_weighted_min": round(b.exposure_weighted_min, 2),
        "remaining_pct": round(b.remaining_pct, 1),
        "status": b.status, "discard_latched": b.discard_latched,
        "qr_token": b.qr_token,
        "created_at": as_utc(b.created_at).isoformat(),
    }


def _fridge_dict(f: Fridge, latest: Reading | None) -> dict:
    return {
        "id": f.id, "name": f.name, "capacity_slots": f.capacity_slots,
        "location": f.location, "device_id": f.device_id,
        "latest": _reading_dict(latest) if latest else None,
    }


def _latest_reading(db: Session, device_id: str | None) -> Reading | None:
    if not device_id:
        return None
    return db.scalar(
        select(Reading).where(Reading.device_id == device_id)
        .order_by(Reading.ts.desc()).limit(1))


def _bind_device_fridge(device: Device, fridge: Fridge) -> None:
    """Keep the two-way device↔fridge binding consistent."""
    device.fridge_id = fridge.id
    fridge.device_id = device.device_id


def _unbind_device_fridge(device: Device | None, fridge: Fridge | None) -> None:
    if device is not None:
        device.fridge_id = None
    if fridge is not None:
        fridge.device_id = None


def _sync_mosquitto(db: Session, device_id: str, secret: str | None) -> None:
    """Best-effort mosquitto credential sync (no-op outside the deployed VM)."""
    pw_file = Path("/secrets/mosquitto.passwd")
    if not pw_file.exists():
        return
    try:
        cmd = (["mosquitto_passwd", "-D", str(pw_file), device_id] if secret is None
               else ["mosquitto_passwd", "-b", str(pw_file), device_id, secret])
        subprocess.run(cmd, check=True)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Failed to update mosquitto password: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Application factory
# ─────────────────────────────────────────────────────────────────────────────

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine   = build_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        import os
        import logging as _log
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            with app.state.sessions() as _seed_db:
                n = seed_system_parameters(_seed_db)
                if n:
                    _log.getLogger(__name__).info("Seeded %d system parameters into DB", n)
        yield
        engine.dispose()

    app = FastAPI(title="ColdChain – IoT Telemetry Hub", version="0.2.0", lifespan=lifespan)
    app.state.sessions = session_factory(engine)
    app.state.engine   = engine
    app.state.settings = settings
    app.state.live     = _live

    assets = Path(__file__).parent
    app.mount("/static", StaticFiles(directory=assets / "static"), name="static")

    # ── Security headers middleware ────────────────────────────────────────────
    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"]         = "same-origin"
        response.headers["X-Frame-Options"]          = "DENY"
        if not request.url.path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self' ws: wss:; "
                "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # ── Legacy SPA pages ──────────────────────────────────────────────────────
    @app.get("/login",      include_in_schema=False)
    def login_page(): return FileResponse(assets / "templates" / "login.html")

    @app.get("/",           include_in_schema=False)
    @app.get("/devices",    include_in_schema=False)
    @app.get("/parameters", include_in_schema=False)
    @app.get("/data",       include_in_schema=False)
    @app.get("/export",     include_in_schema=False)
    def admin_page(): return FileResponse(assets / "templates" / "app.html")

    # ── Health ────────────────────────────────────────────────────────────────
    @app.get("/health/live",  tags=["health"])
    def live(): return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready(db: DB):
        try:
            db.execute(select(Admin.username).limit(1))
        except SQLAlchemyError as exc:
            import traceback; traceback.print_exc()
            raise HTTPException(503, f"Database unavailable or migrations pending: {exc}") from exc
        return {"status": "ok"}

    # =========================================================================
    # Auth – legacy (cookie session for old SPA)
    # =========================================================================

    @app.post("/api/auth/login", tags=["auth"])
    def login(body: Login, db: DB, response: Response):
        admin = db.get(Admin, body.username)
        valid = password_hasher.verify(body.password, admin.password_hash if admin else DUMMY_HASH)
        if not admin or not valid:
            raise HTTPException(401, "Invalid username or password")
        response.headers["Cache-Control"] = "no-store"
        token = create_session(db, admin.username, settings.session_ttl_hours)
        response.set_cookie("telemetry_session", token, httponly=True,
                            secure=settings.secure_cookies, samesite="strict",
                            max_age=settings.session_ttl_hours * 3600)
        return {"access_token": token, "token_type": "bearer",
                "expires_in": settings.session_ttl_hours * 3600}

    @app.post("/api/auth/logout", status_code=204, tags=["auth"])
    def logout(auth: Auth, db: DB):
        db.delete(auth); db.commit()
        response = Response(status_code=204)
        response.delete_cookie("telemetry_session")
        return response

    # ── ColdChain JWT auth ────────────────────────────────────────────────────

    @app.post("/api/cc/auth/login", tags=["cc-auth"])
    def cc_login(body: Login, db: DB):
        user = db.scalar(select(User).where(User.username == body.username))
        if not user or not user.active:
            # timing-safe dummy check
            password_hasher.verify(body.password, DUMMY_HASH)
            raise HTTPException(401, "Invalid credentials")
        # Account lock check
        if user.locked_until and as_utc(user.locked_until) > utcnow():
            raise HTTPException(429, "Account locked due to repeated failures")
        valid = password_hasher.verify(body.password, user.bcrypt_hash)
        if not valid:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= 10:
                user.locked_until = utcnow() + timedelta(minutes=30)
            db.commit()
            raise HTTPException(401, "Invalid credentials")
        user.failed_logins = 0
        user.locked_until  = None
        db.commit()
        tokens = create_tokens(user, settings.coldchain_jwt_secret)
        audit_mod.append(db, actor=user.username, action="LOGIN", payload={"role": user.role})
        db.commit()
        return tokens

    @app.post("/api/cc/auth/refresh", tags=["cc-auth"])
    async def cc_refresh(body: RefreshRequest, db: DB):
        payload = decode_refresh_token(body.refresh_token, settings.coldchain_jwt_secret)
        user = db.get(User, int(payload["sub"]))
        if not user or not user.active:
            raise HTTPException(401, "User not found or inactive")
        return create_tokens(user, settings.coldchain_jwt_secret)

    @app.get("/api/cc/me", tags=["cc-auth"])
    def cc_me(request: Request, db: DB,
              current_user: Annotated[User, Depends(AnyRole)]):
        return {
            "id": current_user.id, "username": current_user.username,
            "role": current_user.role,
            "demo_time_scale": settings.demo_time_scale,
        }

    # =========================================================================
    # Legacy profile + telemetry (unchanged for backward compat)
    # =========================================================================

    @app.get("/api/auth/me", tags=["auth"])
    def me(auth: Auth, db: DB):
        profile = db.get(UserProfile, auth.username)
        return {"username": auth.username,
                "full_name": profile.full_name if profile else None,
                "demo_mode": settings.demo_mode,
                "max_devices": settings.max_devices}

    @app.get("/api/profile",  response_model=ProfileOut, tags=["profile"])
    def get_profile(auth: Auth, db: DB):
        return db.get(UserProfile, auth.username) or ProfileOut(username=auth.username)

    @app.put("/api/profile", response_model=ProfileOut, tags=["profile"])
    def update_profile(body: ProfileUpdate, auth: Auth, db: DB):
        profile = db.get(UserProfile, auth.username)
        if profile is None:
            profile = UserProfile(username=auth.username); db.add(profile)
        profile.full_name, profile.email = body.full_name, body.email
        commit(db); return profile

    @app.get("/api/summary", tags=["telemetry"])
    def summary(auth: Auth, db: DB):
        latest = db.scalar(select(func.max(Telemetry.received_at)))
        return {
            "devices":            db.scalar(select(func.count()).select_from(Device)),
            "enabled_devices":    db.scalar(select(func.count()).select_from(Device).where(Device.enabled.is_(True))),
            "parameters":         db.scalar(select(func.count()).select_from(Parameter)),
            "enabled_parameters": db.scalar(select(func.count()).select_from(Parameter).where(Parameter.enabled.is_(True))),
            "readings":           db.scalar(select(func.count()).select_from(Telemetry)),
            "records":            db.scalar(select(func.count()).select_from(TelemetryRecord)),
            "last_received_at":   as_utc(latest) if latest else None,
        }

    @app.get("/api/devices", response_model=list[DeviceOut], tags=["devices"])
    def devices(auth: Auth, db: DB):
        return db.scalars(select(Device).order_by(Device.device_id)).all()

    @app.post("/api/devices", response_model=DeviceCreateOut, status_code=201, tags=["devices"])
    def add_device(body: DeviceCreate, auth: Auth, db: DB):
        if db.bind.dialect.name == "postgresql":
            db.execute(text("LOCK TABLE devices IN SHARE ROW EXCLUSIVE MODE"))
        if db.get(Device, body.device_id):
            raise HTTPException(409, "Device already exists")
        if db.scalar(select(func.count()).select_from(Device)) >= settings.max_devices:
            raise HTTPException(409, f"Maximum of {settings.max_devices} registered devices reached")
        device = Device(**body.model_dump())
        # Generate unique cryptographic HMAC secret (64-char hex)
        device.mqtt_password = secrets.token_hex(32)
        db.add(device)
        try:
            curr_secrets = json.loads(settings.device_secrets_json)
        except Exception:
            curr_secrets = {}
        curr_secrets[device.device_id] = device.mqtt_password
        settings.device_secrets_json = json.dumps(curr_secrets)
        pw_file = Path("/secrets/mosquitto.passwd")
        if pw_file.exists():
            try:
                subprocess.run(["mosquitto_passwd", "-b", str(pw_file),
                                device.device_id, device.mqtt_password], check=True)
            except Exception as e:
                db.rollback(); raise HTTPException(500, f"Failed to update mosquitto password: {e}")
        commit(db); return device

    @app.put("/api/devices/{device_id}", response_model=DeviceOut, tags=["devices"])
    def update_device(device_id: str, body: DeviceUpdate, auth: Auth, db: DB):
        device = db.get(Device, device_id)
        if device is None: raise HTTPException(404, "Device not found")
        device.name, device.enabled = body.name, body.enabled
        commit(db); return device

    @app.delete("/api/devices/{device_id}/telemetry", status_code=204, tags=["devices"])
    def clear_device_telemetry(device_id: str, auth: Auth, db: DB):
        if db.get(Device, device_id) is None: raise HTTPException(404, "Device not found")
        db.execute(delete(Telemetry).where(Telemetry.device_id == device_id))
        db.execute(delete(TelemetryRecord).where(TelemetryRecord.device_id == device_id))
        db.execute(delete(IngestedMessage).where(IngestedMessage.device_id == device_id))
        db.commit(); return Response(status_code=204)

    @app.delete("/api/devices/{device_id}", status_code=204, tags=["devices"])
    def remove_device(device_id: str, auth: Auth, db: DB):
        if db.get(Device, device_id) is None: raise HTTPException(404, "Device not found")
        db.execute(delete(Telemetry).where(Telemetry.device_id == device_id))
        db.execute(delete(TelemetryRecord).where(TelemetryRecord.device_id == device_id))
        db.execute(delete(IngestedMessage).where(IngestedMessage.device_id == device_id))
        db.execute(delete(Device).where(Device.device_id == device_id))
        pw_file = Path("/secrets/mosquitto.passwd")
        if pw_file.exists():
            try:
                subprocess.run(["mosquitto_passwd", "-D", str(pw_file), device_id], check=True)
            except Exception as e:
                db.rollback(); raise HTTPException(500, f"Failed to remove mosquitto password: {e}")
        db.commit(); return Response(status_code=204)

    # System parameter keys come from the DB (seeded at startup by parameters_seed.py)
    # Use SYSTEM_PARAMETER_KEYS from parameters_seed for guard checks
    _PERM_KEYS: frozenset[str] = SYSTEM_PARAMETER_KEYS

    @app.get("/api/parameters", response_model=list[ParameterOut], tags=["parameters"])
    def parameters(auth: Auth, db: DB):
        params = db.scalars(select(Parameter).order_by(Parameter.name)).all()
        return [
            ParameterOut(
                name=p.name,
                unit=p.unit,
                enabled=p.enabled,
            )
            for p in params
        ]

    @app.get("/api/admin/parameters", tags=["cc-admin"])
    def admin_parameters(
        db: DB,
        current_user: Annotated[User, Depends(AdminOnly)],
    ):
        """Full parameter catalogue sourced entirely from DB (permanent + custom)."""
        seed_system_parameters(db)
        params = db.scalars(
            select(Parameter).order_by(
                Parameter.is_permanent.desc(),  # system params first
                Parameter.name,
            )
        ).all()
        return [
            {
                "name":         p.name,
                "unit":         p.unit,
                "description":  p.description,
                "is_permanent": p.is_permanent,
                "enabled":      p.enabled,
            }
            for p in params
        ]

    @app.delete("/api/admin/parameters/{name}/telemetry", status_code=204, tags=["cc-admin"])
    def clear_parameter_telemetry(
        name: str,
        db: DB,
        current_user: Annotated[User, Depends(AdminOnly)],
    ):
        """Remove all stored telemetry readings for a specific parameter key across all devices."""
        from app.models import Telemetry as _Tel
        db.execute(delete(_Tel).where(_Tel.parameter == name))
        db.commit()
        return Response(status_code=204)

    @app.post("/api/parameters", response_model=ParameterOut, status_code=201, tags=["parameters"])
    def add_parameter(body: ParameterCreate, auth: Auth, db: DB):
        if body.name in _PERM_KEYS:
            raise HTTPException(409, "Parameter is a permanent system parameter")
        parameter = Parameter(
            name=body.name,
            unit=body.unit,
            enabled=body.enabled,
            is_permanent=False,
            description="Custom telemetry parameter",
        )
        db.add(parameter)
        commit(db)
        return ParameterOut(
            name=parameter.name,
            unit=parameter.unit,
            enabled=parameter.enabled,
        )

    @app.put("/api/parameters/{name}", response_model=ParameterOut, tags=["parameters"])
    def update_parameter(name: str, body: ParameterUpdate, auth: Auth, db: DB):
        parameter = db.get(Parameter, name)
        if parameter is None:
            raise HTTPException(404, "Parameter not found")
        if name in _PERM_KEYS and not body.enabled:
            raise HTTPException(400, "Permanent system parameter cannot be disabled")
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(parameter, key, value)
        commit(db)
        return ParameterOut(
            name=parameter.name,
            unit=parameter.unit,
            enabled=parameter.enabled,
            
        )

    @app.delete("/api/parameters/{name}", status_code=204, tags=["parameters"])
    def remove_parameter(name: str, auth: Auth, db: DB):
        if name in _PERM_KEYS:
            raise HTTPException(400, "Permanent system parameter cannot be deleted")
        result = db.execute(delete(Parameter).where(Parameter.name == name))
        if not result.rowcount:
            raise HTTPException(404, "Parameter not found")
        db.commit()
        return Response(status_code=204)

    @app.get("/api/telemetry", response_model=list[TelemetryOut], tags=["telemetry"])
    def telemetry(auth: Auth, db: DB,
                  limit: int = Query(default=100, ge=1, le=1000),
                  before_id: int | None = Query(default=None, ge=1)):
        statement = select(Telemetry).order_by(Telemetry.id.desc()).limit(limit)
        if before_id is not None:
            statement = statement.where(Telemetry.id < before_id)
        return db.scalars(statement).all()

    @app.get("/api/telemetry/records", tags=["telemetry"])
    def telemetry_records(auth: Auth, db: DB,
                          limit: int = Query(default=12, ge=1, le=100),
                          before_id: int | None = Query(default=None, ge=1)):
        statement = (select(TelemetryRecord, Device.name)
                     .join(Device, Device.device_id == TelemetryRecord.device_id)
                     .order_by(TelemetryRecord.id.desc()).limit(limit + 1))
        if before_id is not None:
            statement = statement.where(TelemetryRecord.id < before_id)
        entries = db.execute(statement).all()
        page    = entries[:limit]
        values  = {record.id: {} for record, _ in page}
        if values:
            for reading in db.scalars(select(Telemetry).where(Telemetry.record_id.in_(values))):
                values[reading.record_id][reading.parameter] = reading.value
        columns = sorted(set(db.scalars(select(Parameter.name))) |
                         set(db.scalars(select(Telemetry.parameter).distinct())))
        units = dict(db.execute(select(Parameter.name, Parameter.unit)).all())
        return {
            "columns": columns, "units": units,
            "records": [{"registry_id": record.id, "device_id": record.device_id,
                         "device_name": name, "timestamp": as_utc(record.timestamp),
                         "values": values[record.id],
                         "health": device_health(values[record.id], settings)}
                        for record, name in page],
            "next_cursor": page[-1][0].id if len(entries) > limit else None,
            "health_rule": {"parameter": "systemTemp", "min": settings.system_temp_min,
                            "max": settings.system_temp_max, "unit": settings.system_temp_unit},
        }

    @app.get("/api/telemetry/export", tags=["telemetry"])
    def export(auth: Auth, dates: Annotated[tuple[datetime, datetime], Depends(date_range)]):
        start, end = dates
        def rows():
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            with app.state.sessions() as db:
                columns = sorted(set(db.scalars(select(Parameter.name).where(Parameter.enabled.is_(True)))) |
                                  set(db.scalars(select(Telemetry.parameter).distinct())))
                if "systemTemp" in columns: columns.remove("systemTemp")
                units = dict(db.execute(select(Parameter.name, Parameter.unit)).all())
                header = ["timestamp", "device_id", "device_name"]
                for c in columns:
                    header.append(f"{c}({units[c]})" if units.get(c) else c)
                writer.writerow(header); yield output.getvalue()
                statement = (select(TelemetryRecord, Device.name, Telemetry.parameter, Telemetry.value)
                             .join(Device, Device.device_id == TelemetryRecord.device_id)
                             .join(Telemetry, Telemetry.record_id == TelemetryRecord.id)
                             .where(TelemetryRecord.timestamp >= start, TelemetryRecord.timestamp < end)
                             .order_by(TelemetryRecord.timestamp, TelemetryRecord.id)
                             .execution_options(yield_per=5000))
                current_record_id = None; current_row = None
                for record, device_name, param, val in db.execute(statement):
                    if param == "systemTemp": continue
                    if record.id != current_record_id:
                        if current_row is not None:
                            output.seek(0); output.truncate(0)
                            writer.writerow([current_row.get(col, "") for col in ["timestamp","device_id","device_name"]+columns])
                            yield output.getvalue()
                        current_record_id = record.id
                        safe_name = device_name or ""
                        if safe_name.startswith(("=","+","-","@","\t","\r")): safe_name = f"'{safe_name}"
                        current_row = {"timestamp": as_utc(record.timestamp).isoformat(),
                                       "device_id": record.device_id, "device_name": safe_name}
                    current_row[param] = val
                if current_row is not None:
                    output.seek(0); output.truncate(0)
                    writer.writerow([current_row.get(col, "") for col in ["timestamp","device_id","device_name"]+columns])
                    yield output.getvalue()
        return StreamingResponse(rows(), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="telemetry.csv"',
                                          "Cache-Control": "no-store"})

    # =========================================================================
    # ColdChain – Dashboard & Fridges
    # =========================================================================

    @app.get("/api/fridges", tags=["cc-fridges"])
    def list_fridges(db: DB, current_user: Annotated[User, Depends(AnyRole)]):
        fridges = db.scalars(select(Fridge).order_by(Fridge.id)).all()
        result = []
        for f in fridges:
            latest = None
            if f.device_id:
                latest = db.scalar(
                    select(Reading).where(Reading.device_id == f.device_id)
                    .order_by(Reading.ts.desc()).limit(1))
            batches = db.scalars(select(Batch).where(Batch.fridge_id == f.id)).all()
            result.append({**_fridge_dict(f, latest),
                           "batches": [_batch_dict(b) for b in batches]})
        return result

    @app.post("/api/fridges", status_code=201, tags=["cc-fridges"])
    def create_fridge(body: FridgeCreate, db: DB,
                      current_user: Annotated[User, Depends(AdminOnly)]):
        if body.device_id:
            device = db.get(Device, body.device_id)
            if device is None:
                raise HTTPException(404, "Device not found")
            if device.fridge_id is not None:
                raise HTTPException(409, "Device already assigned to another fridge")
        f = Fridge(**body.model_dump())
        db.add(f); db.flush()
        if body.device_id:
            _bind_device_fridge(db.get(Device, body.device_id), f)
        audit_mod.append(db, actor=current_user.username, action="FRIDGE_CREATED",
                         payload={"fridge_id": f.id, "name": f.name})
        db.commit()
        return _fridge_dict(f, None)

    @app.get("/api/fridges/{fridge_id}", tags=["cc-fridges"])
    def get_fridge(fridge_id: int, db: DB,
                   current_user: Annotated[User, Depends(AnyRole)]):
        f = fridge_or_404(db, fridge_id)
        latest = _latest_reading(db, f.device_id)
        batches = db.scalars(select(Batch).where(Batch.fridge_id == f.id)).all()
        return {**_fridge_dict(f, latest), "batches": [_batch_dict(b) for b in batches]}

    @app.patch("/api/fridges/{fridge_id}", tags=["cc-fridges"])
    def update_fridge(fridge_id: int, body: FridgeUpdate, db: DB,
                      current_user: Annotated[User, Depends(AdminOnly)]):
        """Update name / capacity / location / assigned device (two-way binding)."""
        f = fridge_or_404(db, fridge_id)
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, "No fields to update")

        audit_payload = {"fridge_id": f.id, "fields": sorted(changes.keys())}
        old_device_id = f.device_id

        if "device_id" in changes:
            new_device_id = changes["device_id"]
            if new_device_id is None:
                if f.device_id:
                    _unbind_device_fridge(db.get(Device, f.device_id), f)
            else:
                device = db.get(Device, new_device_id)
                if device is None:
                    raise HTTPException(404, "Device not found")
                if device.fridge_id is not None and device.fridge_id != f.id:
                    raise HTTPException(409, "Device already assigned to another fridge")
                if f.device_id and f.device_id != new_device_id:
                    _unbind_device_fridge(db.get(Device, f.device_id), None)
                _bind_device_fridge(device, f)
            audit_payload["device_from"] = old_device_id
            audit_payload["device_to"] = new_device_id

        for key in ("name", "capacity_slots", "location"):
            if key in changes:
                setattr(f, key, changes[key])

        audit_mod.append(db, actor=current_user.username, action="FRIDGE_UPDATED",
                         payload=audit_payload)
        db.commit()
        return {**_fridge_dict(f, _latest_reading(db, f.device_id)),
                "batches": [_batch_dict(b) for b in db.scalars(
                    select(Batch).where(Batch.fridge_id == f.id)).all()]}

    @app.delete("/api/fridges/{fridge_id}", status_code=204, tags=["cc-fridges"])
    def delete_fridge(fridge_id: int, db: DB,
                      current_user: Annotated[User, Depends(AdminOnly)]):
        """Delete a fridge. Batches keep their exposure history but become unassigned."""
        f = fridge_or_404(db, fridge_id)
        device = db.get(Device, f.device_id) if f.device_id else None
        _unbind_device_fridge(device, f)
        n_batches = db.scalar(
            select(func.count()).select_from(Batch).where(Batch.fridge_id == f.id)) or 0
        db.execute(update(Batch).where(Batch.fridge_id == f.id).values(fridge_id=None))
        audit_mod.append(db, actor=current_user.username, action="FRIDGE_DELETED",
                         payload={"fridge_id": f.id, "name": f.name,
                                  "unassigned_batches": n_batches})
        db.delete(f)
        db.commit()
        return Response(status_code=204)

    @app.get("/api/fridges/{fridge_id}/live", tags=["cc-fridges"])
    def fridge_live(fridge_id: int, db: DB,
                    current_user: Annotated[User, Depends(AnyRole)]):
        f = fridge_or_404(db, fridge_id)
        latest = _latest_reading(db, f.device_id)
        batches = db.scalars(select(Batch).where(Batch.fridge_id == fridge_id)).all()
        return {**_fridge_dict(f, latest), "batches": [_batch_dict(b) for b in batches]}

    @app.get("/api/fridges/{fridge_id}/readings", tags=["cc-fridges"])
    def fridge_readings(fridge_id: int, db: DB,
                        current_user: Annotated[User, Depends(AnyRole)],
                        limit: int = Query(default=200, ge=1, le=2000),
                        from_ts: str | None = Query(default=None),
                        to_ts:   str | None = Query(default=None)):
        f = fridge_or_404(db, fridge_id)
        if not f.device_id:
            return []
        stmt = (select(Reading).where(Reading.device_id == f.device_id)
                .order_by(Reading.ts.desc()).limit(limit))
        if from_ts:
            stmt = stmt.where(Reading.ts >= datetime.fromisoformat(from_ts))
        if to_ts:
            stmt = stmt.where(Reading.ts <= datetime.fromisoformat(to_ts))
        return [_reading_dict(r) for r in db.scalars(stmt).all()]

    @app.get("/api/readings", tags=["cc-readings"])
    def list_readings(
        db: DB,
        current_user: Annotated[User, Depends(AnyRole)],
        device_id: str | None = Query(default=None),
        from_ts:   str | None = Query(default=None),
        to_ts:     str | None = Query(default=None),
        limit:     int = Query(default=50, ge=1, le=500),
        offset:    int = Query(default=0, ge=0),
    ):
        """Query telemetry readings across all devices with timeline filters."""
        stmt = select(Reading)
        count_stmt = select(func.count()).select_from(Reading)

        if device_id:
            stmt = stmt.where(Reading.device_id == device_id)
            count_stmt = count_stmt.where(Reading.device_id == device_id)
        if from_ts:
            dt_from = datetime.fromisoformat(from_ts)
            stmt = stmt.where(Reading.ts >= dt_from)
            count_stmt = count_stmt.where(Reading.ts >= dt_from)
        if to_ts:
            dt_to = datetime.fromisoformat(to_ts)
            stmt = stmt.where(Reading.ts <= dt_to)
            count_stmt = count_stmt.where(Reading.ts <= dt_to)

        total = db.scalar(count_stmt) or 0
        rows = db.scalars(stmt.order_by(Reading.ts.desc()).offset(offset).limit(limit)).all()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [_reading_dict(r) for r in rows],
        }

    @app.get("/api/readings/export", tags=["cc-readings"])
    def export_readings(
        db: DB,
        current_user: Annotated[User, Depends(AnyRole)],
        device_id: str | None = Query(default=None),
        from_ts:   str | None = Query(default=None),
        to_ts:     str | None = Query(default=None),
        limit:     int = Query(default=10000, ge=1, le=50000),
    ):
        """Export telemetry readings to downloadable CSV."""
        stmt = select(Reading)
        if device_id:
            stmt = stmt.where(Reading.device_id == device_id)
        if from_ts:
            stmt = stmt.where(Reading.ts >= datetime.fromisoformat(from_ts))
        if to_ts:
            stmt = stmt.where(Reading.ts <= datetime.fromisoformat(to_ts))

        rows = db.scalars(stmt.order_by(Reading.ts.asc()).limit(limit)).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "device_id", "seq", "timestamp_utc", "temp_c",
            "compressor_on", "lockout_s", "door_open", "door_open_s",
            "power_source", "mains_present", "battery_pct", "battery_v",
            "state", "red_latched", "sim_mode", "ingested_at"
        ])
        for r in rows:
            writer.writerow([
                r.id, r.device_id, r.seq, as_utc(r.ts).isoformat(), r.temp_c,
                1 if r.compressor_on else 0, r.lockout_s,
                1 if r.door_open else 0, r.door_open_s,
                r.power_source, 1 if r.mains_present else 0,
                r.battery_pct if r.battery_pct is not None else "",
                r.battery_v if r.battery_v is not None else "",
                r.state, 1 if r.red_latched else 0, 1 if r.sim_mode else 0,
                as_utc(r.ingested_at).isoformat(),
            ])

        output.seek(0)
        filename = f"telemetry_{device_id or 'all'}_{utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/dashboard/summary", tags=["cc-dashboard"])
    def dashboard_summary(db: DB, current_user: Annotated[User, Depends(AnyRole)]):
        fridges = db.scalars(select(Fridge)).all()
        summary = []
        for f in fridges:
            latest = None
            if f.device_id:
                latest = db.scalar(
                    select(Reading).where(Reading.device_id == f.device_id)
                    .order_by(Reading.ts.desc()).limit(1))
            batches = db.scalars(select(Batch).where(Batch.fridge_id == f.id)).all()
            online = False
            if f.device_id:
                dev = db.get(Device, f.device_id)
                if dev and dev.last_seen:
                    online = (utcnow() - as_utc(dev.last_seen)).total_seconds() < 30
            summary.append({
                "fridge": _fridge_dict(f, latest),
                "online": online,
                "batches": [_batch_dict(b) for b in batches],
                "demo_time_scale": settings.demo_time_scale,
            })
        return summary

    # ── WebSocket live feed ────────────────────────────────────────────────────
    @app.websocket("/api/ws/live")
    async def ws_live(ws: WebSocket):
        await _live.connect(ws)
        try:
            while True:
                await ws.receive_text()   # keep-alive; client sends pings
        except WebSocketDisconnect:
            await _live.disconnect(ws)

    # =========================================================================
    # ColdChain – Batches
    # =========================================================================

    @app.get("/api/batches", tags=["cc-batches"])
    def list_batches(db: DB, current_user: Annotated[User, Depends(AnyRole)]):
        return [_batch_dict(b) for b in db.scalars(select(Batch).order_by(Batch.id)).all()]

    @app.post("/api/batches", status_code=201, tags=["cc-batches"])
    def create_batch(body: dict, db: DB,
                     current_user: Annotated[User, Depends(PharmOrAdmin)]):
        from datetime import date as date_t
        b = Batch(
            code=body["code"], vaccine_name=body["vaccine_name"],
            qty=int(body["qty"]),
            expiry_date=date_t.fromisoformat(body["expiry_date"]) if body.get("expiry_date") else None,
            fridge_id=body.get("fridge_id"),
            qr_token=secrets.token_urlsafe(32),
        )
        db.add(b); db.flush()
        audit_mod.append(db, actor=current_user.username, action="BATCH_CREATED",
                         payload={"batch_id": b.id, "code": b.code})
        db.commit(); db.refresh(b)
        return _batch_dict(b)

    @app.patch("/api/batches/{batch_id}", tags=["cc-batches"])
    def update_batch(batch_id: int, body: dict, db: DB,
                     current_user: Annotated[User, Depends(PharmOrAdmin)]):
        b = batch_or_404(db, batch_id)
        for field in ("vaccine_name", "qty", "fridge_id"):
            if field in body:
                setattr(b, field, body[field])
        db.commit(); return _batch_dict(b)

    @app.post("/api/batches/{batch_id}/move", tags=["cc-batches"])
    def move_batch(batch_id: int, body: dict, db: DB,
                   current_user: Annotated[User, Depends(PharmOrAdmin)]):
        b = batch_or_404(db, batch_id)
        new_fridge_id = int(body["to_fridge_id"])
        fridge_or_404(db, new_fridge_id)
        old_fridge_id = b.fridge_id
        b.fridge_id = new_fridge_id
        mv = BatchMovement(batch_id=batch_id, from_fridge_id=old_fridge_id,
                           to_fridge_id=new_fridge_id, moved_by=current_user.id,
                           reason=body.get("reason", "manual"))
        db.add(mv); db.flush()
        audit_mod.append(db, actor=current_user.username, action="BATCH_MOVED",
                         payload={"batch_id": batch_id, "from": old_fridge_id,
                                  "to": new_fridge_id, "reason": body.get("reason")})
        db.commit()
        return _batch_dict(b)

    @app.post("/api/batches/{batch_id}/reset", tags=["cc-batches"])
    def reset_batch_discard(batch_id: int, body: dict, db: DB,
                             current_user: Annotated[User, Depends(AdminOnly)]):
        try:
            from app.mqtt_publisher import publish_command as _pub_cmd
            def _publish_fn(device_id: str, cmd_type: str, cmd_payload: dict):
                try:
                    _pub_cmd(settings, device_id, cmd_type, cmd_payload)
                except Exception as _exc:
                    logger.warning("Downlink %s to %s failed: %s", cmd_type, device_id, _exc)
            b = reset_discard(db, batch_id, actor=current_user.username,
                              reason=body.get("reason", "admin reset"),
                              publish_cmd_fn=_publish_fn)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        db.commit()
        return _batch_dict(b)

    # ── Public QR page (no auth) ───────────────────────────────────────────────
    @app.get("/api/public/batch/{qr_token}", tags=["public"])
    def public_batch(qr_token: str, db: DB):
        b = db.scalar(select(Batch).where(Batch.qr_token == qr_token))
        if not b:
            raise HTTPException(404, "Batch not found")
        # Return only non-sensitive fields
        return {
            "vaccine_name": b.vaccine_name,
            "status": b.status,
            "remaining_pct": round(b.remaining_pct, 1),
            "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
            "last_checked": utcnow().isoformat(),
        }

    # =========================================================================
    # ColdChain – Alerts
    # =========================================================================

    @app.get("/api/alerts", tags=["cc-alerts"])
    def list_alerts(db: DB, current_user: Annotated[User, Depends(AnyRole)],
                    limit: int = Query(default=50, ge=1, le=200),
                    unacked_only: bool = False):
        stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
        if unacked_only:
            stmt = stmt.where(Alert.acknowledged_by.is_(None))
        alerts = db.scalars(stmt).all()
        return [{"id": a.id, "type": a.type, "device_id": a.device_id,
                 "batch_id": a.batch_id, "message": a.message,
                 "sent_via": a.sent_via,
                 "created_at": as_utc(a.created_at).isoformat(),
                 "acknowledged_by": a.acknowledged_by,
                 "acknowledged_at": as_utc(a.acknowledged_at).isoformat() if a.acknowledged_at else None}
                for a in alerts]

    @app.post("/api/alerts/{alert_id}/ack", tags=["cc-alerts"])
    def ack_alert(alert_id: int, db: DB,
                  current_user: Annotated[User, Depends(PharmOrAdmin)]):
        a = db.get(Alert, alert_id)
        if not a: raise HTTPException(404, "Alert not found")
        a.acknowledged_by = current_user.id
        a.acknowledged_at = utcnow()
        db.commit()
        return {"status": "acknowledged"}

    # =========================================================================
    # ColdChain – Audit Log
    # =========================================================================

    @app.get("/api/audit", tags=["cc-audit"])
    def audit_log(db: DB,
                  current_user: Annotated[User, Depends(require_role("admin", "inspector"))],
                  page: int = Query(default=1, ge=1),
                  per_page: int = Query(default=50, ge=1, le=200)):
        offset = (page - 1) * per_page
        rows = db.scalars(select(AuditLog).order_by(AuditLog.idx.desc())
                          .offset(offset).limit(per_page)).all()
        total = db.scalar(select(func.count()).select_from(AuditLog))
        return {
            "total": total, "page": page, "per_page": per_page,
            "entries": [{"idx": r.idx, "ts": as_utc(r.ts).isoformat(),
                         "actor": r.actor, "action": r.action,
                         "payload": r.payload(),
                         "hash": r.hash[:12] + "...",
                         "prev_hash": r.prev_hash[:12] + "..."} for r in rows],
        }

    @app.get("/api/audit/verify", tags=["cc-audit"])
    def verify_audit(db: DB,
                     current_user: Annotated[User, Depends(require_role("admin", "inspector"))]):
        return audit_mod.verify_chain(db)

    # =========================================================================
    # ColdChain – Security events
    # =========================================================================

    @app.get("/api/security/events", tags=["cc-security"])
    def security_events(db: DB,
                        current_user: Annotated[User, Depends(require_role("admin", "inspector"))],
                        limit: int = Query(default=100, ge=1, le=500)):
        rows = db.scalars(select(SecurityEvent).order_by(SecurityEvent.created_at.desc())
                          .limit(limit)).all()
        return [{"id": r.id, "device_id": r.device_id, "kind": r.kind,
                 "raw_excerpt": r.raw_excerpt,
                 "created_at": as_utc(r.created_at).isoformat()} for r in rows]

    # =========================================================================
    # ColdChain – Device Registry CRUD (DB-backed HMAC secrets)
    # =========================================================================

    def _device_dict(d: Device, db: DB) -> dict:
        fridge = db.get(Fridge, d.fridge_id) if d.fridge_id else None
        return {
            "device_id": d.device_id, "name": d.name, "enabled": d.enabled,
            "fridge_id": d.fridge_id, "fridge_name": fridge.name if fridge else None,
            "has_secret": bool(d.mqtt_password),
            "last_seen": as_utc(d.last_seen).isoformat() if d.last_seen else None,
            "last_seq": d.last_seq,
            "created_at": as_utc(d.created_at).isoformat(),
        }

    def device_or_404(db: DB, device_id: str) -> Device:
        d = db.get(Device, device_id)
        if not d:
            raise HTTPException(404, "Device not found")
        return d

    @app.get("/api/cc/devices", tags=["cc-devices"])
    def cc_devices_list(db: DB, current_user: Annotated[User, Depends(AnyRole)]):
        """Device registry. Secrets never leave the API as list data (has_secret only)."""
        return [_device_dict(d, db) for d in
                db.scalars(select(Device).order_by(Device.device_id)).all()]

    @app.post("/api/cc/devices", status_code=201, tags=["cc-devices"])
    def cc_device_create(body: CcDeviceCreate, db: DB,
                         current_user: Annotated[User, Depends(AdminOnly)]):
        """Register a node. The HMAC secret may be user-set (validated hex) or minted."""
        if db.get(Device, body.device_id):
            raise HTTPException(409, "Device already exists")
        if db.scalar(select(func.count()).select_from(Device)) >= settings.max_devices:
            raise HTTPException(409, f"Maximum of {settings.max_devices} registered devices reached")
        if body.fridge_id is not None:
            fridge = db.get(Fridge, body.fridge_id)
            if fridge is None:
                raise HTTPException(404, "Fridge not found")
            if fridge.device_id:
                raise HTTPException(409, "Fridge already has an assigned device")

        # Secret lives ONLY in the DB (devices.mqtt_password); never hard-coded.
        secret = body.secret.lower() if body.secret else generate_secret()
        device = Device(device_id=body.device_id, name=body.name,
                        enabled=body.enabled, mqtt_password=secret)
        db.add(device); db.flush()
        if body.fridge_id is not None:
            _bind_device_fridge(device, db.get(Fridge, body.fridge_id))

        _sync_mosquitto(db, device.device_id, secret)
        audit_mod.append(db, actor=current_user.username, action="DEVICE_CREATED",
                         payload={"device_id": device.device_id, "fridge_id": body.fridge_id,
                                  "secret_source": "user" if body.secret else "generated"})
        db.commit()
        # The secret is returned exactly once at creation for firmware/simulator config.
        return {**_device_dict(device, db), "secret": secret}

    @app.patch("/api/cc/devices/{device_id}", tags=["cc-devices"])
    def cc_device_update(device_id: str, body: CcDeviceUpdate, db: DB,
                         current_user: Annotated[User, Depends(AdminOnly)]):
        """Update name / enabled / fridge binding / secret (set by user or rotate)."""
        device = device_or_404(db, device_id)
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, "No fields to update")

        new_secret: str | None = None
        if body.rotate:
            new_secret = generate_secret()
        elif body.secret:
            new_secret = body.secret.lower()

        if new_secret is not None:
            device.mqtt_password = new_secret
            _sync_mosquitto(db, device.device_id, new_secret)
            audit_mod.append(db, actor=current_user.username,
                             action="DEVICE_SECRET_ROTATED" if body.rotate else "DEVICE_SECRET_SET",
                             payload={"device_id": device.device_id,
                                      "source": "rotate" if body.rotate else "user"})

        if "fridge_id" in changes:
            new_fridge_id = changes["fridge_id"]
            if new_fridge_id is None:
                if device.fridge_id:
                    _unbind_device_fridge(device, db.get(Fridge, device.fridge_id))
            else:
                fridge = db.get(Fridge, new_fridge_id)
                if fridge is None:
                    raise HTTPException(404, "Fridge not found")
                if fridge.device_id and fridge.device_id != device.device_id:
                    raise HTTPException(409, "Fridge already has an assigned device")
                if device.fridge_id and device.fridge_id != new_fridge_id:
                    _unbind_device_fridge(None, db.get(Fridge, device.fridge_id))
                _bind_device_fridge(device, fridge)

        for key in ("name", "enabled"):
            if key in changes:
                setattr(device, key, changes[key])

        if any(k in changes for k in ("name", "enabled", "fridge_id")):
            audit_mod.append(db, actor=current_user.username, action="DEVICE_UPDATED",
                             payload={"device_id": device.device_id,
                                      "fields": sorted(set(changes) - {"secret"})})
        db.commit()
        out = _device_dict(device, db)
        if new_secret is not None:
            out["secret"] = new_secret  # shown once after set/rotate
        return out

    @app.get("/api/cc/devices/{device_id}/secret", tags=["cc-devices"])
    def cc_device_secret(device_id: str, db: DB,
                         current_user: Annotated[User, Depends(AdminOnly)]):
        """Reveal the currently stored HMAC secret (admin only; audited)."""
        device = device_or_404(db, device_id)
        if not device.mqtt_password:
            raise HTTPException(404, "Device has no secret stored")
        audit_mod.append(db, actor=current_user.username, action="DEVICE_SECRET_VIEWED",
                         payload={"device_id": device.device_id})
        db.commit()
        return {"device_id": device.device_id, "secret": device.mqtt_password}

    @app.delete("/api/cc/devices/{device_id}", status_code=204, tags=["cc-devices"])
    def cc_device_delete(device_id: str, db: DB,
                         current_user: Annotated[User, Depends(AdminOnly)],
                         force: bool = Query(default=False)):
        """Delete a node. Reading/telemetry history must be `force`-purged to proceed."""
        device = device_or_404(db, device_id)
        n_readings = db.scalar(
            select(func.count()).select_from(Reading).where(Reading.device_id == device_id)) or 0
        n_telemetry = db.scalar(
            select(func.count()).select_from(Telemetry).where(Telemetry.device_id == device_id)) or 0
        if (n_readings or n_telemetry) and not force:
            raise HTTPException(409, "Device has stored readings; pass ?force=true to purge history")

        _unbind_device_fridge(device, db.get(Fridge, device.fridge_id) if device.fridge_id else None)
        fridge_by_ref = db.scalar(select(Fridge).where(Fridge.device_id == device_id))
        if fridge_by_ref:
            _unbind_device_fridge(None, fridge_by_ref)

        purged = 0
        if force:
            purged = n_readings
            for table in (Reading, Telemetry, TelemetryRecord, IngestedMessage,
                          Nonce, MlPrediction):
                db.execute(delete(table).where(table.device_id == device_id))

        _sync_mosquitto(db, device_id, None)
        audit_mod.append(db, actor=current_user.username, action="DEVICE_DELETED",
                         payload={"device_id": device_id, "purged_readings": purged})
        db.delete(device)
        db.commit()
        return Response(status_code=204)

    # =========================================================================
    # ColdChain – Users (admin only)
    # =========================================================================

    @app.get("/api/users", tags=["cc-users"])
    def list_users(db: DB, current_user: Annotated[User, Depends(AdminOnly)]):
        users = db.scalars(select(User).order_by(User.id)).all()
        return [{"id": u.id, "username": u.username, "role": u.role,
                 "active": u.active, "created_at": as_utc(u.created_at).isoformat()}
                for u in users]

    @app.post("/api/users", status_code=201, tags=["cc-users"])
    def create_user(body: dict, db: DB,
                    current_user: Annotated[User, Depends(AdminOnly)]):
        if db.scalar(select(User).where(User.username == body["username"])):
            raise HTTPException(409, "Username already exists")
        u = User(username=body["username"],
                 bcrypt_hash=password_hasher.hash(body["password"]),
                 role=body.get("role", "pharmacist"),
                 active=True)
        db.add(u); db.flush()
        audit_mod.append(db, actor=current_user.username, action="USER_CREATED",
                         payload={"username": u.username, "role": u.role})
        db.commit()
        return {"id": u.id, "username": u.username, "role": u.role}

    @app.patch("/api/users/{user_id}", tags=["cc-users"])
    def update_user(user_id: int, body: dict, db: DB,
                    current_user: Annotated[User, Depends(AdminOnly)]):
        u = get_user_or_404(db, user_id)
        if "role"   in body: u.role   = body["role"]
        if "active" in body: u.active = body["active"]
        if "password" in body:
            u.bcrypt_hash   = password_hasher.hash(body["password"])
            u.failed_logins = 0
            u.locked_until  = None
        audit_mod.append(db, actor=current_user.username, action="USER_UPDATED",
                         payload={"user_id": user_id})
        db.commit()
        return {"id": u.id, "username": u.username, "role": u.role, "active": u.active}

    # =========================================================================
    # ColdChain – ML endpoints
    # =========================================================================

    @app.get("/api/ml/forecast/all", tags=["cc-ml"])
    def ml_forecast_all(db: DB, current_user: Annotated[User, Depends(AnyRole)]):
        from app.ml.forecast import predict_next_30
        fridges = db.scalars(select(Fridge).order_by(Fridge.id)).all()
        results = []
        for f in fridges:
            item = {
                "fridge_id": f.id,
                "fridge_name": f.name,
                "device_id": f.device_id,
                "available": False,
            }
            if f.device_id:
                rows = db.scalars(
                    select(Reading).where(Reading.device_id == f.device_id)
                    .order_by(Reading.ts.desc()).limit(300)
                ).all()
                if rows:
                    readings = [{"t_s": i * 5, **_reading_dict(r)} for i, r in enumerate(reversed(rows))]
                    pred = predict_next_30(readings)
                    item.update(pred)
            results.append(item)
        return results

    @app.get("/api/ml/forecast/{fridge_id}", tags=["cc-ml"])
    def ml_forecast(fridge_id: int, db: DB,
                    current_user: Annotated[User, Depends(AnyRole)]):
        f = fridge_or_404(db, fridge_id)
        if not f.device_id:
            return {"available": False, "reason": "no device assigned"}
        rows = db.scalars(
            select(Reading).where(Reading.device_id == f.device_id)
            .order_by(Reading.ts.desc()).limit(500)).all()
        if not rows:
            return {"available": False, "reason": "no readings"}
        from app.ml.forecast import predict_next_30
        readings = [{"t_s": i * 5, **_reading_dict(r)} for i, r in enumerate(reversed(rows))]
        return predict_next_30(readings)

    @app.get("/api/ml/health/{fridge_id}", tags=["cc-ml"])
    def ml_health(fridge_id: int, db: DB,
                  current_user: Annotated[User, Depends(AnyRole)]):
        f = fridge_or_404(db, fridge_id)
        if not f.device_id:
            return {"available": False, "reason": "no device assigned"}
        rows = db.scalars(
            select(Reading).where(Reading.device_id == f.device_id)
            .order_by(Reading.ts.desc()).limit(1000)).all()
        from app.ml.health import score_health
        readings = [{"t_s": i * 5, **_reading_dict(r)} for i, r in enumerate(reversed(rows))]
        return score_health(readings)

    @app.get("/api/ml/relocation/{fridge_id}", tags=["cc-ml"])
    def ml_relocation(fridge_id: int, db: DB,
                      current_user: Annotated[User, Depends(AnyRole)]):
        suggestions = db.scalars(
            select(RelocationSuggestion)
            .where(RelocationSuggestion.from_fridge_id == fridge_id,
                   RelocationSuggestion.status == "pending")
            .order_by(RelocationSuggestion.created_at.desc()).limit(5)).all()
        return [{"id": s.id, "plan": json.loads(s.plan_json),
                 "created_at": as_utc(s.created_at).isoformat()} for s in suggestions]

    @app.post("/api/ml/relocation/{suggestion_id}/confirm", tags=["cc-ml"])
    def confirm_relocation(suggestion_id: int, db: DB,
                           current_user: Annotated[User, Depends(PharmOrAdmin)]):
        from app.ml.relocation import confirm_suggestion
        try:
            moves = confirm_suggestion(db, suggestion_id, current_user.id,
                                       actor=current_user.username)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        db.commit()
        return {"confirmed": True, "moves": len(moves)}

    # =========================================================================
    # ColdChain – Admin controls
    # =========================================================================

    @app.post("/api/admin/sim/{device_id}", tags=["cc-admin"])
    def sim_fault(device_id: str, body: dict, db: DB,
                  current_user: Annotated[User, Depends(AdminOnly)]):
        """Inject a simulation fault or change time-scale (admin only)."""
        device = db.get(Device, device_id)
        if not device:
            raise HTTPException(404, "Device not found")
        audit_mod.append(db, actor=current_user.username, action="SIM_FAULT",
                         payload={"device_id": device_id, **body})
        db.commit()
        # Push SET_SIM / FAULT_INJECT command to the device via MQTT
        try:
            from app.mqtt_publisher import publish_command as _pub_cmd
            from app.device_registry import get_device_secret as _dev_secret
            cmd_type = body.get("cmd", "SET_SIM")
            _pub_cmd(settings, device_id, cmd_type, body,
                     secret=_dev_secret(db, device_id))
        except Exception as _exc:
            logger.warning("Downlink %s to %s failed: %s", cmd_type, device_id, _exc)
        return {"status": "fault injected", "device_id": device_id, "params": body}

    @app.patch("/api/admin/time-scale", tags=["cc-admin"])
    def set_time_scale(body: dict, db: DB,
                       current_user: Annotated[User, Depends(AdminOnly)]):
        new_scale = float(body.get("time_scale", 1.0))
        if not 0.1 <= new_scale <= 1000:
            raise HTTPException(422, "time_scale must be 0.1 – 1000")
        settings.demo_time_scale = new_scale
        audit_mod.append(db, actor=current_user.username, action="TIME_SCALE_CHANGED",
                         payload={"time_scale": new_scale})
        db.commit()
        # Broadcast SET_SCALE to all registered devices
        try:
            from app.mqtt_publisher import publish_command as _pub_cmd
            from app.device_registry import db_device_secrets as _db_secrets
            _secrets = _db_secrets(db)
            for dev in db.scalars(select(Device).where(Device.enabled == True)).all():
                _pub_cmd(settings, dev.device_id, "SET_SCALE", {"time_scale": new_scale},
                         secret=_secrets.get(dev.device_id))
        except Exception as _exc:
            logger.warning("SET_SCALE broadcast failed: %s", _exc)
        return {"demo_time_scale": new_scale}

    @app.get("/api/admin/thresholds", tags=["cc-admin"])
    def get_system_thresholds(current_user: Annotated[User, Depends(AdminOnly)]):
        """Retrieve the live dynamic system thresholds."""
        from app.thresholds import get_thresholds
        return get_thresholds()

    @app.put("/api/admin/thresholds", tags=["cc-admin"])
    def update_system_thresholds(
        body: dict,
        db: DB,
        current_user: Annotated[User, Depends(AdminOnly)],
    ):
        """Update live dynamic system thresholds, persist to file, and downlink to devices."""
        from app.thresholds import update_thresholds
        try:
            updated = update_thresholds(
                body,
                actor=current_user.username,
                db=db,
                settings=settings,
            )
            db.commit()
            return updated
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.get("/api/report/summary", tags=["cc-report"])
    def report_summary(db: DB, current_user: Annotated[User, Depends(AnyRole)]):
        return {
            "fridges": db.scalar(select(func.count()).select_from(Fridge)),
            "batches": db.scalar(select(func.count()).select_from(Batch)),
            "at_risk": db.scalar(select(func.count()).select_from(Batch).where(Batch.status == "AT_RISK")),
            "discard": db.scalar(select(func.count()).select_from(Batch).where(Batch.status == "DISCARD")),
            "total_readings": db.scalar(select(func.count()).select_from(Reading)),
            "security_events": db.scalar(select(func.count()).select_from(SecurityEvent)),
            "audit_entries": db.scalar(select(func.count()).select_from(AuditLog)),
            "demo_time_scale": settings.demo_time_scale,
        }

    return app


# Missing import fix – require_role used in audit/security routes above
from app.security import require_role  # noqa: E402
from app.parameters_seed import SYSTEM_PARAMETER_KEYS, seed_system_parameters
