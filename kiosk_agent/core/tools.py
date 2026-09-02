import json
from collections.abc import Awaitable, Callable
from typing import Literal

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kiosk_agent.models import ChaletConfig, KioskAuditLog


class StrictToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PropertyInfoInput(StrictToolInput):
    topic: str = Field(min_length=2, max_length=100)


class StaffRequestInput(StrictToolInput):
    service: Literal[
        "housekeeping",
        "maintenance",
        "concierge",
        "cafe",
        "food",
        "wifi",
        "grocery",
        "delivery",
        "supplies",
        "security",
        "lost_found",
        "extension",
        "other",
    ]
    details: str = Field(min_length=2, max_length=1000)
    urgency: Literal["normal", "high"]


class EmergencyContactInput(StrictToolInput):
    reason: str = Field(min_length=2, max_length=500)


TOOL_MODELS: dict[str, type[StrictToolInput]] = {
    "get_property_information": PropertyInfoInput,
    "request_property_staff": StaffRequestInput,
    "get_emergency_contact": EmergencyContactInput,
}


def openai_tool_schemas() -> list[dict]:
    descriptions = {
        "get_property_information": "Read verified local chalet information for a guest question.",
        "request_property_staff": "Create a request that requires action by chalet staff.",
        "get_emergency_contact": "Read the configured property emergency contact when relevant.",
    }
    schemas = []
    for name, model in TOOL_MODELS.items():
        parameters = model.model_json_schema()
        properties = set(parameters.get("properties", {}))
        required = set(parameters.get("required", []))
        if properties != required or parameters.get("additionalProperties") is not False:
            raise RuntimeError(
                f"Strict OpenAI tool schema {name!r} must require every property and forbid extras."
            )
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": descriptions[name],
                "parameters": parameters,
                "strict": True,
            },
        })
    return schemas


def realtime_tool_schemas() -> list[dict]:
    """Return the flattened function schema expected by Realtime sessions."""
    tools = []
    for schema in openai_tool_schemas():
        function = schema["function"]
        tools.append({
            "type": "function",
            "name": function["name"],
            "description": function["description"],
            "parameters": function["parameters"],
        })
    return tools


@sync_to_async(thread_sensitive=True)
def _property_information(args: PropertyInfoInput, stay_id: str, request_id: str) -> dict:
    close_old_connections()
    try:
        config = ChaletConfig.load()
        topic = args.topic.casefold()
        matches = {
            key: value
            for key, value in config.property_facts.items()
            if topic in str(key).casefold() or topic in str(value).casefold()
        }
        return {"found": bool(matches), "topic": args.topic, "facts": matches}
    finally:
        close_old_connections()


@sync_to_async(thread_sensitive=True)
def _staff_request(args: StaffRequestInput, stay_id: str, request_id: str) -> dict:
    close_old_connections()
    try:
        config = ChaletConfig.load()
        enabled = not config.enabled_services or args.service in config.enabled_services
        if not enabled:
            return {"accepted": False, "reason": "service_not_enabled"}
        log = KioskAuditLog.objects.create(
            stay_id=stay_id,
            request_id=request_id,
            event=KioskAuditLog.Event.TOOL_CALLED,
            details={"tool": "request_property_staff", "chalet_number": config.chalet_number, **args.model_dump()},
        )
        return {"accepted": True, "reference": f"SR-{log.pk:06d}", "urgency": args.urgency}
    finally:
        close_old_connections()


async def _staff_request_async(args: StaffRequestInput, stay_id: str, request_id: str) -> dict:
    from asgiref.sync import sync_to_async as _sta
    from django.db import close_old_connections as _coc
    from kiosk_agent.models import ChaletConfig as _CC, KioskAuditLog as _KAL
    from kiosk_agent.integrations.saas import forward_request_to_saas as _fwd

    @_sta(thread_sensitive=True)
    def _create():
        _coc()
        try:
            cfg = _CC.load()
            en = not cfg.enabled_services or args.service in cfg.enabled_services
            if not en:
                return None, {"accepted": False, "reason": "service_not_enabled"}, None
            lg = _KAL.objects.create(stay_id=stay_id, request_id=request_id, event=_KAL.Event.TOOL_CALLED, details={"tool": "request_property_staff", "chalet_number": cfg.chalet_number, **args.model_dump()})
            ref = f"SR-{lg.pk:06d}"
            return cfg, {"accepted": True, "reference": ref, "urgency": args.urgency}, ref
        finally:
            _coc()
    cfg, result, ref = await _create()
    if not result.get("accepted"):
        return result
    try:
        saas_res = await _fwd(config=cfg, service=args.service, details=args.details, urgency=args.urgency, stay_id=stay_id, request_id=request_id, local_reference=ref)
        result["saas_forwarded"] = bool(saas_res.get("forwarded"))
        if saas_res.get("forwarded"):
            result["saas_reference"] = saas_res.get("response", {}).get("id")
        else:
            result["saas_error"] = saas_res.get("reason") or saas_res.get("error") or str(saas_res.get("status_code") or "")
    except Exception as exc:
        result["saas_forwarded"] = False
        result["saas_error"] = str(exc)[:300]
    return result


@sync_to_async(thread_sensitive=True)
def _emergency_contact(args: EmergencyContactInput, stay_id: str, request_id: str) -> dict:
    close_old_connections()
    try:
        config = ChaletConfig.load()
        return {"configured": bool(config.emergency_contact), "contact": config.emergency_contact}
    finally:
        close_old_connections()


TOOL_HANDLERS: dict[str, Callable[..., Awaitable[dict]]] = {
    "get_property_information": _property_information,
    "request_property_staff": _staff_request_async,
    "get_emergency_contact": _emergency_contact,
}


async def execute_tool(name: str, raw_arguments: str, *, stay_id: str, request_id: str) -> str:
    model = TOOL_MODELS.get(name)
    handler = TOOL_HANDLERS.get(name)
    if not model or not handler:
        return json.dumps({"ok": False, "error": "unknown_tool"})
    try:
        args = model.model_validate_json(raw_arguments or "{}")
        result = await handler(args, stay_id, request_id)
        return json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str)
    except ValidationError as exc:
        return json.dumps({"ok": False, "error": "validation_error", "details": exc.errors(include_url=False)})
    except Exception:
        return json.dumps({"ok": False, "error": "tool_execution_failed"})
