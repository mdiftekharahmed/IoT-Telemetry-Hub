import json
import re
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Device, IngestedMessage, Parameter, Telemetry, TelemetryRecord, utcnow
from app.schemas import TelemetryPayload, as_utc

TOPIC = re.compile(r"^devices/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/telemetry$")
MAX_PAYLOAD_BYTES = 16_384


class InvalidMessage(ValueError):
    pass


@dataclass(frozen=True)
class IngestResult:
    status: str
    stored: int = 0


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def ingest(factory: sessionmaker[Session], topic: str, payload: bytes) -> IngestResult:
    match = TOPIC.fullmatch(topic)
    if not match or len(payload) > MAX_PAYLOAD_BYTES:
        raise InvalidMessage("invalid topic or oversized payload")
    try:
        data = TelemetryPayload.model_validate(
            json.loads(payload.decode("utf-8"), object_pairs_hook=unique_keys)
        )
    except (UnicodeError, ValueError, ValidationError, RecursionError) as exc:
        raise InvalidMessage("invalid telemetry payload") from exc

    device_id = match.group(1)
    message_id = str(data.message_id)
    with factory() as db:
        try:
            with db.begin():
                device = db.get(Device, device_id)
                if device is None or not device.enabled:
                    return IngestResult("device_rejected")
                if db.get(IngestedMessage, (device_id, message_id)):
                    return IngestResult("duplicate")
                allowed = set(db.scalars(select(Parameter.name).where(Parameter.enabled.is_(True))))
                values = {key: value for key, value in data.values.items() if key in allowed}
                received_at = utcnow()
                db.add(
                    IngestedMessage(
                        device_id=device_id,
                        message_id=message_id,
                        received_at=received_at,
                    )
                )
                db.flush()
                timestamp = as_utc(data.timestamp) if data.timestamp else received_at
                record = None
                if values:
                    record = TelemetryRecord(
                        device_id=device_id, message_id=message_id,
                        timestamp=timestamp, received_at=received_at,
                    )
                    db.add(record)
                    db.flush()
                for parameter, value in values.items():
                    db.add(
                        Telemetry(
                            record_id=record.id,
                            device_id=device_id,
                            parameter=parameter,
                            value=value,
                            timestamp=timestamp,
                            received_at=received_at,
                        )
                    )
            return IngestResult("accepted", len(values))
        except IntegrityError:
            # A concurrent delivery may have committed this receipt first.
            db.rollback()
            if db.get(IngestedMessage, (device_id, message_id)):
                return IngestResult("duplicate")
            raise
