import json
import logging
import secrets
import uuid
from datetime import timedelta

import redis
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import TemplateView
from rest_framework import parsers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .ac_control import (
    ACControlError,
    AC_PROTOCOL_CONFIG,
    AC_STATE_FIELDS,
    accept_esp32_state_sync,
    is_protocol_model_supported,
    normalize_protocol_model,
    protocol_capabilities,
    protocol_defaults,
    protocol_models,
    serialize_ac_state,
    set_ac_state,
)
from .core.agent_engine import stay_group
from .core.realtime import create_realtime_call
from .core.tools import TOOL_MODELS, execute_tool
from .device_discovery import DeviceDiscoveryError, discover_identity_devices
from .ir_capture import IRCaptureError, read_ir_capture, start_ir_capture
from .models import (
    ACState,
    ChaletConfig,
    KioskAuditLog,
    KioskMessage,
    RealtimeSession,
    RemoteButton,
    RemoteButtonIcon,
    RemoteButtonKey,
    RemoteControl,
)
from .permissions import (
    KIOSK_COOKIE_NAME,
    OptionalKioskKeyPermission,
    create_kiosk_cookie,
    valid_kiosk_cookie,
)
from .remote_control import RemoteCommandError, press_remote_button
from .serializers import (
    ChaletPublicSerializer,
    ChatRequestSerializer,
    KioskMessageSerializer,
    RealtimeMessageSerializer,
    RealtimeSessionIdentitySerializer,
    RealtimeToolSerializer,
    RemoteControlPublicSerializer,
)
from .services import AgentBusyError, enqueue_message
from .tasks import sync_remote_ips
from .tv_remote import TVRemoteError, get_status as get_tv_status, send_command as send_tv_command

logger = logging.getLogger(__name__)


def _serialize_config_button(button):
    return {
        "id": button.pk,
        "key": button.key,
        "label": button.label,
        "icon": button.icon,
        "row": button.row,
        "column": button.column,
        "sort_order": button.sort_order,
        "command_url": button.command_url,
        "ir_id": button.ir_id,
        "frequency": button.frequency,
        "raw": button.raw,
        "is_active": button.is_active,
        "requires_confirmation": button.requires_confirmation,
        "configured": button.is_configured,
    }


@staff_member_required
def button_config_view(request):
    remotes = list(
        RemoteControl.objects.order_by("sort_order", "name").values(
            "id", "name", "location", "device_type"
        )
    )
    return render(
        request,
        "kiosk_agent/button_config.html",
        {
            "remotes": remotes,
            "key_choices": [
                {"value": value, "label": label} for value, label in RemoteButtonKey.choices
            ],
            "icon_choices": [
                {"value": value, "label": label} for value, label in RemoteButtonIcon.choices
            ],
        },
    )


@staff_member_required
@require_POST
def remote_create_view(request):
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON payload."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "Provide remote details."}, status=400)

    name = payload.get("name")
    location = payload.get("location", "")
    device_type = payload.get("device_type", RemoteControl.DeviceType.RAW)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        return JsonResponse({"detail": "Enter a remote name up to 120 characters."}, status=400)
    if not isinstance(location, str) or len(location.strip()) > 120:
        return JsonResponse({"detail": "Location must be 120 characters or fewer."}, status=400)
    if device_type not in RemoteControl.DeviceType.values:
        return JsonResponse({"detail": "Choose a valid remote type."}, status=400)

    name = name.strip()
    base_slug = slugify(name)[:100].strip("-") or "remote"
    suffix = uuid.uuid4().hex[:8]
    remote = RemoteControl.objects.create(
        name=name,
        location=location.strip(),
        device_type=device_type,
        slug=f"{base_slug}-{suffix}",
        sort_order=(RemoteControl.objects.order_by("-sort_order")
                    .values_list("sort_order", flat=True).first() or 0) + 1,
    )
    return JsonResponse(
        {
            "remote": {
                "id": remote.pk,
                "name": remote.name,
                "location": remote.location,
                "device_type": remote.device_type,
            }
        },
        status=201,
    )


@staff_member_required
@require_GET
def button_config_data_view(request, remote_id):
    remote = get_object_or_404(RemoteControl, pk=remote_id)
    ac_config = None
    if remote.device_type == RemoteControl.DeviceType.AC:
        state, _ = ACState.objects.get_or_create(device=remote)
        normalized_model = normalize_protocol_model(remote.protocol, remote.protocol_model)
        ac_config = {
            "protocol": remote.protocol,
            "brand": remote.brand,
            "model": normalized_model,
            "state": serialize_ac_state(state),
            "state_version": state.state_version,
            "visibility": {
                field: (remote.ac_control_visibility or {}).get(field, True)
                for field in AC_STATE_FIELDS
            },
            "protocols": [
                {
                    "value": value,
                    "label": label,
                    "brand": protocol_defaults(value)[0],
                    "brand_label": RemoteControl.Brand(protocol_defaults(value)[0]).label,
                    "model": protocol_defaults(value)[1],
                    "model_label": RemoteControl.ProtocolModel(protocol_defaults(value)[1]).label,
                    "models": [
                        {
                            "value": model,
                            "label": RemoteControl.ProtocolModel(model).label,
                        }
                        for model in protocol_models(value)
                    ],
                    "capabilities": protocol_capabilities(value),
                }
                for value, label in RemoteControl.Protocol.choices
                if value in AC_PROTOCOL_CONFIG
            ],
        }
    return JsonResponse(
        {
            "remote": {
                "id": remote.pk,
                "name": remote.name,
                "location": remote.location,
                "device_type": remote.device_type,
                "device_name": remote.device_name,
                "device_ip": str(remote.device_ip or ""),
                "can_capture": bool(remote.device_ip),
                "is_active": remote.is_active,
                "guest_visible": remote.guest_visible,
                "voice_enabled": remote.voice_enabled,
            },
            "ac": ac_config,
            "buttons": [
                _serialize_config_button(button)
                for button in remote.buttons.order_by("sort_order", "row", "column", "id")
            ],
        }
    )


def _capture_error_response(exc):
    status_map = {
        "device_unavailable": 400,
        "invalid_frequency": 400,
        "timeout": 504,
        "network_error": 502,
        "controller_error": 502,
        "invalid_response": 502,
    }
    return JsonResponse(
        {"success": False, "code": exc.code, "detail": exc.message},
        status=status_map.get(exc.code, 400),
    )


@staff_member_required
@require_POST
def button_capture_start_view(request, remote_id):
    remote = get_object_or_404(RemoteControl, pk=remote_id)
    try:
        payload = json.loads(request.body or "{}")
        frequency = int(payload.get("frequency", 38))
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"detail": "Frequency must be an integer."}, status=400)
    try:
        result = start_ir_capture(remote, frequency)
    except IRCaptureError as exc:
        return _capture_error_response(exc)
    return JsonResponse({"success": True, **result})


@staff_member_required
@require_GET
def button_capture_status_view(request, remote_id):
    remote = get_object_or_404(RemoteControl, pk=remote_id)
    try:
        result = read_ir_capture(remote)
    except IRCaptureError as exc:
        return _capture_error_response(exc)
    return JsonResponse({"success": True, **result})


def _button_validation_error(exc):
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return {"buttons": exc.messages}


@staff_member_required
@require_POST
def button_config_save_view(request, remote_id):
    try:
        payload = json.loads(request.body)
    except (TypeError, ValueError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON payload."}, status=400)
    rows = payload.get("buttons") if isinstance(payload, dict) else None
    remote_settings = payload.get("remote") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > 100:
        return JsonResponse({"detail": "Provide no more than 100 buttons."}, status=400)
    remote_fields = ("is_active", "guest_visible", "voice_enabled")
    if remote_settings is not None and (
        not isinstance(remote_settings, dict)
        or any(not isinstance(remote_settings.get(field), bool) for field in remote_fields)
        or not isinstance(remote_settings.get("device_name"), str)
        or len(remote_settings.get("device_name", "")) > 120
    ):
        return JsonResponse({"detail": "Invalid remote settings."}, status=400)

    with transaction.atomic():
        remote = get_object_or_404(RemoteControl.objects.select_for_update(), pk=remote_id)
        if not rows and remote.device_type not in (RemoteControl.DeviceType.AC, RemoteControl.DeviceType.LG_TV):
            return JsonResponse({"detail": "Provide at least one button."}, status=400)
        if remote_settings is None:
            remote_settings = {field: getattr(remote, field) for field in remote_fields}
            remote_settings["device_name"] = remote.device_name
        if remote.device_type == RemoteControl.DeviceType.AC:
            protocol = remote_settings.get("protocol")
            if protocol not in AC_PROTOCOL_CONFIG:
                return JsonResponse({"detail": "Choose a supported AC protocol."}, status=400)
            protocol_model = str(remote_settings.get("protocol_model", ""))
            protocol_model = normalize_protocol_model(protocol, protocol_model)
            if not is_protocol_model_supported(protocol, protocol_model):
                return JsonResponse(
                    {"detail": "Choose a model supported by the selected AC protocol."},
                    status=400,
                )
            visibility = remote_settings.get("ac_control_visibility", {})
            if (
                not isinstance(visibility, dict)
                or set(visibility) - set(AC_STATE_FIELDS)
                or any(not isinstance(value, bool) for value in visibility.values())
            ):
                return JsonResponse({"detail": "Invalid AC control visibility settings."}, status=400)
        else:
            protocol = ""
            protocol_model = ""
            visibility = {}
        existing = list(remote.buttons.select_for_update())
        existing_by_id = {button.pk: button for button in existing}
        submitted_ids = []
        buttons = []
        positions = set()
        keys = set()

        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                return JsonResponse({"detail": f"Button {index + 1} must be an object."}, status=400)
            button_id = row.get("id")
            if button_id in (None, ""):
                button = RemoteButton(remote=remote)
            else:
                try:
                    button_id = int(button_id)
                except (TypeError, ValueError):
                    return JsonResponse({"detail": f"Button {index + 1} has an invalid id."}, status=400)
                button = existing_by_id.get(button_id)
                if button is None or button_id in submitted_ids:
                    return JsonResponse({"detail": "The button list is stale. Reload and try again."}, status=409)
                submitted_ids.append(button_id)

            try:
                button.key = str(row.get("key", "")).strip()
                button.label = str(row.get("label", "")).strip()
                button.icon = str(row.get("icon", "")).strip()
                button.row = int(row.get("row", 0))
                button.column = int(row.get("column", 0))
                button.sort_order = int(row.get("sort_order", index))
                button.command_url = str(row.get("command_url", "")).strip()
                button.ir_id = int(row.get("ir_id", 1))
                button.frequency = int(row.get("frequency", 38))
                button.raw = row.get("raw", [])
                button.is_active = row.get("is_active") is True
                button.requires_confirmation = row.get("requires_confirmation") is True
                button.full_clean(validate_unique=False, validate_constraints=False)
            except (TypeError, ValueError, ValidationError) as exc:
                errors = _button_validation_error(exc) if isinstance(exc, ValidationError) else {"buttons": [str(exc)]}
                return JsonResponse(
                    {"detail": f"Check button {index + 1}.", "errors": errors},
                    status=400,
                )

            position = (button.row, button.column)
            if position in positions:
                return JsonResponse({"detail": "Each button must have a unique grid position."}, status=400)
            if button.key in keys:
                return JsonResponse({"detail": "Each button must have a unique action."}, status=400)
            positions.add(position)
            keys.add(button.key)
            buttons.append(button)

        if set(submitted_ids) != set(existing_by_id):
            return JsonResponse({"detail": "The button list is stale. Reload and try again."}, status=409)

        # Move persisted rows into a disjoint temporary area so action and position
        # swaps cannot trip immediate database uniqueness constraints.
        for button in existing:
            RemoteButton.objects.filter(pk=button.pk).update(key=f"temporary-{button.pk}")
        max_row = max((button.row for button in existing), default=0)
        RemoteButton.objects.filter(remote=remote).update(row=F("row") + max_row + 1000)

        for button in buttons:
            button.save()

        for field in remote_fields:
            setattr(remote, field, remote_settings[field])
        remote.device_name = remote_settings["device_name"].strip()
        remote.protocol = protocol
        remote.brand = protocol_defaults(protocol)[0]
        remote.protocol_model = protocol_model
        remote.ac_control_visibility = visibility
        remote.save(
            update_fields=(
                *remote_fields,
                "device_name",
                "protocol",
                "brand",
                "protocol_model",
                "ac_control_visibility",
                "updated_at",
            )
        )

    return JsonResponse(
        {
            "ok": True,
            "buttons": [_serialize_config_button(button) for button in buttons],
        }
    )


@staff_member_required
@require_POST
def button_config_ac_test_view(request, remote_id):
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON payload."}, status=400)
    state = payload.get("state") if isinstance(payload, dict) else None
    if not isinstance(state, dict):
        return JsonResponse({"detail": "AC state must be an object."}, status=400)
    try:
        confirmed = set_ac_state(remote_id, state)
    except ACControlError as exc:
        status_map = {
            "not_found": 404,
            "wrong_type": 400,
            "unconfigured": 400,
            "invalid_state": 400,
            "timeout": 504,
            "network_error": 502,
            "controller_error": 502,
            "invalid_response": 502,
            "stale_response": 409,
        }
        return JsonResponse(
            {"success": False, "code": exc.code, "detail": exc.message},
            status=status_map.get(exc.code, 400),
        )
    return JsonResponse(
        {
            "success": True,
            "state": serialize_ac_state(confirmed),
            "state_version": confirmed.state_version,
        }
    )


@staff_member_required
@require_POST
def button_config_sync_ip_view(request, remote_id):
    remote = get_object_or_404(RemoteControl, pk=remote_id)
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON payload."}, status=400)
    device_name = payload.get("device_name") if isinstance(payload, dict) else None
    if not isinstance(device_name, str) or not device_name.strip() or len(device_name) > 120:
        return JsonResponse({"detail": "Enter a valid Device name."}, status=400)

    remote.device_name = device_name.strip()
    remote.save(update_fields=("device_name", "updated_at"))
    try:
        devices = discover_identity_devices()
    except DeviceDiscoveryError as exc:
        return JsonResponse({"detail": str(exc)}, status=503)

    key = remote.device_name.casefold()
    matches = [device for device in devices if device["name"].strip().casefold() == key]
    if not matches:
        return JsonResponse({"detail": f'Device "{remote.device_name}" was not found.'}, status=404)
    if len(matches) > 1:
        return JsonResponse({"detail": "Multiple devices reported the same Device name."}, status=409)

    device = matches[0]
    if (
        remote.device_type == RemoteControl.DeviceType.AC
        and "ac_control" not in device.get("capabilities", [])
    ):
        return JsonResponse(
            {"detail": "The device firmware does not advertise AC control support."},
            status=409,
        )
    if (
        remote.device_type == RemoteControl.DeviceType.LG_TV
        and "lg_tv_remote" not in device.get("capabilities", [])
    ):
        return JsonResponse({"detail": "The device is not an LG TV controller."}, status=409)
    remote.device_ip = device["ip"]
    remote.device_last_seen_at = timezone.now()
    if remote.device_type == RemoteControl.DeviceType.LG_TV:
        remote.controller_url = f"http://{remote.device_ip}"
    command_url = f"http://{remote.device_ip}/ir"
    with transaction.atomic():
        remote.save(
            update_fields=(
                "device_ip",
                "device_last_seen_at",
                "controller_url",
                "updated_at",
            )
        )
        updated_buttons = remote.buttons.update(command_url=command_url)
    return JsonResponse(
        {
            "success": True,
            "device_name": remote.device_name,
            "device_ip": str(remote.device_ip),
            "command_url": command_url,
            "updated_buttons": updated_buttons,
            "firmware_version": device.get("firmware_version", ""),
            "capabilities": device.get("capabilities", []),
        }
    )


class KioskPageView(TemplateView):
    template_name = "kiosk_agent/chat.html"

    def get(self, request, *args, **kwargs):
        expected = settings.KIOSK_API_KEY
        supplied = request.GET.get("key", "")
        has_cookie = valid_kiosk_cookie(request.COOKIES.get(KIOSK_COOKIE_NAME, ""))
        if expected and not has_cookie and not secrets.compare_digest(supplied, expected):
            return HttpResponseForbidden("Kiosk access is not provisioned.")
        response = super().get(request, *args, **kwargs)
        response.set_cookie(
            KIOSK_COOKIE_NAME,
            create_kiosk_cookie(),
            max_age=settings.KIOSK_SESSION_MAX_AGE,
            httponly=True,
            secure=request.is_secure(),
            samesite="Strict",
        )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["voice_wake_word"] = settings.VOICE_WAKE_WORD
        context["voice_source"] = settings.VOICE_SOURCE
        context["voice_activation_mode"] = settings.VOICE_ACTIVATION_MODE
        return context

class TVRemotePageView(KioskPageView):
    template_name = "kiosk_agent/tv_remote.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        remote_id = self.kwargs.get("remote_id")
        remotes = RemoteControl.objects.filter(
            device_type=RemoteControl.DeviceType.LG_TV,
            is_active=True,
            guest_visible=True,
        )
        context["tv_remote"] = (
            remotes.filter(pk=remote_id).first() if remote_id else remotes.first()
        )
        return context


def _has_kiosk_access(request):
    expected = settings.KIOSK_API_KEY
    supplied = request.headers.get("X-Kiosk-Key", "")
    if expected and supplied and secrets.compare_digest(supplied, expected):
        return True
    return valid_kiosk_cookie(request.COOKIES.get(KIOSK_COOKIE_NAME, ""))


def _active_lg_remote(remote_id):
    try:
        return RemoteControl.objects.get(
            pk=remote_id,
            device_type=RemoteControl.DeviceType.LG_TV,
            is_active=True,
        )
    except (RemoteControl.DoesNotExist, TypeError, ValueError):
        return None


@require_POST
def tv_remote_command_view(request):
    if not _has_kiosk_access(request):
        return JsonResponse({"success": False, "error": "Kiosk access denied"}, status=403)
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid JSON payload"}, status=400)
    command = payload.get("command") if isinstance(payload, dict) else None
    remote = _active_lg_remote(payload.get("remote_id") if isinstance(payload, dict) else None)
    if remote is None:
        return JsonResponse({"success": False, "error": "TV remote not found"}, status=404)
    if not isinstance(command, str):
        return JsonResponse({"success": False, "error": "Unsupported TV remote command"}, status=400)
    try:
        result = send_tv_command(remote.controller_url, command)
    except TVRemoteError as exc:
        status_map = {
            "invalid_command": 400,
            "not_configured": 503,
            "timeout": 504,
            "offline": 503,
            "controller_error": 502,
            "invalid_response": 502,
        }
        return JsonResponse(
            {"success": False, "error": exc.message},
            status=status_map.get(exc.code, 502),
        )
    return JsonResponse({"success": True, "command": result.get("command", command)})


@require_GET
def tv_remote_status_view(request):
    if not _has_kiosk_access(request):
        return JsonResponse({"success": False, "online": False, "error": "Kiosk access denied"}, status=403)
    remote = _active_lg_remote(request.GET.get("remote_id"))
    if remote is None:
        return JsonResponse({"success": False, "online": False, "error": "TV remote not found"}, status=404)
    try:
        get_tv_status(remote.controller_url)
    except TVRemoteError as exc:
        status_code = 504 if exc.code == "timeout" else 503
        return JsonResponse(
            {"success": False, "online": False, "error": exc.message},
            status=status_code,
        )
    return JsonResponse({"success": True, "online": True})


def _validated_realtime_session(data):
    now = timezone.now()
    try:
        session = RealtimeSession.objects.select_for_update().get(
            pk=data["session_id"],
            stay_id=data["stay_id"],
            state=RealtimeSession.State.ACTIVE,
        )
    except RealtimeSession.DoesNotExist:
        return None, "invalid_session"
    config = ChaletConfig.load()
    if config.current_stay_id != data["stay_id"]:
        session.state = RealtimeSession.State.RESET
        session.save(update_fields=("state", "last_activity_at"))
        return None, "stay_expired"
    if session.expires_at <= now:
        session.state = RealtimeSession.State.EXPIRED
        session.save(update_fields=("state", "last_activity_at"))
        return None, "session_expired"
    session.expires_at = now + timedelta(
        seconds=settings.REALTIME_LOCAL_SESSION_TTL_SECONDS
    )
    session.save(update_fields=("expires_at", "last_activity_at"))
    return session, ""


class ChatView(APIView):
    authentication_classes = []
    permission_classes = (OptionalKioskKeyPermission,)

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            request_id, _ = enqueue_message(serializer.validated_data["message"])
        except AgentBusyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response({"request_id": request_id, "status": "queued"}, status=status.HTTP_202_ACCEPTED)


class MemoryView(APIView):
    authentication_classes = []
    permission_classes = (OptionalKioskKeyPermission,)

    def get(self, request):
        config = ChaletConfig.load()
        try:
            limit = min(max(int(request.query_params.get("limit", 50)), 1), 100)
            before_id = int(request.query_params.get("before_id", 0))
        except (TypeError, ValueError):
            return Response({"detail": "Invalid pagination parameters."}, status=400)
        messages = KioskMessage.objects.filter(
            stay_id=config.current_stay_id
        ).exclude(role=KioskMessage.Role.TOOL)
        if before_id > 0:
            messages = messages.filter(pk__lt=before_id)
        page = list(messages.order_by("-id")[: limit + 1])
        has_more = len(page) > limit
        page = page[:limit]
        page.reverse()
        return Response({
            "chalet": ChaletPublicSerializer(config).data,
            "stay_id": config.current_stay_id,
            "voice": {
                "source": settings.VOICE_SOURCE,
                "activation_mode": settings.VOICE_ACTIVATION_MODE,
                "wake_word": settings.VOICE_WAKE_WORD,
            },
            "messages": KioskMessageSerializer(page, many=True).data,
            "pagination": {
                "has_more": has_more,
                "before_id": page[0].pk if page and has_more else None,
            },
        })


class RealtimeSessionView(APIView):
    permission_classes = (OptionalKioskKeyPermission,)
    parser_classes = [parsers.BaseParser]
    authentication_classes = []

    def post(self, request):
        if settings.VOICE_SOURCE != "realtime":
            return Response({"detail": "Realtime voice is disabled."}, status=409)
        if request.content_type not in {"application/sdp", "text/plain"}:
            return Response({"detail": "Content-Type must be application/sdp."}, status=415)
        try:
            sdp = request.body.decode("utf-8")
        except UnicodeDecodeError:
            return Response({"detail": "Invalid SDP encoding."}, status=400)
        if not sdp.startswith("v=0") or len(sdp) > 100_000:
            return Response({"detail": "Invalid SDP offer."}, status=400)
        try:
            upstream = create_realtime_call(sdp)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=503)
        except Exception:
            return Response({"detail": "Unable to create the realtime session."}, status=502)
        response = HttpResponse(
            upstream.content,
            status=upstream.status_code,
            content_type=upstream.headers.get("content-type", "application/sdp"),
        )
        if 200 <= upstream.status_code < 300:
            config = ChaletConfig.load()
            now = timezone.now()
            RealtimeSession.objects.filter(
                state=RealtimeSession.State.ACTIVE,
                expires_at__lte=now,
            ).update(state=RealtimeSession.State.EXPIRED)
            RealtimeSession.objects.filter(
                state__in=(
                    RealtimeSession.State.CLOSED,
                    RealtimeSession.State.RESET,
                    RealtimeSession.State.EXPIRED,
                ),
                created_at__lt=now - timedelta(days=7),
            ).delete()
            local_session = RealtimeSession.objects.create(
                stay_id=config.current_stay_id,
                expires_at=now + timedelta(
                    seconds=settings.REALTIME_LOCAL_SESSION_TTL_SECONDS
                ),
            )
            response["X-Local-Session-ID"] = str(local_session.pk)
            response["X-Stay-ID"] = str(config.current_stay_id)
        return response


class RealtimeMessageView(APIView):
    authentication_classes = []
    permission_classes = (OptionalKioskKeyPermission,)

    def post(self, request):
        serializer = RealtimeMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            session, error = _validated_realtime_session(data)
            if error:
                return Response({"detail": error}, status=409)
            event_id = data.get("event_id") or None
            try:
                with transaction.atomic():
                    message = KioskMessage.objects.create(
                        stay_id=data["stay_id"],
                        request_id=data["request_id"],
                        role=data["role"],
                        content=data["content"],
                        status=KioskMessage.Status.COMPLETE,
                        event_id=event_id,
                        metadata={
                            "source": "realtime",
                            "session_id": str(session.pk),
                            "input_mode": data["input_mode"],
                            "model": settings.REALTIME_MODEL,
                        },
                    )
            except IntegrityError:
                return Response({"status": "duplicate"}, status=200)
            # The database primary key is already a monotonic, indexed event sequence.
            message.sequence = message.pk
            message.save(update_fields=("sequence",))
        transaction.on_commit(
            lambda: async_to_sync(get_channel_layer().group_send)(
                stay_group(str(data["stay_id"])),
                {
                    "type": "agent.event",
                    "payload": {
                        "event": "message_persisted",
                        "request_id": str(data["request_id"]),
                        "message_id": message.pk,
                        "stay_id": str(data["stay_id"]),
                        "sequence": message.sequence,
                        "role": message.role,
                        "content": message.content,
                    },
                },
            )
        )
        return Response({"status": "saved", "message_id": message.pk}, status=201)


class RealtimeSessionCloseView(APIView):
    authentication_classes = []
    permission_classes = (OptionalKioskKeyPermission,)

    def post(self, request):
        serializer = RealtimeSessionIdentitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        updated = RealtimeSession.objects.filter(
            pk=data["session_id"],
            stay_id=data["stay_id"],
            state=RealtimeSession.State.ACTIVE,
        ).update(state=RealtimeSession.State.CLOSED)
        return Response({"status": "closed" if updated else "inactive"})


class RealtimeToolView(APIView):
    authentication_classes = []
    permission_classes = (OptionalKioskKeyPermission,)

    def post(self, request):
        serializer = RealtimeToolSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["name"] not in TOOL_MODELS:
            return Response({"ok": False, "error": "unknown_tool"}, status=400)
        with transaction.atomic():
            session, error = _validated_realtime_session(data)
            if error:
                return Response({"ok": False, "error": error}, status=409)
            existing = KioskMessage.objects.filter(
                stay_id=data["stay_id"],
                request_id=data["request_id"],
                role=KioskMessage.Role.TOOL,
            )
            duplicate = existing.filter(tool_call_id=data["call_id"]).first()
            if duplicate:
                return Response(json.loads(duplicate.content), status=200)
            if existing.count() >= 5:
                return Response({"ok": False, "error": "tool_iteration_limit"}, status=429)
            try:
                with transaction.atomic():
                    reservation = KioskMessage.objects.create(
                        stay_id=data["stay_id"],
                        request_id=data["request_id"],
                        role=KioskMessage.Role.TOOL,
                        content='{"ok": false, "error": "tool_in_progress"}',
                        status=KioskMessage.Status.STREAMING,
                        tool_name=data["name"],
                        tool_call_id=data["call_id"],
                        metadata={
                            "source": "realtime",
                            "session_id": str(session.pk),
                        },
                    )
            except IntegrityError:
                duplicate = KioskMessage.objects.get(
                    stay_id=data["stay_id"], tool_call_id=data["call_id"]
                )
                return Response(json.loads(duplicate.content), status=200)
        result = execute_tool(
            data["name"],
            json.dumps(data["arguments"], ensure_ascii=False),
            stay_id=str(data["stay_id"]),
            request_id=str(data["request_id"]),
        )
        KioskMessage.objects.filter(pk=reservation.pk).update(
            content=result,
            status=KioskMessage.Status.COMPLETE,
        )
        return Response(json.loads(result), status=200)


class ResetView(APIView):
    authentication_classes = []
    permission_classes = (OptionalKioskKeyPermission,)

    def post(self, request):
        with transaction.atomic():
            config = ChaletConfig.objects.select_for_update().get_or_create(pk=ChaletConfig.SINGLETON_PK)[0]
            old_stay_id = config.current_stay_id
            RealtimeSession.objects.filter(
                stay_id=old_stay_id,
                state=RealtimeSession.State.ACTIVE,
            ).update(state=RealtimeSession.State.RESET)
            deleted, _ = KioskMessage.objects.filter(stay_id=old_stay_id).delete()
            config.current_stay_id = uuid.uuid4()
            config.save(update_fields=("current_stay_id", "updated_at"))
            KioskAuditLog.objects.create(
                stay_id=old_stay_id,
                event=KioskAuditLog.Event.STAY_RESET,
                details={"messages_deleted": deleted, "new_stay_id": str(config.current_stay_id)},
            )
        transaction.on_commit(
            lambda: async_to_sync(get_channel_layer().group_send)(
                stay_group(str(old_stay_id)),
                {
                    "type": "agent.event",
                    "payload": {
                        "event": "reset",
                        "new_stay_id": str(config.current_stay_id),
                    },
                },
            )
        )
        return Response({"status": "reset", "stay_id": config.current_stay_id})


class HealthView(APIView):
    authentication_classes = ()
    permission_classes = ()
    throttle_classes = ()

    def get(self, request):
        checks = {"database": False, "redis": False}
        try:
            connection.ensure_connection()
            checks["database"] = True
        except Exception:
            pass
        try:
            checks["redis"] = bool(redis.Redis.from_url(settings.REDIS_URL).ping())
        except Exception:
            pass
        healthy = all(checks.values())
        return Response({"status": "ok" if healthy else "degraded", "checks": checks}, status=200 if healthy else 503)


class StatusView(APIView):
    authentication_classes = ()
    permission_classes = (OptionalKioskKeyPermission,)
    throttle_classes = ()

    def get(self, request):
        config = ChaletConfig.load()
        now = timezone.now()
        redis_ok = False
        queue_depth = None
        try:
            client = redis.Redis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            redis_ok = bool(client.ping())
            queue_depth = client.llen("celery")
        except Exception:
            pass
        active_sessions = RealtimeSession.objects.filter(
            stay_id=config.current_stay_id,
            state=RealtimeSession.State.ACTIVE,
            expires_at__gt=now,
        ).count()
        active_fallback = KioskMessage.objects.filter(
            stay_id=config.current_stay_id,
            role=KioskMessage.Role.USER,
            status__in=(KioskMessage.Status.QUEUED, KioskMessage.Status.STREAMING),
        ).count()
        last_failure = KioskAuditLog.objects.filter(
            event=KioskAuditLog.Event.AGENT_FAILED
        ).first()
        return Response(
            {
                "status": "ok" if redis_ok else "degraded",
                "redis": redis_ok,
                "queue_depth": queue_depth,
                "active_realtime_sessions": active_sessions,
                "active_fallback_requests": active_fallback,
                "last_agent_failure_at": (
                    last_failure.created_at if last_failure else None
                ),
            }
        )


class RemotesListView(APIView):
    authentication_classes = []
    permission_classes = (OptionalKioskKeyPermission,)

    def get(self, request):
        remotes = (
            RemoteControl.objects.filter(is_active=True, guest_visible=True)
            .select_related("ac_state")
            .prefetch_related("buttons")
            .order_by("sort_order", "name")
        )
        # AC remotes are state-based and do not need RAW button records.
        payload = []
        for remote in remotes:
            active_buttons = [b for b in remote.buttons.all() if b.is_active]
            if remote.device_type == RemoteControl.DeviceType.RAW and not active_buttons:
                continue
            payload.append(RemoteControlPublicSerializer(remote).data)
        return Response({"remotes": payload})


class RemotesSyncView(APIView):
    authentication_classes = []
    permission_classes = (OptionalKioskKeyPermission,)

    def post(self, request):
        try:
            result = sync_remote_ips()
        except DeviceDiscoveryError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"success": True, **result})


class RemoteButtonPressView(APIView):
    authentication_classes = []
    permission_classes = (OptionalKioskKeyPermission,)

    def post(self, request, button_id):
        config = ChaletConfig.load()
        try:
            result = press_remote_button(
                int(button_id),
                source="kiosk",
                stay_id=config.current_stay_id,
                require_guest_visible=True,
            )
        except RemoteCommandError as exc:
            status_map = {
                "not_found": status.HTTP_404_NOT_FOUND,
                "forbidden": status.HTTP_403_FORBIDDEN,
                "unconfigured": status.HTTP_400_BAD_REQUEST,
                "invalid_url": status.HTTP_400_BAD_REQUEST,
                "invalid_command": status.HTTP_400_BAD_REQUEST,
                "cooldown": status.HTTP_429_TOO_MANY_REQUESTS,
                "timeout": status.HTTP_504_GATEWAY_TIMEOUT,
                "network_error": status.HTTP_502_BAD_GATEWAY,
                "http_error": status.HTTP_502_BAD_GATEWAY,
                "controller_error": status.HTTP_502_BAD_GATEWAY,
            }
            return Response(
                {"ok": False, "status": exc.code, "detail": exc.message, "execution": "server"},
                status=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
            )
        return Response(
            {
                "ok": True,
                "status": "success",
                "execution": "server",
                "label": result.get("label"),
                "target": result.get("target") or "",
            }
        )


class ACStateView(APIView):
    authentication_classes = []
    permission_classes = (OptionalKioskKeyPermission,)

    def get(self, request, device_id):
        try:
            device = RemoteControl.objects.get(
                pk=device_id,
                device_type=RemoteControl.DeviceType.AC,
            )
        except RemoteControl.DoesNotExist:
            return Response({"detail": "AC device not found."}, status=status.HTTP_404_NOT_FOUND)
        state, _ = ACState.objects.get_or_create(device=device)
        return Response(
            {
                "device_id": device.pk,
                "state_version": state.state_version,
                "state": serialize_ac_state(state),
                "updated_at": state.updated_at,
            }
        )

    def patch(self, request, device_id):
        if not isinstance(request.data, dict):
            return Response({"detail": "JSON object required."}, status=status.HTTP_400_BAD_REQUEST)
        changes = dict(request.data)
        request_id = changes.pop("request_id", None)
        try:
            state = set_ac_state(device_id, changes, request_id=request_id)
        except ACControlError as exc:
            status_map = {
                "not_found": status.HTTP_404_NOT_FOUND,
                "wrong_type": status.HTTP_400_BAD_REQUEST,
                "unconfigured": status.HTTP_400_BAD_REQUEST,
                "invalid_state": status.HTTP_400_BAD_REQUEST,
                "timeout": status.HTTP_504_GATEWAY_TIMEOUT,
                "network_error": status.HTTP_502_BAD_GATEWAY,
                "controller_error": status.HTTP_502_BAD_GATEWAY,
                "invalid_response": status.HTTP_502_BAD_GATEWAY,
                "stale_response": status.HTTP_409_CONFLICT,
            }
            return Response(
                {"success": False, "code": exc.code, "detail": exc.message},
                status=status_map.get(exc.code, status.HTTP_400_BAD_REQUEST),
            )
        return Response(
            {
                "success": True,
                "device_id": state.device_id,
                "state_version": state.state_version,
                "state": serialize_ac_state(state),
                "updated_at": state.updated_at,
            }
        )


class InternalACStateSyncView(APIView):
    """ESP32 notification endpoint. It never sends a command back to the ESP32."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        expected_token = settings.ESP32_SYNC_TOKEN
        supplied_token = request.headers.get("X-ESP32-Token", "")
        if expected_token and not secrets.compare_digest(expected_token, supplied_token):
            return Response({"detail": "Invalid ESP32 sync token."}, status=status.HTTP_403_FORBIDDEN)
        if not isinstance(request.data, dict):
            return Response({"detail": "JSON object required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            state, applied = accept_esp32_state_sync(dict(request.data))
        except ACControlError as exc:
            http_status = (
                status.HTTP_404_NOT_FOUND
                if exc.code == "not_found"
                else status.HTTP_409_CONFLICT
                if exc.code == "ambiguous_device"
                else status.HTTP_400_BAD_REQUEST
            )
            return Response(
                {"success": False, "code": exc.code, "detail": exc.message},
                status=http_status,
            )
        return Response(
            {
                "success": True,
                "applied": applied,
                "request_id": request.data.get("request_id"),
                "remote_id": state.device_id,
                "state_version": state.state_version,
            }
        )
