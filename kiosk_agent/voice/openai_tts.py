import asyncio
import base64
import logging

from django.conf import settings
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
MAX_TTS_RETRIES = 2


async def synthesize_mp3(
    client: AsyncOpenAI, *, text: str, request_id: str, sequence: int
) -> str | None:
    """Return base64 MP3, or None after bounded retryable failures."""
    for attempt in range(MAX_TTS_RETRIES + 1):
        try:
            response = await client.audio.speech.create(
                model=settings.VOICE_MODEL,
                voice=settings.VOICE_NAME,
                input=text,
                speed=settings.VOICE_SPEED,
                response_format="mp3",
                instructions=settings.VOICE_INSTRUCTIONS or None,
            )
            return base64.b64encode(response.content).decode("ascii")
        except Exception as exc:
            logger.warning(
                "TTS attempt %s/%s failed for request %s chunk %s: %s",
                attempt + 1,
                MAX_TTS_RETRIES + 1,
                request_id,
                sequence,
                type(exc).__name__,
            )
            if attempt < MAX_TTS_RETRIES:
                await asyncio.sleep(0.5 * (attempt + 1))
    return None
