"""Shared LAN remote command execution (admin, kiosk, future voice)."""

from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit

import httpx
import redis
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from kiosk_agent.models import ChaletConfig, KioskAuditLog, RemoteButton

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https"}
MAX_URL_LENGTH = 500
COOLDOWN_KEY = "wazen:remote:cooldown:{button_id}"


class RemoteCommandError(Exception):
    def __init__(self, code: str, message: str = "", *, http_status: int | None = None):
        self.code = code
        self.message = message or code
        self.http_status = http_status
        super().__init__(self.message)


def validate_command_url(url: str) -> str:
    """Accept any absolute http(s) URL. Host/path allowlists are not enforced."""
    raw = (url or "").strip()
    if not raw:
        raise ValidationError("Command URL is required.")
    if len(raw) > MAX_URL_LENGTH:
        raise ValidationError(f"Command URL exceeds {MAX_URL_LENGTH} characters.")
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise ValidationError("Command URL must start with http:// or https://.")
    if not parsed.netloc:
        raise ValidationError("Command URL must include a host.")
    return raw


def _cooldown_seconds() -> float:
    return float(getattr(settings, "REMOTE_BUTTON_COOLDOWN_SECONDS", 1.5) or 1.5)


def _check_cooldown(button_id: int) -> None:
    seconds = _cooldown_seconds()
    if seconds <= 0:
        return
    try:
        client = redis.Redis.from_url(settings.REDIS_URL)
        key = COOLDOWN_KEY.format(button_id=button_id)
        if not client.set(key, "1", nx=True, ex=max(1, int(seconds))):
            raise RemoteCommandError("cooldown", "Please wait before pressing again.")
    except RemoteCommandError:
        raise
    except Exception as exc:
        logger.debug("Remote cooldown redis unavailable: %s", exc)


def _parse_controller_payload(data) -> tuple[bool, str]:
    """Interpret controller JSON. Empty/unknown payloads are treated as OK when HTTP was 2xx."""
    if not isinstance(data, dict) or not data:
        return True, "success"
    status = str(data.get("status") or "").lower()
    http_code = data.get("httpCode")
    if status in {"success", "ok", "true", "1"}:
        return True, "success"
    if status in {"error", "fail", "failed", "false"}:
        return False, status
    if http_code is not None:
        try:
            if 200 <= int(http_code) < 300:
                return True, "success"
            return False, f"httpCode_{http_code}"
        except (TypeError, ValueError):
            pass
    # Unknown shape with no explicit failure → trust the HTTP status from the caller.
    return True, status or "success"


def _audit(
    *,
    stay_id,
    request_id,
    event: str,
    details: dict,
) -> None:
    close_old_connections()
    try:
        KioskAuditLog.objects.create(
            stay_id=stay_id,
            request_id=request_id,
            event=event,
            details=details,
        )
    except Exception as exc:
        logger.warning("Failed to write remote audit log: %s", exc)


def press_remote_button(
    button_id: int,
    *,
    source: str,
    stay_id=None,
    request_id=None,
    require_guest_visible: bool = False,
) -> dict:
    """Execute a configured remote button via server-side GET. Never accepts a URL from the client."""
    close_old_connections()
    try:
        button = (
            RemoteButton.objects.select_related("remote")
            .filter(pk=button_id, is_active=True, remote__is_active=True)
            .get()
        )
    except RemoteButton.DoesNotExist as exc:
        raise RemoteCommandError("not_found", "Button not found.") from exc

    if require_guest_visible and not button.remote.guest_visible:
        raise RemoteCommandError("forbidden", "Remote is not available on the kiosk.")

    if not button.is_configured:
        raise RemoteCommandError("unconfigured", "Button has no command URL.")

    try:
        url = validate_command_url(button.command_url)
    except ValidationError as exc:
        raise RemoteCommandError("invalid_url", "; ".join(exc.messages)) from exc

    _check_cooldown(button.pk)

    if stay_id is None:
        stay_id = ChaletConfig.load().current_stay_id

    timeout = float(getattr(settings, "REMOTE_COMMAND_TIMEOUT_SECONDS", 3.0) or 3.0)
    started = time.monotonic()
    http_status = None
    controller_status = ""
    error_code = ""

    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(1.5, timeout)),
            follow_redirects=False,
        ) as client:
            response = client.get(url)
        http_status = response.status_code
        duration_ms = int((time.monotonic() - started) * 1000)
        if not (200 <= response.status_code < 300):
            error_code = "http_error"
            _audit(
                stay_id=stay_id,
                request_id=request_id,
                event=KioskAuditLog.Event.REMOTE_FAILED,
                details={
                    "remote_id": button.remote_id,
                    "button_id": button.pk,
                    "button_key": button.key,
                    "source": source,
                    "status": error_code,
                    "http_status": http_status,
                    "duration_ms": duration_ms,
                },
            )
            raise RemoteCommandError(
                error_code,
                "Controller returned an error.",
                http_status=http_status,
            )
        try:
            payload = response.json()
        except Exception:
            payload = {}
        ok, controller_status = _parse_controller_payload(payload)
        if not ok:
            error_code = "controller_error"
            _audit(
                stay_id=stay_id,
                request_id=request_id,
                event=KioskAuditLog.Event.REMOTE_FAILED,
                details={
                    "remote_id": button.remote_id,
                    "button_id": button.pk,
                    "button_key": button.key,
                    "source": source,
                    "status": error_code,
                    "controller_status": controller_status,
                    "http_status": http_status,
                    "duration_ms": duration_ms,
                },
            )
            raise RemoteCommandError(
                error_code,
                "Controller reported failure.",
                http_status=http_status,
            )
        _audit(
            stay_id=stay_id,
            request_id=request_id,
            event=KioskAuditLog.Event.REMOTE_PRESSED,
            details={
                "remote_id": button.remote_id,
                "button_id": button.pk,
                "button_key": button.key,
                "source": source,
                "status": "success",
                "http_status": http_status,
                "duration_ms": duration_ms,
                "target": str(payload.get("target") or "")[:80],
            },
        )
        return {
            "ok": True,
            "status": "success",
            "remote_id": button.remote_id,
            "button_id": button.pk,
            "label": button.label,
            "http_status": http_status,
            "duration_ms": duration_ms,
            "target": str(payload.get("target") or "")[:80],
        }
    except RemoteCommandError:
        raise
    except httpx.TimeoutException as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        _audit(
            stay_id=stay_id,
            request_id=request_id,
            event=KioskAuditLog.Event.REMOTE_FAILED,
            details={
                "remote_id": button.remote_id,
                "button_id": button.pk,
                "button_key": button.key,
                "source": source,
                "status": "timeout",
                "http_status": None,
                "duration_ms": duration_ms,
            },
        )
        raise RemoteCommandError("timeout", "Controller timed out.") from exc
    except httpx.HTTPError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        _audit(
            stay_id=stay_id,
            request_id=request_id,
            event=KioskAuditLog.Event.REMOTE_FAILED,
            details={
                "remote_id": button.remote_id,
                "button_id": button.pk,
                "button_key": button.key,
                "source": source,
                "status": "network_error",
                "http_status": None,
                "duration_ms": duration_ms,
            },
        )
        raise RemoteCommandError("network_error", "Could not reach controller.") from exc
