import uuid
import json

import redis
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import connection, transaction
from django.http import HttpResponse
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .core.agent_engine import stay_group
from .core.realtime import create_realtime_call
from .core.tools import TOOL_MODELS, execute_tool
from .models import ChaletConfig, KioskAuditLog, KioskMessage
from .permissions import OptionalKioskKeyPermission
from .serializers import (
    ChatRequestSerializer,
    ChaletPublicSerializer,
    KioskMessageSerializer,
    RealtimeMessageSerializer,
    RealtimeToolSerializer,
)
from .services import AgentBusyError, enqueue_message


class KioskPageView(TemplateView):
    template_name = "kiosk_agent/chat.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["voice_wake_word"] = settings.VOICE_WAKE_WORD
        context["voice_source"] = settings.VOICE_SOURCE
        return context


class ChatView(APIView):
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
    permission_classes = (OptionalKioskKeyPermission,)

    def get(self, request):
        config = ChaletConfig.load()
        messages = KioskMessage.objects.filter(stay_id=config.current_stay_id).exclude(role=KioskMessage.Role.TOOL)
        return Response({
            "chalet": ChaletPublicSerializer(config).data,
            "stay_id": config.current_stay_id,
            "messages": KioskMessageSerializer(messages, many=True).data,
        })


class RealtimeSessionView(APIView):
    permission_classes = (OptionalKioskKeyPermission,)

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
        return HttpResponse(
            upstream.content,
            status=upstream.status_code,
            content_type=upstream.headers.get("content-type", "application/sdp"),
        )


class RealtimeMessageView(APIView):
    permission_classes = (OptionalKioskKeyPermission,)

    def post(self, request):
        serializer = RealtimeMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        config = ChaletConfig.load()
        event_id = data.get("event_id", "")
        if event_id and KioskMessage.objects.filter(
            stay_id=config.current_stay_id,
            metadata__event_id=event_id,
        ).exists():
            return Response({"status": "duplicate"}, status=200)
        message = KioskMessage.objects.create(
            stay_id=config.current_stay_id,
            request_id=data["request_id"],
            role=data["role"],
            content=data["content"],
            status=KioskMessage.Status.COMPLETE,
            metadata={
                "source": "realtime",
                "event_id": event_id,
                "input_mode": data["input_mode"],
                "model": settings.REALTIME_MODEL,
            },
        )
        return Response({"status": "saved", "message_id": message.pk}, status=201)


class RealtimeToolView(APIView):
    permission_classes = (OptionalKioskKeyPermission,)

    def post(self, request):
        serializer = RealtimeToolSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["name"] not in TOOL_MODELS:
            return Response({"ok": False, "error": "unknown_tool"}, status=400)
        config = ChaletConfig.load()
        existing = KioskMessage.objects.filter(
            stay_id=config.current_stay_id,
            request_id=data["request_id"],
            role=KioskMessage.Role.TOOL,
        )
        duplicate = existing.filter(tool_call_id=data["call_id"]).first()
        if duplicate:
            return Response(json.loads(duplicate.content), status=200)
        if existing.count() >= 5:
            return Response({"ok": False, "error": "tool_iteration_limit"}, status=429)
        result = async_to_sync(execute_tool)(
            data["name"],
            json.dumps(data["arguments"], ensure_ascii=False),
            stay_id=str(config.current_stay_id),
            request_id=str(data["request_id"]),
        )
        KioskMessage.objects.create(
            stay_id=config.current_stay_id,
            request_id=data["request_id"],
            role=KioskMessage.Role.TOOL,
            content=result,
            status=KioskMessage.Status.COMPLETE,
            tool_name=data["name"],
            tool_call_id=data["call_id"],
            metadata={"source": "realtime"},
        )
        return Response(json.loads(result), status=200)


class ResetView(APIView):
    permission_classes = (OptionalKioskKeyPermission,)

    def post(self, request):
        with transaction.atomic():
            config = ChaletConfig.objects.select_for_update().get_or_create(pk=ChaletConfig.SINGLETON_PK)[0]
            old_stay_id = config.current_stay_id
            deleted, _ = KioskMessage.objects.filter(stay_id=old_stay_id).delete()
            config.current_stay_id = uuid.uuid4()
            config.save(update_fields=("current_stay_id", "updated_at"))
            KioskAuditLog.objects.create(
                stay_id=old_stay_id,
                event=KioskAuditLog.Event.STAY_RESET,
                details={"messages_deleted": deleted, "new_stay_id": str(config.current_stay_id)},
            )
        async_to_sync(get_channel_layer().group_send)(
            stay_group(str(old_stay_id)),
            {"type": "agent.event", "payload": {"event": "reset", "new_stay_id": str(config.current_stay_id)}},
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
