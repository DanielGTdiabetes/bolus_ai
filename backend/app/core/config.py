
import os
from typing import Optional, Tuple

def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, default)

def get_vision_provider() -> str:
    """
    Returns 'gemini', 'openai', or 'none'.
    Prioritizes VISION_PROVIDER, then PHOTO_ESTIMATOR_PROVIDER.
    """
    val = get_env("VISION_PROVIDER") or get_env("PHOTO_ESTIMATOR_PROVIDER")
    return val.lower() if val else "none"

def get_google_api_key() -> str:
    """
    Returns Google API Key from GOOGLE_API_KEY or GEMINI_API_KEY.
    """
    return get_env("GOOGLE_API_KEY") or get_env("GEMINI_API_KEY") or ""

def get_gemini_model() -> str:
    # Updated default to 3.0 Flash Preview as per Render config
    return get_env("GEMINI_MODEL") or "gemini-3-flash-preview"

def get_gemini_pro_model() -> str:
    # Dedicated model for reasoning/complex tasks
    return get_env("GEMINI_MODEL_PRO") or "gemini-3-pro-preview"

# --- Telegram Bot Config ---
def get_telegram_bot_token() -> Optional[str]:
    return get_env("TELEGRAM_BOT_TOKEN")

def get_telegram_webhook_secret() -> Optional[str]:
    """
    Secret used by Telegram to sign webhook requests.

    Returning None means no validation will be performed and secret_token will
    not be sent during setWebhook.
    """
    val = get_env("TELEGRAM_WEBHOOK_SECRET")
    return val.strip() if val else None


def get_public_bot_url_with_source() -> Tuple[Optional[str], str]:
    """
    Return the public URL to use for Telegram webhooks and the source env key.

    Priority:
    1. BOT_PUBLIC_URL (explicit override)
    2. RENDER_EXTERNAL_URL (Render auto-env)
    3. PUBLIC_URL / public_url (legacy naming)
    """

    candidates = [
        (get_env("BOT_PUBLIC_URL"), "BOT_PUBLIC_URL"),
        (get_env("RENDER_EXTERNAL_URL"), "RENDER_EXTERNAL_URL"),
        (get_env("PUBLIC_URL"), "PUBLIC_URL"),
        (get_env("public_url"), "PUBLIC_URL"),
    ]

    for url, source in candidates:
        if url:
            return url.rstrip("/"), source
    return None, "none"


def get_public_bot_url() -> Optional[str]:
    url, _ = get_public_bot_url_with_source()
    return url


def get_public_app_url_with_source() -> Tuple[Optional[str], str]:
    """
    Return the public URL for the web app to reference in outbound notifications.

    Priority:
    1. NAS_EXTERNAL_URL (primary NAS public URL)
    2. RENDER_EXTERNAL_URL (Render public URL)
    """
    candidates = [
        (get_env("NAS_EXTERNAL_URL"), "NAS_EXTERNAL_URL"),
        (get_env("RENDER_EXTERNAL_URL"), "RENDER_EXTERNAL_URL"),
    ]

    for url, source in candidates:
        if url:
            return url.rstrip("/"), source
    return None, "none"


def get_public_app_url() -> Optional[str]:
    url, _ = get_public_app_url_with_source()
    return url


def get_admin_shared_secret() -> Optional[str]:
    """
    Shared secret for admin-like actions (e.g., webhook refresh).
    """
    val = get_env("ADMIN_SHARED_SECRET")
    return val.strip() if val else None


def get_bot_poll_interval() -> float:
    try:
        return float(get_env("TELEGRAM_POLL_INTERVAL", "1.5"))
    except ValueError:
        return 1.5


def get_bot_read_timeout() -> int:
    try:
        return int(get_env("TELEGRAM_POLL_TIMEOUT", "20"))
    except ValueError:
        return 20


def get_bot_leader_ttl_seconds() -> int:
    try:
        return int(get_env("BOT_LEADER_TTL_SECONDS", "60"))
    except ValueError:
        return 60


def get_bot_leader_renew_seconds() -> int:
    try:
        return int(get_env("BOT_LEADER_RENEW_SECONDS", "20"))
    except ValueError:
        return 20


def get_voice_transcriber_provider() -> str:
    return (get_env("VOICE_TRANSCRIBER_PROVIDER") or "gemini").lower()


def get_voice_min_confidence() -> float:
    try:
        return float(get_env("VOICE_TRANSCRIBER_MIN_CONFIDENCE", "0.6"))
    except ValueError:
        return 0.6

def get_gemini_transcribe_model() -> str:
    # Use 2.0 Flash Exp for audio/vision by default if not set
    return get_env("GEMINI_TRANSCRIBE_MODEL") or "gemini-2.0-flash-exp"

def is_telegram_voice_enabled() -> bool:
    """
    Voice is auto-enabled when a Google/Gemini API key is present unless
    ENABLE_TELEGRAM_VOICE is explicitly set.
    """
    val = get_env("ENABLE_TELEGRAM_VOICE")
    if val is None:
        return bool(get_google_api_key())
    return val.lower() == "true"

def get_max_voice_seconds() -> int:
    try:
        return int(get_env("MAX_VOICE_SECONDS", "45"))
    except ValueError:
        return 45

def get_max_voice_mb() -> float:
    try:
        return float(get_env("MAX_VOICE_MB", "10"))
    except ValueError:
        return 10.0

def get_max_voice_bytes() -> int:
    return int(get_max_voice_mb() * 1024 * 1024)

def get_allowed_telegram_user_id() -> Optional[int]:
    # Security: Only allow this user ID to interact
    val = get_env("ALLOWED_TELEGRAM_USER_ID")
    return int(val) if val and val.isdigit() else None

def is_telegram_bot_enabled() -> bool:
    # Feature flag to kill the bot if needed
    val = get_env("ENABLE_TELEGRAM_BOT", "true")
    return val.lower() == "true"

def get_vision_timeout() -> int:
    try:
        return int(get_env("GEMINI_TIMEOUT_SECONDS") or get_env("VISION_TIMEOUT_SECONDS") or "60")
    except ValueError:
        return 60

def get_bot_default_username() -> str:
    return get_env("BOT_DEFAULT_USERNAME", "admin")
