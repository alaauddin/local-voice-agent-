import logging

from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 10 * 1024 * 1024


class TranscribeError(Exception):
    """Typed failure for the push-to-talk transcription path."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "audio.webm",
    content_type: str = "audio/webm",
) -> str:
    """Transcribe raw audio bytes to Arabic text via OpenAI.

    Raises TranscribeError with a stable ``code`` the API layer maps to HTTP.
    """
    if not settings.OPENAI_API_KEY:
        raise TranscribeError(
            "api_key_missing", "Speech transcription is not configured."
        )
    if not audio_bytes:
        raise TranscribeError("audio_empty", "No audio was recorded.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise TranscribeError(
            "audio_too_large", "The recording exceeds the 10 MB limit."
        )
    try:
        with OpenAI(api_key=settings.OPENAI_API_KEY, timeout=45) as client:
            result = client.audio.transcriptions.create(
                model=settings.REALTIME_TRANSCRIPTION_MODEL,
                file=(filename, audio_bytes, content_type or "audio/webm"),
                language="ar",
            )
    except Exception as exc:
        logger.warning("Push-to-talk transcription failed: %s", type(exc).__name__)
        raise TranscribeError(
            "provider_error", "Unable to transcribe the recording.", retryable=True
        ) from exc
    return (result.text or "").strip()
