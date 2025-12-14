
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
    # Fallback to 1.5-flash which has higher rate limits (1500 RPD vs 20 RPD for 2.5)
    return get_env("GEMINI_MODEL") or "gemini-1.5-flash"

def get_vision_timeout() -> int:
    try:
        return int(get_env("GEMINI_TIMEOUT_SECONDS") or get_env("VISION_TIMEOUT_SECONDS") or "20")
    except ValueError:
        return 20
