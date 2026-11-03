"""Model migration shared by environment and persisted user configuration."""

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_GEMINI_PRO_MODEL = "gemini-3.8-flash"

_REPLACEMENTS = {
    "gemini-1.5-flash": DEFAULT_GEMINI_MODEL,
    "gemini-2.0-flash": DEFAULT_GEMINI_MODEL,
    "gemini-2.0-flash-exp": DEFAULT_GEMINI_MODEL,
    "gemini-2.5-flash": DEFAULT_GEMINI_MODEL,
    "gemini-3-flash-preview": DEFAULT_GEMINI_MODEL,
    "gemini-1.5-pro": DEFAULT_GEMINI_PRO_MODEL,
    "gemini-2.5-pro": DEFAULT_GEMINI_PRO_MODEL,
    "gemini-3-pro-preview": DEFAULT_GEMINI_PRO_MODEL,
}


def resolve_gemini_model(value: str | None, default: str = DEFAULT_GEMINI_MODEL) -> str:
    model = (value or default).strip().removeprefix("models/") or default
    return _REPLACEMENTS.get(model, model)


def migrate_gemini_settings(settings):
    """Normalize only model IDs in raw settings, preserving all other fields."""
    if not isinstance(settings, dict) or not isinstance(settings.get("vision"), dict):
        return settings
    vision = dict(settings["vision"])
    for key in ("gemini_model", "gemini_transcribe_model"):
        if isinstance(vision.get(key), str):
            vision[key] = resolve_gemini_model(vision[key])
    return {**settings, "vision": vision}
