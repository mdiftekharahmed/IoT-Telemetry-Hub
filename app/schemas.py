import math
import re
from datetime import UTC, datetime
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
ParameterName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviceCreate(InputModel):
    device_id: Identifier
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True

    @field_validator("device_id")
    @classmethod
    def reserve_collector(cls, value):
        if value == "collector":
            raise ValueError("collector is reserved for the MQTT service")
        return value

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()


class DeviceUpdate(InputModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool

    _nonblank_name = field_validator("name")(DeviceCreate.nonblank_name.__func__)


class DeviceOut(DeviceCreate):
    model_config = ConfigDict(from_attributes=True)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value):
        return as_utc(value)


class DeviceCreateOut(DeviceOut):
    mqtt_password: str | None = None


class ParameterCreate(InputModel):
    name: ParameterName
    unit: str | None = Field(default=None, max_length=16)
    enabled: bool = True


class ParameterUpdate(InputModel):
    unit: str | None = Field(default=None, max_length=16)
    enabled: bool


class ParameterOut(ParameterCreate):
    model_config = ConfigDict(from_attributes=True)


class Login(InputModel):
    username: Identifier
    password: str = Field(min_length=1, max_length=1024)


class ProfileUpdate(InputModel):
    full_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254)

    @field_validator("full_name", "email", mode="before")
    @classmethod
    def trim_optional(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address")
        return value


class ProfileOut(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)
    username: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc_dates(cls, value):
        return as_utc(value) if value else None


class TelemetryPayload(InputModel):
    message_id: str = Field(min_length=1, max_length=36)
    timestamp: AwareDatetime | None = None
    values: dict[ParameterName, float] = Field(min_length=1, max_length=100)

    @field_validator("values", mode="before")
    @classmethod
    def numeric_values(cls, values):
        if not isinstance(values, dict):
            raise ValueError("values must be an object")
        for value in values.values():
            if type(value) not in (int, float):
                raise ValueError("only numeric sensor values are supported")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("sensor values must be finite")
        return values


def as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; all persisted values are normalized to UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class TelemetryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    timestamp: datetime
    received_at: datetime
    device_id: str
    parameter: str
    value: float

    _utc_dates = field_validator("timestamp", "received_at")(as_utc)
