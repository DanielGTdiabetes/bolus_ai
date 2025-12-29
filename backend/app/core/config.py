
import os
from typing import Optional

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

def get_telegram_webhook_secret() -> str:
    # Secret to verify updates come from Telegram
    return get_env("TELEGRAM_WEBHOOK_SECRET") or "change-me-in-production"

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
