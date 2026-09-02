import json
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import close_old_connections
from openai import AsyncOpenAI

from kiosk_agent.core.prompt_builder import build_system_prompt
from kiosk_agent.core.tools import execute_tool, openai_tool_schemas
from kiosk_agent.models import ChaletConfig, KioskMessage

MAX_ITERATIONS = 5
HISTORY_LIMIT = 40


def stay_group(stay_id: str) -> str:
    return f"kiosk_stay_{stay_id}"


async def publish(stay_id: str, event: str, request_id: str, **payload) -> None:
    layer = get_channel_layer()
    await layer.group_send(
        stay_group(stay_id),
        {"type": "agent.event", "payload": {"event": event, "request_id": request_id, **payload}},
    )


@sync_to_async(thread_sensitive=True)
def _load_context(stay_id: str):
    close_old_connections()
    try:
        config = ChaletConfig.load()
        if str(config.current_stay_id) != stay_id:
            raise RuntimeError("This stay has already been reset.")
        rows = list(
            KioskMessage.objects.filter(
                stay_id=stay_id,
                role__in=(KioskMessage.Role.USER, KioskMessage.Role.ASSISTANT),
            ).exclude(status=KioskMessage.Status.FAILED).order_by("-created_at", "-id")[:HISTORY_LIMIT]
        )
        rows.reverse()
        return config, [{"role": row.role, "content": row.content} for row in rows]
    finally:
        close_old_connections()


@sync_to_async(thread_sensitive=True)
def _save_message(**kwargs):
    close_old_connections()
    try:
        config = ChaletConfig.load()
        if str(config.current_stay_id) != str(kwargs["stay_id"]):
            return None
        return KioskMessage.objects.create(**kwargs)
    finally:
        close_old_connections()


@dataclass
class ToolCallBuffer:
    id: str = ""
    name: str = ""
    arguments: str = ""


async def run_agent(*, stay_id: str, request_id: str) -> str:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    config, history = await _load_context(stay_id)
    model = config.llm_model or settings.OPENAI_MODEL
    messages: list[dict] = [{"role": "system", "content": build_system_prompt(config)}, *history]
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    await publish(stay_id, "status", request_id, status="thinking")

    for iteration in range(1, MAX_ITERATIONS + 1):
        text_parts: list[str] = []
        tool_buffers: dict[int, ToolCallBuffer] = {}
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=openai_tool_schemas(),
            tool_choice="auto",
            temperature=0.3,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                text_parts.append(delta.content)
                await publish(stay_id, "token", request_id, token=delta.content)
            for call in delta.tool_calls or []:
                buffer = tool_buffers.setdefault(call.index, ToolCallBuffer())
                if call.id:
                    buffer.id += call.id
                if call.function:
                    if call.function.name:
                        buffer.name += call.function.name
                    if call.function.arguments:
                        buffer.arguments += call.function.arguments

        text = "".join(text_parts)
        if not tool_buffers:
            if not text.strip():
                raise RuntimeError("The model returned an empty response.")
            saved = await _save_message(
                stay_id=stay_id,
                request_id=request_id,
                role=KioskMessage.Role.ASSISTANT,
                content=text,
                status=KioskMessage.Status.COMPLETE,
                metadata={"model": model, "iterations": iteration},
            )
            if saved is None:
                await publish(stay_id, "cancelled", request_id, reason="stay_reset")
                return ""
            await publish(stay_id, "complete", request_id, message_id=saved.pk, content=text)
            return text

        assistant_calls = [
            {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}}
            for _, call in sorted(tool_buffers.items())
        ]
        messages.append({"role": "assistant", "content": text or None, "tool_calls": assistant_calls})

        for call in (tool_buffers[index] for index in sorted(tool_buffers)):
            await publish(stay_id, "tool_status", request_id, tool=call.name, status="running")
            result = await execute_tool(call.name, call.arguments, stay_id=stay_id, request_id=request_id)
            await _save_message(
                stay_id=stay_id,
                request_id=request_id,
                role=KioskMessage.Role.TOOL,
                content=result,
                status=KioskMessage.Status.COMPLETE,
                tool_name=call.name,
                tool_call_id=call.id,
            )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            parsed = json.loads(result)
            await publish(
                stay_id,
                "tool_status",
                request_id,
                tool=call.name,
                status="complete" if parsed.get("ok") else "failed",
            )

    raise RuntimeError(f"Agent exceeded the {MAX_ITERATIONS}-iteration safety limit.")
