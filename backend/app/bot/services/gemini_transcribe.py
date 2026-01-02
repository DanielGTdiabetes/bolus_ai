import asyncio
import logging
from typing import Any, Dict, Optional

import google.generativeai as genai

from app.core import config

logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    "audio/ogg",
    "audio/opus",
    "audio/ogg; codecs=opus",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/mp4",
    "audio/m4a",
}

_configured = False


def _configure_genai() -> bool:
    """Configure the Gemini SDK safely."""
    global _configured
    if _configured:
        return True

    api_key = config.get_google_api_key()
    if not api_key:
        return False

    genai.configure(api_key=api_key)
    _configured = True
    return True


def _normalize_confidence(candidate: Any) -> Optional[float]:
    """
    Gemini audio responses do not expose a direct confidence.
    Use avg_logprob if present and map it to 0-1 for a rough heuristic.
    """
    try:
        avg_logprob = getattr(candidate, "avg_logprob", None)
        if avg_logprob is None:
            return None
        # Map typical logprob range (-10..0) into 0..1
        scaled = (avg_logprob + 10) / 10
        return max(0.0, min(1.0, scaled))
    except Exception:
        return None


async def transcribe_audio(file_bytes: bytes, mime_type: str) -> Dict[str, Optional[Any]]:
    """
    Transcribe audio with Gemini Flash.

    Returns: {"text": str | None, "confidence": float | None, "error": str | None}
    Error codes: missing_key, unsupported_format, too_large, provider_error
    """
    if not _configure_genai():
        return {"text": None, "confidence": None, "error": "missing_key"}

    if mime_type not in SUPPORTED_MIME_TYPES:
        return {"text": None, "confidence": None, "error": "unsupported_format"}

    max_bytes = config.get_max_voice_bytes()
    if len(file_bytes) > max_bytes:
        return {"text": None, "confidence": None, "error": "too_large"}

    model_name = config.get_gemini_transcribe_model()

    prompt = (
        "Transcribe la nota de voz de forma literal y concisa en el mismo idioma. "
        "No agregues comentarios ni formato extra."
    )

    try:
        model = genai.GenerativeModel(model_name)
        response = await asyncio.wait_for(
            model.generate_content_async(
                [prompt, {"mime_type": mime_type, "data": bytes(file_bytes)}]
            ),
            timeout=30.0,
        )

        text = (response.text or "").strip() if response else ""
        confidence = None
        try:
            if response and response.candidates:
                confidence = _normalize_confidence(response.candidates[0])
        except Exception:
            confidence = None

        return {"text": text, "confidence": confidence, "error": None}
    except asyncio.TimeoutError:
        logger.warning("Gemini transcription timeout.")
        return {"text": None, "confidence": None, "error": "provider_error"}
    except Exception as exc:  # pragma: no cover - depends on external service
        logger.error("Gemini transcription failed: %s", exc)
        return {"text": None, "confidence": None, "error": "provider_error"}

