from dataclasses import dataclass
from typing import Optional

from app.bot.services import gemini_transcribe


@dataclass
class TranscriptionResult:
    text: Optional[str]
    confidence: Optional[float]
    provider: str
    error: Optional[str] = None


async def transcribe_audio(file_bytes: bytes, mime_type: str = "audio/ogg", model_name: Optional[str] = None) -> TranscriptionResult:
    provider = "gemini"
    result = await gemini_transcribe.transcribe_audio(file_bytes, mime_type, model_name=model_name)
    return TranscriptionResult(
        text=result.get("text"),
        confidence=result.get("confidence"),
        provider=provider,
        error=result.get("error"),
    )
