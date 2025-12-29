import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.core import config

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    text: Optional[str]
    confidence: float
    provider: str
    error: Optional[str] = None


async def transcribe_audio(file_bytes: bytes, mime_type: str = "audio/ogg") -> TranscriptionResult:
    provider = config.get_voice_transcriber_provider()
    min_conf = config.get_voice_min_confidence()

    if provider == "none":
        return TranscriptionResult(
            text=None,
            confidence=0.0,
            provider="none",
            error="Transcripción no configurada. Define VOICE_TRANSCRIBER_PROVIDER y credenciales.",
        )

    # Simple stub using OpenAI Whisper via HTTP if OPENAI_API_KEY is present.
    # Kept lightweight; avoids new heavy dependencies.
    if provider in {"openai", "whisper"}:
        api_key = config.get_env("OPENAI_API_KEY")
        if not api_key:
            return TranscriptionResult(
                text=None,
                confidence=0.0,
                provider=provider,
                error="Falta OPENAI_API_KEY para transcribir audio.",
            )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Whisper API expects multipart/form-data
                files = {
                    "file": ("voice.ogg", file_bytes, mime_type),
                    "model": (None, "gpt-4o-transcribe"),
                }
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files=files,
                )
                resp.raise_for_status()
                data = resp.json()
                text = data.get("text")
                return TranscriptionResult(
                    text=text,
                    confidence=data.get("confidence", 0.8),
                    provider=provider,
                )
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Voice transcription failed: %s", exc)
            return TranscriptionResult(text=None, confidence=0.0, provider=provider, error=str(exc))

    return TranscriptionResult(
        text=None,
        confidence=0.0,
        provider=provider,
        error=f"Proveedor {provider} no soportado.",
    )
