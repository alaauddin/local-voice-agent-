"""Staff-only proxy for learning RAW IR signals from a discovered controller."""

from __future__ import annotations

import httpx
from django.conf import settings
from django.core.exceptions import ValidationError

from .models import RemoteControl
from .remote_control import validate_ir_command


class IRCaptureError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _controller_url(remote: RemoteControl, path: str) -> str:
    if not remote.device_ip:
        raise IRCaptureError(
            "device_unavailable",
            "Sync the remote device IP before capturing an IR signal.",
        )
    return f"http://{remote.device_ip}{path}"


def _request(remote: RemoteControl, method: str, path: str, *, json=None) -> dict:
    timeout = float(getattr(settings, "REMOTE_COMMAND_TIMEOUT_SECONDS", 3.0) or 3.0)
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(1.5, timeout)),
            follow_redirects=False,
        ) as client:
            response = client.request(method, _controller_url(remote, path), json=json)
    except httpx.TimeoutException as exc:
        raise IRCaptureError("timeout", "The IR controller timed out.") from exc
    except httpx.HTTPError as exc:
        raise IRCaptureError("network_error", "Could not reach the IR controller.") from exc

    if not 200 <= response.status_code < 300:
        raise IRCaptureError(
            "controller_error",
            f"The IR controller returned HTTP {response.status_code}.",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise IRCaptureError("invalid_response", "The IR controller returned invalid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise IRCaptureError("invalid_response", "The IR controller returned an invalid response.")
    return payload


def start_ir_capture(remote: RemoteControl, frequency: int) -> dict:
    if isinstance(frequency, bool) or not isinstance(frequency, int) or not 20 <= frequency <= 100:
        raise IRCaptureError("invalid_frequency", "Frequency must be between 20 and 100 kHz.")
    payload = _request(
        remote,
        "POST",
        "/api/ir/capture/start",
        json={"frequency": frequency},
    )
    return {
        "capturing": payload.get("capturing") is True,
        "frequency": frequency,
        "timeout_ms": int(payload.get("timeout_ms") or 15_000),
    }


def read_ir_capture(remote: RemoteControl) -> dict:
    payload = _request(remote, "GET", "/api/ir/capture")
    ready = payload.get("ready") is True
    result = {
        "capturing": payload.get("capturing") is True,
        "ready": ready,
        "revision": int(payload.get("revision") or 0),
    }
    if not ready:
        return result

    frequency = payload.get("frequency")
    raw = payload.get("raw")
    try:
        command = validate_ir_command(1, frequency, raw)
    except ValidationError as exc:
        raise IRCaptureError("invalid_response", "; ".join(exc.messages)) from exc
    result.update(
        {
            "frequency": command["frequency"],
            "raw": command["raw"],
            "protocol": str(payload.get("protocol") or "")[:40],
        }
    )
    return result
