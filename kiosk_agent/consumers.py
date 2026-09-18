import secrets
import uuid
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from .core.agent_engine import stay_group
from .models import ChaletConfig
from .permissions import KIOSK_COOKIE_NAME, valid_kiosk_cookie
from .serializers import ChatRequestSerializer
from .services import AgentBusyError, enqueue_message
from .tasks import welcome_tts_task


class KioskConsumer(AsyncJsonWebsocketConsumer):
    group_name: str

    async def connect(self):
        if not self._valid_key():
            await self.close(code=4403)
            return
        stay_id = await self._current_stay_id()
        self.group_name = stay_group(stay_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({"event": "connected", "stay_id": stay_id})

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "voice.welcome" and settings.VOICE_SOURCE == "backend":
            try:
                request_id = str(uuid.UUID(str(content.get("request_id", ""))))
            except (TypeError, ValueError):
                await self.send_json({"event": "error", "message": "Invalid welcome request."})
                return
            stay_id = await self._current_stay_id()
            try:
                await sync_to_async(welcome_tts_task.delay, thread_sensitive=False)(
                    stay_id, request_id
                )
            except Exception:
                await self.send_json({
                    "event": "tts_fallback",
                    "request_id": request_id,
                    "nonce": request_id,
                    "text": "أهلاً وسهلاً، أنا معك. تفضل.",
                })
            return
        if content.get("type") != "chat.message":
            await self.send_json({"event": "error", "message": "Unsupported event type."})
            return
        serializer = ChatRequestSerializer(data={"message": content.get("message")})
        if not serializer.is_valid():
            await self.send_json({"event": "error", "errors": serializer.errors})
            return
        try:
            request_id, _ = await sync_to_async(enqueue_message, thread_sensitive=True)(
                serializer.validated_data["message"]
            )
        except AgentBusyError as exc:
            await self.send_json({"event": "busy", "message": str(exc)})
            return
        await self.send_json({"event": "accepted", "request_id": str(request_id)})

    async def agent_event(self, event):
        await self.send_json(event["payload"])

    @database_sync_to_async
    def _current_stay_id(self):
        return str(ChaletConfig.load().current_stay_id)

    def _valid_key(self):
        expected = settings.KIOSK_API_KEY
        supplied = parse_qs(self.scope.get("query_string", b"").decode()).get("key", [""])[0]
        if expected and supplied and secrets.compare_digest(supplied, expected):
            return True
        return valid_kiosk_cookie(self.scope.get("cookies", {}).get(KIOSK_COOKIE_NAME, ""))
