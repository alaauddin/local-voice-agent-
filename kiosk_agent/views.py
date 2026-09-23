import json
import secrets
import uuid
from datetime import timedelta

import redis
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.views.generic import TemplateView
from rest_framework import parsers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .core.agent_engine import stay_group
from .core.realtime import create_realtime_call
from .core.tools import TOOL_MODELS, execute_tool
from .models import ChaletConfig, KioskAuditLog, KioskMessage, RealtimeSession, RemoteControl
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
            .prefetch_related("buttons")
            .order_by("sort_order", "name")
        )
        # Only expose remotes that have at least one active button.
        payload = []
        for remote in remotes:
            active_buttons = [b for b in remote.buttons.all() if b.is_active]
            if not active_buttons:
                continue
            payload.append(RemoteControlPublicSerializer(remote).data)
        return Response({"remotes": payload})


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
