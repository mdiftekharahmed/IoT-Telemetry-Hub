from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite:///./telemetry.db"
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    max_devices: int = Field(default=10, ge=1, le=10)
    secure_cookies: bool = False
    demo_mode: bool = False
    system_temp_min: float | None = Field(default=None, allow_inf_nan=False)
    system_temp_max: float | None = Field(default=None, allow_inf_nan=False)
    system_temp_unit: str = Field(default="", max_length=16)
    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str = "collector"
    mqtt_password: SecretStr = SecretStr("")
    mqtt_client_id: str = "telemetry-hub-collector"
    mqtt_tls: bool = False
    mqtt_ca_file: str = ""

    @model_validator(mode="after")
    def valid_temperature_range(self):
        if self.system_temp_min is not None and self.system_temp_max is not None:
            if self.system_temp_min > self.system_temp_max:
                raise ValueError("SYSTEM_TEMP_MIN must be at most SYSTEM_TEMP_MAX")
        return self
