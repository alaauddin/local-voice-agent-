"""State-based AC communication between Django and an ESP32 controller."""

from __future__ import annotations

import uuid

import httpx
from django.conf import settings
from django.db import transaction

from .models import ACState, RemoteControl

AC_STATE_FIELDS = (
    "power",
    "mode",
    "temperature",
    "fan",
    "swing_vertical",
    "swing_horizontal",
    "turbo",
    "sleep",
    "eco",
    "quiet",
    "light",
    "x_fan",
)
BOOLEAN_FIELDS = {
    "power",
    "swing_vertical",
    "swing_horizontal",
    "turbo",
    "sleep",
    "eco",
    "quiet",
    "light",
    "x_fan",
}


class ACControlError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int | None = None):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def serialize_ac_state(state: ACState) -> dict:
    return {field: getattr(state, field) for field in AC_STATE_FIELDS}


def _validate_state_values(values: dict, *, require_all: bool = False) -> dict:
    unknown = set(values) - set(AC_STATE_FIELDS)
    if unknown:
        raise ACControlError("invalid_state", f"Unknown AC fields: {', '.join(sorted(unknown))}.")
    if require_all:
        missing = set(AC_STATE_FIELDS) - set(values)
        if missing:
            raise ACControlError("invalid_response", "ESP32 returned an incomplete AC state.")

    normalized = {}
    for field, value in values.items():
        if field in BOOLEAN_FIELDS:
            if not isinstance(value, bool):
                raise ACControlError("invalid_state", f"{field} must be a boolean.")
        elif field == "temperature":
            if isinstance(value, bool) or not isinstance(value, int) or not 16 <= value <= 32:
                raise ACControlError("invalid_state", "temperature must be an integer from 16 to 32.")
        elif field == "mode":
            if value not in ACState.Mode.values:
                raise ACControlError("invalid_state", "Invalid AC mode.")
        elif field == "fan":
            if value not in ACState.Fan.values:
                raise ACControlError("invalid_state", "Invalid AC fan setting.")
        normalized[field] = value
    return normalized


def _controller_url(device: RemoteControl) -> str:
    if not device.device_ip:
        raise ACControlError("unconfigured", "The AC controller has no discovered IP address.")
    return f"http://{device.device_ip}/api/ac/state"


def _parse_esp32_response(response: httpx.Response, device: RemoteControl) -> dict:
    if not 200 <= response.status_code < 300:
        message = "ESP32 rejected the AC command."
        try:
            message = str(response.json().get("message") or message)
        except (TypeError, ValueError):
            pass
        raise ACControlError("controller_error", message, http_status=response.status_code)
    try:
        payload = response.json()
    except ValueError as exc:
        raise ACControlError("invalid_response", "ESP32 returned invalid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ACControlError("controller_error", "ESP32 did not confirm transmission.")
    for field, expected in (
        ("brand", device.brand),
        ("protocol", device.protocol),
        ("model", device.protocol_model),
    ):
        if str(payload.get(field) or "").casefold() != expected.casefold():
            raise ACControlError("invalid_response", f"ESP32 response {field} did not match.")
    version = payload.get("state_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ACControlError("invalid_response", "ESP32 returned an invalid state version.")
    state = payload.get("state")
    if not isinstance(state, dict):
        raise ACControlError("invalid_response", "ESP32 returned no AC state.")
    payload["state"] = _validate_state_values(state, require_all=True)
    return payload


@transaction.atomic
def set_ac_state(device_id: int, changes: dict, *, request_id: str | None = None) -> ACState:
    """Transmit first, then persist exactly the state confirmed by the ESP32."""
    try:
        device = RemoteControl.objects.select_for_update().get(pk=device_id)
    except RemoteControl.DoesNotExist as exc:
        raise ACControlError("not_found", "AC device not found.") from exc
    if device.device_type != RemoteControl.DeviceType.AC:
        raise ACControlError("wrong_type", "Device is not configured as an AC.")
    if not all((device.device_name, device.brand, device.protocol, device.protocol_model)):
        raise ACControlError("unconfigured", "Complete the AC controller, brand, protocol, and model settings.")

    changes = _validate_state_values(dict(changes))
    state, _ = ACState.objects.select_for_update().get_or_create(device=device)
    merged = serialize_ac_state(state)
    merged.update(changes)
    request_id = request_id or str(uuid.uuid4())
    payload = {
        "source": "django",
        "request_id": request_id,
        "brand": device.brand,
        "protocol": device.protocol,
        "model": device.protocol_model,
        "state_version": state.state_version + 1,
        **merged,
    }

    timeout = float(getattr(settings, "AC_COMMAND_TIMEOUT_SECONDS", 5.0) or 5.0)
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(1.5, timeout)),
            follow_redirects=False,
        ) as client:
            response = client.post(_controller_url(device), json=payload)
    except httpx.TimeoutException as exc:
        raise ACControlError("timeout", "AC controller timed out.") from exc
    except httpx.HTTPError as exc:
        raise ACControlError("network_error", "Could not reach the AC controller.") from exc

    confirmed = _parse_esp32_response(response, device)
    if confirmed["state_version"] < state.state_version:
        raise ACControlError("stale_response", "ESP32 returned an older AC state.")
    for field, value in confirmed["state"].items():
        setattr(state, field, value)
    state.state_version = confirmed["state_version"]
    updated_at = confirmed.get("updated_at", 0)
    state.esp32_updated_at = updated_at if isinstance(updated_at, int) and updated_at >= 0 else 0
    state.save()
    return state


@transaction.atomic
def accept_esp32_state_sync(payload: dict) -> tuple[ACState, bool]:
    """Accept an ESP32 notification without issuing any command back to it."""
    if payload.get("source") != "esp32":
        raise ACControlError("invalid_source", "source must be esp32.")
    esp32_id = payload.get("esp32_id")
    version = payload.get("state_version")
    if not isinstance(esp32_id, str) or not esp32_id.strip():
        raise ACControlError("invalid_state", "esp32_id must be a non-empty string.")
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ACControlError("invalid_state", "state_version must be a non-negative integer.")
    incoming = payload.get("state")
    if not isinstance(incoming, dict):
        raise ACControlError("invalid_state", "state must be an object.")
    incoming = _validate_state_values(incoming, require_all=True)

    try:
        device = RemoteControl.objects.select_for_update().get(
            device_type=RemoteControl.DeviceType.AC,
            device_name=esp32_id.strip(),
        )
    except RemoteControl.DoesNotExist as exc:
        raise ACControlError("not_found", "AC device not found.") from exc
    except RemoteControl.MultipleObjectsReturned as exc:
        raise ACControlError("ambiguous_device", "More than one AC uses this DEVICE_NAME.") from exc

    for field, expected in (
        ("brand", device.brand),
        ("protocol", device.protocol),
        ("model", device.protocol_model),
    ):
        if str(payload.get(field) or "").casefold() != expected.casefold():
            raise ACControlError("invalid_state", f"ESP32 {field} does not match Django.")

    state, _ = ACState.objects.select_for_update().get_or_create(device=device)
    if version < state.state_version:
        return state, False
    for field, value in incoming.items():
        setattr(state, field, value)
    state.state_version = version
    updated_at = payload.get("updated_at", 0)
    state.esp32_updated_at = updated_at if isinstance(updated_at, int) and updated_at >= 0 else 0
    state.save()
    return state, True
