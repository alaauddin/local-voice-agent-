from kiosk_agent.core.agent_engine import publish


async def voice_status(stay_id: str, request_id: str, *, nonce: str, total: int) -> None:
    await publish(
        stay_id,
        "voice_status",
        request_id,
        nonce=nonce,
        total=total,
        status="generating",
    )


async def voice_chunk(
    stay_id: str,
    request_id: str,
    *,
    nonce: str,
    seq: int,
    total: int,
    text: str,
    audio: str | None = None,
) -> None:
    payload = {"nonce": nonce, "seq": seq, "total": total, "text": text}
    if audio is None:
        payload["fallback_text"] = text
    else:
        payload.update({"audio": audio, "content_type": "audio/mpeg"})
    await publish(stay_id, "voice_chunk", request_id, **payload)


async def voice_fallback(
    stay_id: str, request_id: str, *, nonce: str, text: str, reason: str
) -> None:
    await publish(
        stay_id,
        "voice_fallback",
        request_id,
        nonce=nonce,
        text=text,
        reason=reason,
    )


async def voice_completed(
    stay_id: str, request_id: str, *, nonce: str, total: int
) -> None:
    await publish(
        stay_id,
        "voice_completed",
        request_id,
        nonce=nonce,
        total=total,
    )


async def voice_skipped(
    stay_id: str, request_id: str, *, nonce: str, reason: str
) -> None:
    await publish(
        stay_id,
        "voice_skipped",
        request_id,
        nonce=nonce,
        reason=reason,
    )
