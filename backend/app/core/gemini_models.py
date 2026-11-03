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
