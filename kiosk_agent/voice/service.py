import asyncio

from django.conf import settings
from openai import AsyncOpenAI

from .config import VoiceSource
from .events import voice_chunk, voice_completed, voice_fallback, voice_skipped, voice_status
from .openai_tts import synthesize_mp3
from .text import clean_spoken_text, split_spoken_text


async def _synthesize_and_publish(
    client: AsyncOpenAI,
    *,
    chunk: str,
    seq: int,
    total: int,
    stay_id: str,
    request_id: str,
    nonce: str,
    semaphore: asyncio.Semaphore,
) -> None:
    async with semaphore:
        audio = await synthesize_mp3(
            client, text=chunk, request_id=request_id, sequence=seq
        )
    await voice_chunk(
        stay_id,
        request_id,
        nonce=nonce,
        seq=seq,
        total=total,
        text=chunk,
        audio=audio,
    )


async def generate_and_publish_tts(
    *, text: str, stay_id: str, request_id: str, client: AsyncOpenAI | None = None
) -> None:
    """Run one voice-output request and always publish a terminal event."""
    clean = clean_spoken_text(text)
    nonce = request_id
    if not clean:
        await voice_skipped(stay_id, request_id, nonce=nonce, reason="empty_text")
        return
    if settings.VOICE_SOURCE == VoiceSource.OFF:
        await voice_skipped(stay_id, request_id, nonce=nonce, reason="voice_off")
        return
    if settings.VOICE_SOURCE != VoiceSource.BACKEND:
        await voice_skipped(stay_id, request_id, nonce=nonce, reason="source_not_backend")
        return
    if not settings.OPENAI_API_KEY:
        await voice_fallback(
            stay_id,
            request_id,
            nonce=nonce,
            text=clean,
            reason="api_key_missing",
        )
        return

    chunks = split_spoken_text(clean)
    await voice_status(stay_id, request_id, nonce=nonce, total=len(chunks))
    semaphore = asyncio.Semaphore(settings.VOICE_TTS_CONCURRENCY)
    owns_client = client is None
    if client is None:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        await asyncio.gather(
            *(
                _synthesize_and_publish(
                    client,
                    chunk=chunk,
                    seq=seq,
                    total=len(chunks),
                    stay_id=stay_id,
                    request_id=request_id,
                    nonce=nonce,
                    semaphore=semaphore,
                )
                for seq, chunk in enumerate(chunks)
            )
        )
    finally:
        if owns_client:
            await client.close()
    await voice_completed(stay_id, request_id, nonce=nonce, total=len(chunks))
