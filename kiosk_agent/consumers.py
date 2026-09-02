import secrets
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from .core.agent_engine import stay_group
from .models import ChaletConfig
from .serializers import ChatRequestSerializer
from .services import AgentBusyError, enqueue_message


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
        if not expected:
            return True
        supplied = parse_qs(self.scope.get("query_string", b"").decode()).get("key", [""])[0]
        return secrets.compare_digest(supplied, expected)
