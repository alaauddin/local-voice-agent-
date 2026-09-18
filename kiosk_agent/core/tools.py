import json
import logging
from collections.abc import Callable
from typing import Literal

from django.db import close_old_connections, transaction
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kiosk_agent.models import ChaletConfig, KioskAuditLog, StaffRequest

logger = logging.getLogger(__name__)


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


def _property_information(args: PropertyInfoInput, stay_id: str, request_id: str) -> dict:
    close_old_connections()
    try:
        config = ChaletConfig.load()
        if str(config.current_stay_id) != str(stay_id):
            return {"found": False, "reason": "stay_expired", "facts": {}}
        topic = args.topic.casefold()
        matches = {
            key: value
            for key, value in config.property_facts.items()
            if topic in str(key).casefold() or topic in str(value).casefold()
        }
        return {"found": bool(matches), "topic": args.topic, "facts": matches}
    finally:
        close_old_connections()


def _staff_request_local(args: StaffRequestInput, stay_id: str, request_id: str) -> dict:
    close_old_connections()
    try:
        with transaction.atomic():
            config = ChaletConfig.objects.select_for_update().get(pk=ChaletConfig.SINGLETON_PK)
            if str(config.current_stay_id) != str(stay_id):
                return {"accepted": False, "reason": "stay_expired"}
            enabled = not config.enabled_services or args.service in config.enabled_services
            if not enabled:
                return {"accepted": False, "reason": "service_not_enabled"}
            staff_request = StaffRequest.objects.create(
                stay_id=stay_id,
                request_id=request_id,
                service=args.service,
                details=args.details,
                urgency=args.urgency,
                delivery_status=StaffRequest.DeliveryStatus.QUEUED,
            )
            staff_request.local_reference = f"SR-{staff_request.pk:06d}"
            staff_request.save(update_fields=("local_reference", "updated_at"))
            KioskAuditLog.objects.create(
                stay_id=stay_id,
                request_id=request_id,
                event=KioskAuditLog.Event.TOOL_CALLED,
                details={
                    "tool": "request_property_staff",
                    "chalet_number": config.chalet_number,
                    "reference": staff_request.local_reference,
                    **args.model_dump(),
                },
            )
            from kiosk_agent.tasks import forward_staff_request_task

            def enqueue_forwarding():
                try:
                    forward_staff_request_task.delay(staff_request.pk)
                except Exception:
                    logger.exception(
                        "Unable to queue SaaS delivery for staff request %s",
                        staff_request.local_reference,
                    )
                    StaffRequest.objects.filter(pk=staff_request.pk).update(
                        delivery_status=StaffRequest.DeliveryStatus.FAILED,
                        last_error="delivery_queue_unavailable",
                    )

            transaction.on_commit(enqueue_forwarding)
        return {
            "accepted": True,
            "reference": staff_request.local_reference,
            "urgency": args.urgency,
            "delivery_status": staff_request.delivery_status,
        }
    finally:
        close_old_connections()


def _emergency_contact(args: EmergencyContactInput, stay_id: str, request_id: str) -> dict:
    close_old_connections()
    try:
        config = ChaletConfig.load()
        if str(config.current_stay_id) != str(stay_id):
            return {"configured": False, "reason": "stay_expired", "contact": ""}
        return {"configured": bool(config.emergency_contact), "contact": config.emergency_contact}
    finally:
        close_old_connections()


TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "get_property_information": _property_information,
    "request_property_staff": _staff_request_local,
    "get_emergency_contact": _emergency_contact,
}


def execute_tool(name: str, raw_arguments: str, *, stay_id: str, request_id: str) -> str:
    model = TOOL_MODELS.get(name)
    handler = TOOL_HANDLERS.get(name)
    if not model or not handler:
        return json.dumps({"ok": False, "error": "unknown_tool"})
    try:
        args = model.model_validate_json(raw_arguments or "{}")
        result = handler(args, stay_id, request_id)
        return json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str)
    except ValidationError as exc:
        return json.dumps({"ok": False, "error": "validation_error", "details": exc.errors(include_url=False)})
    except Exception:
        return json.dumps({"ok": False, "error": "tool_execution_failed"})
