from app.config import Settings


def device_health(values: dict[str, float], settings: Settings) -> str:
    """Health belongs to this recorded message; absent data/rules are never OK."""
    value = values.get("systemTemp")
    if value is None or (settings.system_temp_min is None and settings.system_temp_max is None):
        return "unknown"
    if settings.system_temp_min is not None and value < settings.system_temp_min:
        return "not_ok"
    if settings.system_temp_max is not None and value > settings.system_temp_max:
        return "not_ok"
    return "ok"
