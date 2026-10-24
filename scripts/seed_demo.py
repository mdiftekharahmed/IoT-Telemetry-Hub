import math
import os
import sys
from datetime import timedelta
from pathlib import Path

# Add project root to sys.path so app can be imported from any working directory
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from alembic import command
from alembic.config import Config

from app.db import build_engine, session_factory
from app.models import Admin, Device, Parameter, Telemetry, utcnow
from app.security import password_hasher

demo_file = project_root / "demo.db"
if demo_file.exists():
    raise SystemExit("demo.db already exists. No changes made.")
os.environ["DATABASE_URL"] = f"sqlite:///{demo_file.as_posix()}"
command.upgrade(Config(str(project_root / "alembic.ini")), "head")
engine = build_engine(os.environ["DATABASE_URL"])
try:
    with session_factory(engine).begin() as db:
        db.add(Admin(username="demo", password_hash=password_hasher.hash("local-preview-only")))
        devices = [
            ("MGRV-001", "Riverside station", True),
            ("MGRV-002", "Forest edge", True),
            ("MGRV-003", "Estuary station", True),
            ("MGRV-004", "North creek", False),
        ]
        for device_id, name, enabled in devices:
            db.add(Device(device_id=device_id, name=name, enabled=enabled))
        for name in ("temperature", "humidity", "soil_moisture", "water_level", "conductivity"):
            db.add(Parameter(name=name, enabled=name != "conductivity"))
        db.flush()
        now = utcnow()
        parameters = [
            ("temperature", 29.8),
            ("humidity", 72.4),
            ("soil_moisture", 41.6),
            ("water_level", 76.9),
        ]
        for index in range(84):
            parameter, base = parameters[index % len(parameters)]
            timestamp = now - timedelta(minutes=(83 - index) * 4)
            db.add(
                Telemetry(
                    timestamp=timestamp,
                    received_at=timestamp,
                    device_id=devices[index % 3][0],
                    parameter=parameter,
                    value=round(base + math.sin(index) * 2, 2),
                )
            )
    print("Created demo.db with synthetic readings. Local preview login: demo / local-preview-only")
    print("Start with DATABASE_URL=sqlite:///./demo.db and DEMO_MODE=true; bind to 127.0.0.1 only.")
finally:
    engine.dispose()
