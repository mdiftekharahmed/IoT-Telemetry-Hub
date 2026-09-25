import csv
import io
import secrets
import string
import subprocess
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import build_engine, session_factory
from app.models import (
    Admin, AdminSession, Device, IngestedMessage, Parameter, Telemetry, TelemetryRecord,
    UserProfile, utcnow,
)
from app.health import device_health
from app.schemas import (
    DeviceCreate,
    DeviceOut,
    DeviceUpdate,
    Login,
    ParameterCreate,
    ParameterOut,
    ParameterUpdate,
    ProfileOut,
    ProfileUpdate,
    TelemetryOut,
    as_utc,
)
from app.security import DUMMY_HASH, create_session, password_hasher, token_digest

bearer = HTTPBearer(auto_error=False)


def db_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as db:
        yield db


def authenticated(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(db_session)],
) -> AdminSession:
    token = credentials.credentials if credentials else request.cookies.get("telemetry_session")
    if not credentials and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("X-Requested-With") != "telemetry-ui":
            raise HTTPException(403, "Same-origin request header required")
    session = db.get(AdminSession, token_digest(token)) if token else None
    if session is None or as_utc(session.expires_at) <= utcnow():
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    return session


DB = Annotated[Session, Depends(db_session)]
Auth = Annotated[AdminSession, Depends(authenticated)]


def date_range(
    start: Annotated[AwareDatetime, Query()],
    end: Annotated[AwareDatetime, Query()],
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = build_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="IoT Telemetry Hub", version="0.1.0", lifespan=lifespan)
    app.state.sessions = session_factory(engine)
    app.state.engine = engine
    assets = Path(__file__).parent
    app.mount("/static", StaticFiles(directory=assets / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if not request.url.path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'self'; form-action 'self'"
            )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/login", include_in_schema=False)
    def login_page():
        return FileResponse(assets / "templates" / "login.html")

    @app.get("/", include_in_schema=False)
    @app.get("/devices", include_in_schema=False)
    @app.get("/parameters", include_in_schema=False)
    @app.get("/data", include_in_schema=False)
    @app.get("/export", include_in_schema=False)
    def admin_page():
        return FileResponse(assets / "templates" / "app.html")

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready(db: DB):
        try:
            db.execute(select(Admin.username).limit(1))
        except SQLAlchemyError as exc:
            raise HTTPException(503, "Database unavailable or migrations pending") from exc
        return {"status": "ok"}

    @app.post("/api/auth/login", tags=["auth"])
    def login(body: Login, db: DB, response: Response):
        admin = db.get(Admin, body.username)
        valid = password_hasher.verify(body.password, admin.password_hash if admin else DUMMY_HASH)
        if not admin or not valid:
            raise HTTPException(401, "Invalid username or password")
        response.headers["Cache-Control"] = "no-store"
        token = create_session(db, admin.username, settings.session_ttl_hours)
        response.set_cookie(
            "telemetry_session",
            token,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="strict",
            max_age=settings.session_ttl_hours * 3600,
        )
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": settings.session_ttl_hours * 3600,
        }

    @app.post("/api/auth/logout", status_code=204, tags=["auth"])
    def logout(auth: Auth, db: DB):
        db.delete(auth)
        db.commit()
        response = Response(status_code=204)
        response.delete_cookie("telemetry_session")
        return response

    @app.get("/api/auth/me", tags=["auth"])
    def me(auth: Auth, db: DB):
        profile = db.get(UserProfile, auth.username)
        return {
            "username": auth.username,
            "full_name": profile.full_name if profile else None,
            "demo_mode": settings.demo_mode,
            "max_devices": settings.max_devices,
        }

    @app.get("/api/profile", response_model=ProfileOut, tags=["profile"])
    def get_profile(auth: Auth, db: DB):
        return db.get(UserProfile, auth.username) or ProfileOut(username=auth.username)

    @app.put("/api/profile", response_model=ProfileOut, tags=["profile"])
    def update_profile(body: ProfileUpdate, auth: Auth, db: DB):
        profile = db.get(UserProfile, auth.username)
        if profile is None:
            profile = UserProfile(username=auth.username)
            db.add(profile)
        profile.full_name, profile.email = body.full_name, body.email
        commit(db)
        return profile

    @app.get("/api/summary", tags=["telemetry"])
    def summary(auth: Auth, db: DB):
        latest = db.scalar(select(func.max(Telemetry.received_at)))
        return {
            "devices": db.scalar(select(func.count()).select_from(Device)),
            "enabled_devices": db.scalar(
                select(func.count()).select_from(Device).where(Device.enabled.is_(True))
            ),
            "parameters": db.scalar(select(func.count()).select_from(Parameter)),
            "enabled_parameters": db.scalar(
                select(func.count()).select_from(Parameter).where(Parameter.enabled.is_(True))
            ),
            "readings": db.scalar(select(func.count()).select_from(Telemetry)),
            "records": db.scalar(select(func.count()).select_from(TelemetryRecord)),
            "last_received_at": as_utc(latest) if latest else None,
        }

    @app.get("/api/devices", response_model=list[DeviceOut], tags=["devices"])
    def devices(auth: Auth, db: DB):
        return db.scalars(select(Device).order_by(Device.device_id)).all()

    @app.post("/api/devices", response_model=DeviceOut, status_code=201, tags=["devices"])
    def add_device(body: DeviceCreate, auth: Auth, db: DB):
        # Serialize capacity checks across API workers on PostgreSQL.
        if db.bind.dialect.name == "postgresql":
            db.execute(text("LOCK TABLE devices IN SHARE ROW EXCLUSIVE MODE"))
        if db.get(Device, body.device_id):
            raise HTTPException(409, "Device already exists")
        if db.scalar(select(func.count()).select_from(Device)) >= settings.max_devices:
            raise HTTPException(
                409, f"Maximum of {settings.max_devices} registered devices reached"
            )
        device = Device(**body.model_dump())
        
        # Auto-generate an MQTT password
        alphabet = string.ascii_letters + string.digits
        device.mqtt_password = ''.join(secrets.choice(alphabet) for _ in range(16))
        
        db.add(device)
        commit(db)
        
        pw_file = Path("/secrets/mosquitto.passwd")
        if pw_file.exists():
            try:
                subprocess.run(["mosquitto_passwd", "-b", str(pw_file), device.device_id, device.mqtt_password], check=True)
            except Exception as e:
                print(f"Warning: failed to update mosquitto password: {e}")
        
        return device

    @app.put("/api/devices/{device_id}", response_model=DeviceOut, tags=["devices"])
    def update_device(device_id: str, body: DeviceUpdate, auth: Auth, db: DB):
        device = db.get(Device, device_id)
        if device is None:
            raise HTTPException(404, "Device not found")
        device.name, device.enabled = body.name, body.enabled
        commit(db)
        return device

    @app.delete("/api/devices/{device_id}/telemetry", status_code=204, tags=["devices"])
    def clear_device_telemetry(device_id: str, auth: Auth, db: DB):
        """Delete all telemetry data for a device. The device registration is kept."""
        if db.get(Device, device_id) is None:
            raise HTTPException(404, "Device not found")
        # Delete in dependency order: readings first, then the registry records
        # that group them, then the deduplication receipts so the device starts clean.
        db.execute(delete(Telemetry).where(Telemetry.device_id == device_id))
        db.execute(delete(TelemetryRecord).where(TelemetryRecord.device_id == device_id))
        db.execute(delete(IngestedMessage).where(IngestedMessage.device_id == device_id))
        db.commit()
        return Response(status_code=204)

    @app.delete("/api/devices/{device_id}", status_code=204, tags=["devices"])
    def remove_device(device_id: str, auth: Auth, db: DB):
        """Delete a device and all of its telemetry data."""
        if db.get(Device, device_id) is None:
            raise HTTPException(404, "Device not found")
            
        # Delete telemetry first (foreign key constraints)
        db.execute(delete(Telemetry).where(Telemetry.device_id == device_id))
        db.execute(delete(TelemetryRecord).where(TelemetryRecord.device_id == device_id))
        db.execute(delete(IngestedMessage).where(IngestedMessage.device_id == device_id))
        
        # Delete device
        db.execute(delete(Device).where(Device.device_id == device_id))
        db.commit()
        
        # Remove MQTT password
        pw_file = Path("/secrets/mosquitto.passwd")
        if pw_file.exists():
            try:
                subprocess.run(["mosquitto_passwd", "-D", str(pw_file), device_id], check=True)
            except Exception as e:
                print(f"Warning: failed to remove mosquitto password: {e}")
                
        return Response(status_code=204)

    @app.get("/api/parameters", response_model=list[ParameterOut], tags=["parameters"])
    def parameters(auth: Auth, db: DB):
        return db.scalars(select(Parameter).order_by(Parameter.name)).all()

    @app.post("/api/parameters", response_model=ParameterOut, status_code=201, tags=["parameters"])
    def add_parameter(body: ParameterCreate, auth: Auth, db: DB):
        parameter = Parameter(**body.model_dump())
        db.add(parameter)
        commit(db)
        return parameter

    @app.put("/api/parameters/{name}", response_model=ParameterOut, tags=["parameters"])
    def update_parameter(name: str, body: ParameterUpdate, auth: Auth, db: DB):
        parameter = db.get(Parameter, name)
        if parameter is None:
            raise HTTPException(404, "Parameter not found")
        parameter.enabled = body.enabled
        commit(db)
        return parameter

    @app.delete("/api/parameters/{name}", status_code=204, tags=["parameters"])
    def remove_parameter(name: str, auth: Auth, db: DB):
        result = db.execute(delete(Parameter).where(Parameter.name == name))
        if not result.rowcount:
            raise HTTPException(404, "Parameter not found")
        db.commit()
        return Response(status_code=204)

    @app.get("/api/telemetry", response_model=list[TelemetryOut], tags=["telemetry"])
    def telemetry(
        auth: Auth,
        db: DB,
        limit: int = Query(default=100, ge=1, le=1000),
        before_id: int | None = Query(default=None, ge=1),
    ):
        statement = select(Telemetry).order_by(Telemetry.id.desc()).limit(limit)
        if before_id is not None:
            statement = statement.where(Telemetry.id < before_id)
        return db.scalars(statement).all()

    @app.get("/api/telemetry/export", tags=["telemetry"])
    def export(auth: Auth, dates: Annotated[tuple[datetime, datetime], Depends(date_range)]):
        start, end = dates

        def rows():
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow(["timestamp", "device_id", "parameter", "value"])
            yield output.getvalue()
            with app.state.sessions() as db:
                statement = (
                    select(Telemetry)
                    .where(Telemetry.timestamp >= start, Telemetry.timestamp < end)
                    .order_by(Telemetry.timestamp, Telemetry.id)
                    .execution_options(yield_per=1000)
                )
                for row in db.scalars(statement):
                    if row.parameter == "systemTemp":
                        continue
                    output.seek(0)
                    output.truncate(0)
                    writer.writerow(
                        [
                            as_utc(row.timestamp).isoformat(),
                            row.device_id,
                            row.parameter,
                            row.value,
                        ]
                    )
                    yield output.getvalue()

        return StreamingResponse(
            rows(),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="telemetry.csv"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/telemetry/records", tags=["telemetry"])
    def telemetry_records(
        auth: Auth, db: DB,
        limit: int = Query(default=12, ge=1, le=100),
        before_id: int | None = Query(default=None, ge=1),
    ):
        statement = (
            select(TelemetryRecord, Device.name)
            .join(Device, Device.device_id == TelemetryRecord.device_id)
            .order_by(TelemetryRecord.id.desc()).limit(limit + 1)
        )
        if before_id is not None:
            statement = statement.where(TelemetryRecord.id < before_id)
        entries = db.execute(statement).all()
        page = entries[:limit]
        values = {record.id: {} for record, _ in page}
        if values:
            for reading in db.scalars(select(Telemetry).where(Telemetry.record_id.in_(values))):
                values[reading.record_id][reading.parameter] = reading.value
        columns = sorted(set(db.scalars(select(Parameter.name))) | set(
            db.scalars(select(Telemetry.parameter).distinct())
        ))
        return {
            "columns": columns,
            "records": [{
                "registry_id": record.id, "device_id": record.device_id,
                "device_name": name, "timestamp": as_utc(record.timestamp),
                "values": values[record.id],
                "health": device_health(values[record.id], settings),
            } for record, name in page],
            "next_cursor": page[-1][0].id if len(entries) > limit else None,
            "health_rule": {
                "parameter": "systemTemp", "min": settings.system_temp_min,
                "max": settings.system_temp_max, "unit": settings.system_temp_unit,
            },
        }

    return app
