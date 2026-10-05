"""Server-side client for the dedicated LG TV IR controller."""

import httpx


COMMAND_ENDPOINTS = {
    "POWER": "/api/ir/power",
    "VOL_UP": "/api/ir/volume/up",
    "VOL_DOWN": "/api/ir/volume/down",
    "MUTE": "/api/ir/mute",
    "CH_UP": "/api/ir/channel/up",
    "CH_DOWN": "/api/ir/channel/down",
    "INPUT": "/api/ir/input",
    "HOME": "/api/ir/home",
    "SETTINGS": "/api/ir/settings",
    "UP": "/api/ir/navigation/up",
    "DOWN": "/api/ir/navigation/down",
    "LEFT": "/api/ir/navigation/left",
    "RIGHT": "/api/ir/navigation/right",
    "OK": "/api/ir/navigation/ok",
    "BACK": "/api/ir/back",
    "EXIT": "/api/ir/exit",
    **{str(number): f"/api/ir/number/{number}" for number in range(10)},
}


class TVRemoteError(Exception):
    def __init__(self, code, message="TV remote is offline"):
        self.code = code
        self.message = message
        super().__init__(message)


def _request(method, base_url, path, timeout=3):
    if not base_url:
        raise TVRemoteError("not_configured", "TV remote is not configured")
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(1.5, timeout))) as client:
            response = client.request(method, f"{base_url.rstrip('/')}{path}")
    except httpx.TimeoutException as exc:
        raise TVRemoteError("timeout") from exc
    except httpx.HTTPError as exc:
        raise TVRemoteError("offline") from exc
    if response.status_code != 200:
        raise TVRemoteError("controller_error", "TV remote did not accept the command")
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise TVRemoteError("invalid_response", "TV remote returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise TVRemoteError("invalid_response", "TV remote returned an invalid response")
    return payload


def send_command(base_url, command):
    path = COMMAND_ENDPOINTS.get(command)
    if path is None:
        raise TVRemoteError("invalid_command", "Unsupported TV remote command")
    payload = _request("POST", base_url, path)
    if payload.get("success") is not True:
        raise TVRemoteError("controller_error", "TV remote did not accept the command")
    return payload


def get_status(base_url):
    payload = _request("GET", base_url, "/api/status")
    return {"online": True, "controller": payload}
