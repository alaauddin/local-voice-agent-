import asyncio
import base64
import logging
import re

from django.conf import settings
from openai import AsyncOpenAI

from .agent_engine import publish

logger = logging.getLogger(__name__)

MAX_TTS_RETRIES = 2
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)


def clean_spoken_text(text: str) -> str:
    """Remove visual-only formatting while preserving natural spoken punctuation."""
    clean = _EMOJI_PATTERN.sub("", text)
    clean = re.sub(r"[*_#`\[\]{}<>]", "", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def split_spoken_text(text: str, max_chars: int = 220) -> list[str]:
    """Create small independently playable chunks without cutting words."""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?؟؛])\s+", text) if part.strip()]
    chunks: list[str] = []
    for sentence in sentences or [text]:
        while len(sentence) > max_chars:
            split_at = sentence.rfind(" ", 0, max_chars + 1)
            split_at = split_at if split_at > 0 else max_chars
            chunks.append(sentence[:split_at].strip())
            sentence = sentence[split_at:].strip()
        if sentence:
            chunks.append(sentence)
    return chunks[:8]


async def _synthesize_chunk(
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
        for attempt in range(MAX_TTS_RETRIES + 1):
            try:
                response = await client.audio.speech.create(
                    model=settings.VOICE_MODEL,
                    voice=settings.VOICE_NAME,
                    input=chunk,
                    speed=settings.VOICE_SPEED,
                    response_format="mp3",
                    instructions=settings.VOICE_INSTRUCTIONS or None,
                )
                audio = base64.b64encode(response.content).decode("ascii")
                await publish(
                    stay_id,
                    "tts_audio",
                    request_id,
                    audio=audio,
                    text=chunk,
                    seq=seq,
                    total=total,
                    nonce=nonce,
                    content_type="audio/mpeg",
                )
                return
            except Exception as exc:
                logger.warning(
                    "TTS attempt %s/%s failed for request %s chunk %s: %s",
                    attempt + 1,
                    MAX_TTS_RETRIES + 1,
                    request_id,
                    seq,
                    type(exc).__name__,
                )
                if attempt < MAX_TTS_RETRIES:
                    await asyncio.sleep(0.5 * (attempt + 1))
        await publish(
            stay_id,
            "tts_chunk_fallback",
            request_id,
            text=chunk,
            seq=seq,
            total=total,
            nonce=nonce,
        )


async def generate_and_publish_tts(*, text: str, stay_id: str, request_id: str) -> None:
    clean = clean_spoken_text(text)
    if not clean or settings.VOICE_SOURCE == "off":
        return

    nonce = request_id
    if settings.VOICE_SOURCE != "backend" or not settings.OPENAI_API_KEY:
        await publish(stay_id, "tts_fallback", request_id, text=clean, nonce=nonce)
        return

    chunks = split_spoken_text(clean)
    await publish(
        stay_id,
        "tts_status",
        request_id,
        status="generating",
        nonce=nonce,
        total=len(chunks),
    )
    semaphore = asyncio.Semaphore(3)
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY) as client:
        await asyncio.gather(*(
            _synthesize_chunk(
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
        ))
    await publish(stay_id, "tts_end", request_id, nonce=nonce, total=len(chunks))
