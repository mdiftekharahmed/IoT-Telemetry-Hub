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
from pydantic import AwareDatetime
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

import app.audit as audit_mod
import app.alerts as alert_mod
from app.budget_engine import reset_discard, update_exposure
from app.config import Settings
from app.db import build_engine, session_factory
from app.health import device_health
from app.models import (
    Admin, AdminSession, Alert, AuditLog, Batch, BatchMovement, Device,
    Fridge, IngestedMessage, MlPrediction, Parameter, Reading,
    RelocationSuggestion, SecurityEvent, Telemetry, TelemetryRecord,
    User, UserProfile, utcnow,
)
from app.schemas import (
    DeviceCreate, DeviceCreateOut, DeviceOut, DeviceUpdate,
    Login, ParameterCreate, ParameterOut, ParameterUpdate,
    ProfileOut, ProfileUpdate, TelemetryOut, as_utc,
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
) -> AdminSession:
    """Legacy cookie/bearer session for the old admin SPA."""
    token = credentials.credentials if credentials else request.cookies.get("telemetry_session")
    if not credentials and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("X-Requested-With") != "telemetry-ui":
            raise HTTPException(403, "Same-origin request header required")
    session = db.get(AdminSession, token_digest(token)) if token else None
    if session is None or as_utc(session.expires_at) <= utcnow():
        raise HTTPException(401, "Authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    return session


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


# ─────────────────────────────────────────────────────────────────────────────
# Application factory
# ─────────────────────────────────────────────────────────────────────────────

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine   = build_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
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
            raise HTTPException(503, "Database unavailable or migrations pending") from exc
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
    def cc_refresh(request: Request, db: DB):
        body = {}
        try:
            import asyncio
            body = asyncio.get_event_loop().run_until_complete(request.json())
        except Exception:
            raise HTTPException(400, "JSON body with refresh_token required")
        refresh_token = body.get("refresh_token", "")
        payload = decode_refresh_token(refresh_token, settings.coldchain_jwt_secret)
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
        alphabet = string.ascii_letters + string.digits
        device.mqtt_password = "".join(secrets.choice(alphabet) for _ in range(16))
        db.add(device)
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

    @app.get("/api/parameters", response_model=list[ParameterOut], tags=["parameters"])
    def parameters(auth: Auth, db: DB):
        return db.scalars(select(Parameter).order_by(Parameter.name)).all()

    @app.post("/api/parameters", response_model=ParameterOut, status_code=201, tags=["parameters"])
    def add_parameter(body: ParameterCreate, auth: Auth, db: DB):
        parameter = Parameter(**body.model_dump()); db.add(parameter); commit(db); return parameter

    @app.put("/api/parameters/{name}", response_model=ParameterOut, tags=["parameters"])
    def update_parameter(name: str, body: ParameterUpdate, auth: Auth, db: DB):
        parameter = db.get(Parameter, name)
        if parameter is None: raise HTTPException(404, "Parameter not found")
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(parameter, key, value)
        commit(db); return parameter

    @app.delete("/api/parameters/{name}", status_code=204, tags=["parameters"])
    def remove_parameter(name: str, auth: Auth, db: DB):
        result = db.execute(delete(Parameter).where(Parameter.name == name))
        if not result.rowcount: raise HTTPException(404, "Parameter not found")
        db.commit(); return Response(status_code=204)

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
    def create_fridge(body: dict, db: DB,
                      current_user: Annotated[User, Depends(AdminOnly)]):
        f = Fridge(name=body["name"],
                   capacity_slots=body.get("capacity_slots", 10),
                   location=body.get("location"),
                   device_id=body.get("device_id"))
        db.add(f); db.commit(); db.refresh(f)
        audit_mod.append(db, actor=current_user.username, action="FRIDGE_CREATED",
                         payload={"fridge_id": f.id, "name": f.name})
        db.commit()
        return _fridge_dict(f, None)

    @app.get("/api/fridges/{fridge_id}/live", tags=["cc-fridges"])
    def fridge_live(fridge_id: int, db: DB,
                    current_user: Annotated[User, Depends(AnyRole)]):
        f = fridge_or_404(db, fridge_id)
        latest = None
        if f.device_id:
            latest = db.scalar(
                select(Reading).where(Reading.device_id == f.device_id)
                .order_by(Reading.ts.desc()).limit(1))
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
            b = reset_discard(db, batch_id, actor=current_user.username,
                              reason=body.get("reason", "admin reset"))
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
        if not device: raise HTTPException(404, "Device not found")
        audit_mod.append(db, actor=current_user.username, action="SIM_FAULT",
                         payload={"device_id": device_id, **body})
        db.commit()
        # Push command to device via MQTT (worker publishes)
        # The worker is a separate process; we store the command in the audit log
        # and the next iteration of the worker picks it up from a command queue (TODO: event bus).
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
        return {"demo_time_scale": new_scale}

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
