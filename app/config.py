"""Application settings – original + ColdChain extensions."""

import json

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # ── Database ───────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./telemetry.db"

    # ── Legacy session auth ────────────────────────────────────────────────────
    session_ttl_hours: int   = Field(default=12, ge=1, le=168)
    max_devices:       int   = Field(default=10, ge=1, le=100)
    secure_cookies:    bool  = False
    demo_mode:         bool  = False

    system_temp_min:  float | None = Field(default=10.0, allow_inf_nan=False)
    system_temp_max:  float | None = Field(default=50.0, allow_inf_nan=False)
    system_temp_unit: str          = Field(default="", max_length=16)

    # ── MQTT ───────────────────────────────────────────────────────────────────
    mqtt_host:      str       = "localhost"
    mqtt_port:      int       = Field(default=1883, ge=1, le=65535)
    mqtt_username:  str       = "collector"
    mqtt_password:  SecretStr = SecretStr("")
    mqtt_client_id: str       = "telemetry-hub-collector"
    mqtt_tls:       bool      = False
    mqtt_ca_file:   str       = ""

    # ── ColdChain: JWT ─────────────────────────────────────────────────────────
    coldchain_jwt_secret: str = Field(default="change-me-in-production", min_length=16)

    # ── ColdChain: per-device HMAC secrets ────────────────────────────────────
    # JSON string: '{"fridge-A":"aabb...","fridge-B":"ccdd..."}'
    device_secrets_json: str = Field(default="{}")

    @property
    def device_secrets(self) -> dict[str, str]:
        try:
            return json.loads(self.device_secrets_json)
        except Exception:
            return {}

    def device_secret(self, device_id: str) -> str | None:
        return self.device_secrets.get(device_id)

    # ── ColdChain: Telegram ────────────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id:   str = ""

    # ── ColdChain: demo / simulation ───────────────────────────────────────────
    demo_time_scale:  float = Field(default=1.0, ge=0.1, le=1000.0)
    hmac_ts_window_s: int   = Field(default=60,  ge=10,  le=300)

    # ── Validators ─────────────────────────────────────────────────────────────
    @model_validator(mode="after")
    def valid_temperature_range(self) -> "Settings":
        if self.system_temp_min is not None and self.system_temp_max is not None:
            if self.system_temp_min > self.system_temp_max:
                raise ValueError("SYSTEM_TEMP_MIN must be at most SYSTEM_TEMP_MAX")
        return self
