import json
import logging
from collections.abc import Callable
from typing import Literal

from django.core import signing
from django.db import close_old_connections, transaction
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from kiosk_agent.ac_control import (
    ACControlError,
    AC_STATE_FIELDS,
    protocol_capabilities,
    serialize_ac_state,
    set_ac_state,
)
from kiosk_agent.models import (
    ACState,
    ChaletConfig,
    KioskAuditLog,
    RemoteControl,
    StaffRequest,
)
from kiosk_agent.remote_control import (
    RemoteCommandError,
    get_pressable_remote_button,
    press_remote_button,
)

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


class ListRemoteControlsInput(StrictToolInput):
    pass


class PressRemoteButtonInput(StrictToolInput):
    button_id: int = Field(gt=0)
    confirmation_token: str = Field(max_length=1000)


class SetAirConditionerInput(StrictToolInput):
    device_id: int = Field(gt=0)
    power: bool | None
    mode: Literal["auto", "cool", "heat", "dry", "fan"] | None
    temperature: int | None = Field(ge=16, le=32)
    fan: Literal["auto", "low", "medium", "high"] | None
    swing_vertical: bool | None
    swing_horizontal: bool | None
    turbo: bool | None
    sleep: bool | None
    eco: bool | None
    quiet: bool | None
    light: bool | None
    x_fan: bool | None

    @model_validator(mode="after")
    def require_a_change(self):
        if all(getattr(self, field) is None for field in AC_STATE_FIELDS):
            raise ValueError("At least one AC state field must be provided.")
        return self


TOOL_MODELS: dict[str, type[StrictToolInput]] = {
    "get_property_information": PropertyInfoInput,
    "request_property_staff": StaffRequestInput,
    "get_emergency_contact": EmergencyContactInput,
    "list_remote_controls": ListRemoteControlsInput,
    "press_remote_button": PressRemoteButtonInput,
    "set_air_conditioner": SetAirConditionerInput,
}


def openai_tool_schemas() -> list[dict]:
    descriptions = {
        "get_property_information": "Read verified local chalet information for a guest question.",
        "request_property_staff": "Create a request that requires action by chalet staff.",
        "get_emergency_contact": "Read the configured property emergency contact when relevant.",
        "list_remote_controls": (
            "List the active devices and actions explicitly enabled for guest voice control, "
            "including current AC state and supported controls. Call this before controlling a device."
        ),
        "press_remote_button": (
            "Press one listed non-AC remote button using its button_id. Pass an empty "
            "confirmation_token initially. If confirmation is required, ask the guest and use the "
            "returned token only in a later turn after an explicit yes."
        ),
        "set_air_conditioner": (
            "Atomically change one listed voice-enabled air conditioner. Supply null for every "
            "field the guest did not ask to change."
        ),
    }
    schemas = []
    for name, model in TOOL_MODELS.items():
        parameters = model.model_json_schema()
        # Pydantic omits ``required`` for a valid zero-argument object. OpenAI's
        # strict schema contract and our schema consumers expect the explicit
        # empty array.
        parameters.setdefault("required", [])
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


def _current_stay_matches(stay_id: str) -> bool:
    return str(ChaletConfig.load().current_stay_id) == str(stay_id)


def _visible_ac_capabilities(device: RemoteControl) -> dict:
    capabilities = protocol_capabilities(device.protocol)
    for field, visible in (device.ac_control_visibility or {}).items():
        if field in capabilities and visible is False:
            capabilities[field] = False
    return capabilities


def _list_remote_controls(
    args: ListRemoteControlsInput,
    stay_id: str,
    request_id: str,
) -> dict:
    del args, request_id
    close_old_connections()
    try:
        if not _current_stay_matches(stay_id):
            return {"available": False, "reason": "stay_expired", "devices": []}

        devices = []
        remotes = (
            RemoteControl.objects.filter(is_active=True, voice_enabled=True)
            .prefetch_related("buttons")
            .order_by("sort_order", "name")
        )
        for remote in remotes:
            item = {
                "device_id": remote.pk,
                "name": remote.name,
                "location": remote.location,
                "device_type": remote.device_type,
            }
            if remote.device_type == RemoteControl.DeviceType.AC:
                state, _ = ACState.objects.get_or_create(device=remote)
                item["state"] = serialize_ac_state(state)
                item["capabilities"] = _visible_ac_capabilities(remote)
            else:
                item["buttons"] = [
                    {
                        "button_id": button.pk,
                        "key": button.key,
                        "label": button.label,
                        "requires_confirmation": button.requires_confirmation,
                    }
                    for button in remote.buttons.all()
                    if button.is_active and button.is_configured
                ]
                if not item["buttons"]:
                    continue
            devices.append(item)
        return {"available": bool(devices), "devices": devices}
    finally:
        close_old_connections()


REMOTE_CONFIRMATION_SALT = "kiosk-agent.remote-confirmation.v1"
REMOTE_CONFIRMATION_MAX_AGE_SECONDS = 120


def _make_confirmation_token(*, button_id: int, stay_id: str, request_id: str) -> str:
    return signing.dumps(
        {"button_id": button_id, "stay_id": str(stay_id), "request_id": str(request_id)},
        salt=REMOTE_CONFIRMATION_SALT,
        compress=True,
    )


def _valid_confirmation_token(
    token: str,
    *,
    button_id: int,
    stay_id: str,
    request_id: str,
) -> bool:
    try:
        payload = signing.loads(
            token,
            salt=REMOTE_CONFIRMATION_SALT,
            max_age=REMOTE_CONFIRMATION_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        return False
    return (
        payload.get("button_id") == button_id
        and payload.get("stay_id") == str(stay_id)
        and payload.get("request_id") != str(request_id)
    )


def _press_remote_button_tool(
    args: PressRemoteButtonInput,
    stay_id: str,
    request_id: str,
) -> dict:
    close_old_connections()
    try:
        if not _current_stay_matches(stay_id):
            return {"pressed": False, "reason": "stay_expired"}
        try:
            button = get_pressable_remote_button(
                args.button_id,
                require_voice_enabled=True,
            )
            if button.remote.device_type == RemoteControl.DeviceType.AC:
                return {"pressed": False, "reason": "wrong_device_type"}
            if button.requires_confirmation and not _valid_confirmation_token(
                args.confirmation_token,
                button_id=button.pk,
                stay_id=stay_id,
                request_id=request_id,
            ):
                return {
                    "pressed": False,
                    "confirmation_required": True,
                    "confirmation_token": _make_confirmation_token(
                        button_id=button.pk,
                        stay_id=stay_id,
                        request_id=request_id,
                    ),
                    "device": button.remote.name,
                    "location": button.remote.location,
                    "action": button.label,
                }
            result = press_remote_button(
                button.pk,
                source="voice",
                stay_id=stay_id,
                request_id=request_id,
                require_voice_enabled=True,
            )
            return {
                "pressed": True,
                "device": button.remote.name,
                "location": button.remote.location,
                "action": result["label"],
            }
        except RemoteCommandError as exc:
            return {"pressed": False, "reason": exc.code}
    finally:
        close_old_connections()


def _audit_ac_control(
    *,
    stay_id: str,
    request_id: str,
    device_id: int,
    success: bool,
    changed_fields: list[str],
    reason: str = "",
) -> None:
    KioskAuditLog.objects.create(
        stay_id=stay_id,
        request_id=request_id,
        event=(
            KioskAuditLog.Event.REMOTE_PRESSED
            if success
            else KioskAuditLog.Event.REMOTE_FAILED
        ),
        details={
            "remote_id": device_id,
            "source": "voice",
            "execution": "server",
            "command_type": "ac_state",
            "changed_fields": changed_fields,
            "status": "success" if success else reason,
        },
    )


def _set_air_conditioner(
    args: SetAirConditionerInput,
    stay_id: str,
    request_id: str,
) -> dict:
    close_old_connections()
    try:
        if not _current_stay_matches(stay_id):
            return {"applied": False, "reason": "stay_expired"}
        try:
            device = RemoteControl.objects.get(
                pk=args.device_id,
                device_type=RemoteControl.DeviceType.AC,
                is_active=True,
                voice_enabled=True,
            )
        except RemoteControl.DoesNotExist:
            return {"applied": False, "reason": "not_found_or_voice_disabled"}

        changes = {
            field: getattr(args, field)
            for field in AC_STATE_FIELDS
            if getattr(args, field) is not None
        }
        capabilities = _visible_ac_capabilities(device)
        blocked = [field for field in changes if capabilities.get(field) is not True]
        if blocked:
            return {
                "applied": False,
                "reason": "unsupported_or_hidden_control",
                "fields": blocked,
            }
        try:
            state = set_ac_state(device.pk, changes, request_id=request_id)
        except ACControlError as exc:
            _audit_ac_control(
                stay_id=stay_id,
                request_id=request_id,
                device_id=device.pk,
                success=False,
                changed_fields=sorted(changes),
                reason=exc.code,
            )
            return {"applied": False, "reason": exc.code}

        _audit_ac_control(
            stay_id=stay_id,
            request_id=request_id,
            device_id=device.pk,
            success=True,
            changed_fields=sorted(changes),
        )
        return {
            "applied": True,
            "device": device.name,
            "location": device.location,
            "state": serialize_ac_state(state),
            "state_version": state.state_version,
        }
    finally:
        close_old_connections()


TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "get_property_information": _property_information,
    "request_property_staff": _staff_request_local,
    "get_emergency_contact": _emergency_contact,
    "list_remote_controls": _list_remote_controls,
    "press_remote_button": _press_remote_button_tool,
    "set_air_conditioner": _set_air_conditioner,
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
