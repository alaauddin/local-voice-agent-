import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from kiosk_agent.models import (
    ChaletConfig,
    KioskAuditLog,
    KioskMessage,
    RealtimeSession,
)

IN_MEMORY_CHANNELS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


@override_settings(CHANNEL_LAYERS=IN_MEMORY_CHANNELS, KIOSK_API_KEY="")
class KioskApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.config = ChaletConfig.load()
        self.realtime_session = RealtimeSession.objects.create(
            stay_id=self.config.current_stay_id,
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        self.client.get(reverse("kiosk-chat"))

    def realtime_identity(self):
        return {
            "stay_id": str(self.config.current_stay_id),
            "session_id": str(self.realtime_session.pk),
        }

    def test_chat_screen_is_available(self):
        response = self.client.get(reverse("kiosk-chat"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "id=\"chatForm\"")
        self.assertContains(response, "يا غروب")
        self.assertContains(response, "Sunset Resort")
        self.assertContains(response, "مساعد غروب")
        self.assertContains(response, "id=\"messagesDrawer\"")

    def test_root_redirects_to_chat_screen(self):
        response = self.client.get("/")
        self.assertRedirects(response, reverse("kiosk-chat"), fetch_redirect_response=False)

    @patch("kiosk_agent.services.run_concierge_task.delay")
    def test_chat_enqueues_without_running_agent(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("kiosk_agent:chat"), {"message": "I need towels"}, format="json")
        self.assertEqual(response.status_code, 202)
        message = KioskMessage.objects.get(role=KioskMessage.Role.USER)
        self.assertEqual(message.content, "I need towels")
        self.assertEqual(message.status, KioskMessage.Status.QUEUED)
        delay.assert_called_once_with(str(self.config.current_stay_id), str(message.request_id))

    def test_chat_rejects_overlapping_request(self):
        KioskMessage.objects.create(
            stay_id=self.config.current_stay_id,
            role=KioskMessage.Role.USER,
            content="first",
            status=KioskMessage.Status.STREAMING,
        )
        response = self.client.post(reverse("kiosk_agent:chat"), {"message": "second"}, format="json")
        self.assertEqual(response.status_code, 409)

    @patch("kiosk_agent.services.run_concierge_task.delay")
    def test_completed_reply_recovers_stale_queued_user(self, delay):
        previous_request_id = uuid.uuid4()
        user = KioskMessage.objects.create(
            stay_id=self.config.current_stay_id,
            request_id=previous_request_id,
            role=KioskMessage.Role.USER,
            content="first",
            status=KioskMessage.Status.QUEUED,
        )
        KioskMessage.objects.create(
            stay_id=self.config.current_stay_id,
            request_id=previous_request_id,
            role=KioskMessage.Role.ASSISTANT,
            content="done",
            status=KioskMessage.Status.COMPLETE,
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("kiosk_agent:chat"), {"message": "next"}, format="json"
            )
        self.assertEqual(response.status_code, 202)
        user.refresh_from_db()
        self.assertEqual(user.status, KioskMessage.Status.COMPLETE)
        delay.assert_called_once()

    def test_reset_deletes_memory_and_rotates_stay(self):
        old_stay = self.config.current_stay_id
        KioskMessage.objects.create(stay_id=old_stay, role="user", content="private memory")
        response = self.client.post(reverse("kiosk_agent:reset"), {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.config.refresh_from_db()
        self.assertNotEqual(old_stay, self.config.current_stay_id)
        self.assertFalse(KioskMessage.objects.filter(stay_id=old_stay).exists())
        self.assertTrue(KioskAuditLog.objects.filter(stay_id=old_stay, event="stay_reset").exists())
        self.realtime_session.refresh_from_db()
        self.assertEqual(self.realtime_session.state, RealtimeSession.State.RESET)

    @override_settings(VOICE_SOURCE="realtime")
    @patch("kiosk_agent.views.create_realtime_call")
    def test_realtime_session_proxies_sdp_without_exposing_api_key(self, create_call):
        create_call.return_value = SimpleNamespace(
            content=b"v=0\r\no=answer",
            status_code=201,
            headers={"content-type": "application/sdp"},
        )
        response = self.client.generic(
            "POST",
            reverse("kiosk_agent:realtime-session"),
            data="v=0\r\no=offer",
            content_type="application/sdp",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.content, b"v=0\r\no=answer")
        self.assertTrue(response["X-Local-Session-ID"])
        self.assertEqual(response["X-Stay-ID"], str(self.config.current_stay_id))
        create_call.assert_called_once_with("v=0\r\no=offer")

    @override_settings(VOICE_SOURCE="realtime")
    def test_realtime_session_rejects_invalid_sdp(self):
        response = self.client.generic(
            "POST",
            reverse("kiosk_agent:realtime-session"),
            data="not-an-offer",
            content_type="application/sdp",
        )
        self.assertEqual(response.status_code, 400)

    def test_realtime_message_is_persisted_idempotently(self):
        request_id = uuid.uuid4()
        payload = {
            **self.realtime_identity(),
            "request_id": str(request_id),
            "role": "user",
            "content": "أحتاج مناشف",
            "event_id": "item-123",
            "input_mode": "voice",
        }
        first = self.client.post(reverse("kiosk_agent:realtime-message"), payload, format="json")
        second = self.client.post(reverse("kiosk_agent:realtime-message"), payload, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(KioskMessage.objects.filter(request_id=request_id).count(), 1)

    def test_realtime_tool_rejects_unknown_tool(self):
        response = self.client.post(
            reverse("kiosk_agent:realtime-tool"),
            {
                **self.realtime_identity(),
                "request_id": str(uuid.uuid4()),
                "call_id": "call-1",
                "name": "delete_everything",
                "arguments": {},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "unknown_tool")

    def test_realtime_tool_is_capped_at_five_calls_per_turn(self):
        request_id = uuid.uuid4()
        for index in range(5):
            KioskMessage.objects.create(
                stay_id=self.config.current_stay_id,
                request_id=request_id,
                role=KioskMessage.Role.TOOL,
                content='{"ok": true}',
                tool_name="get_property_information",
                tool_call_id=f"existing-{index}",
            )
        response = self.client.post(
            reverse("kiosk_agent:realtime-tool"),
            {
                **self.realtime_identity(),
                "request_id": str(request_id),
                "call_id": "call-6",
                "name": "get_property_information",
                "arguments": {"topic": "wifi"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "tool_iteration_limit")

    def test_realtime_message_rejects_expired_stay(self):
        old_stay = self.config.current_stay_id
        self.config.rotate_stay()
        response = self.client.post(
            reverse("kiosk_agent:realtime-message"),
            {
                "stay_id": str(old_stay),
                "session_id": str(self.realtime_session.pk),
                "request_id": str(uuid.uuid4()),
                "role": "user",
                "content": "رسالة متأخرة",
                "event_id": "late-event",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(KioskMessage.objects.filter(event_id="late-event").exists())

    def test_realtime_session_can_be_closed_locally(self):
        response = self.client.post(
            reverse("kiosk_agent:realtime-session-close"),
            self.realtime_identity(),
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.realtime_session.refresh_from_db()
        self.assertEqual(self.realtime_session.state, RealtimeSession.State.CLOSED)

    def test_cookie_rejects_cross_origin_post(self):
        response = self.client.post(
            reverse("kiosk_agent:reset"),
            {},
            format="json",
            HTTP_ORIGIN="https://other.example",
        )
        self.assertEqual(response.status_code, 403)

    def test_memory_is_paginated(self):
        for index in range(55):
            KioskMessage.objects.create(
                stay_id=self.config.current_stay_id,
                role=KioskMessage.Role.USER,
                content=f"message {index}",
            )
        response = self.client.get(reverse("kiosk_agent:messages"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["messages"]), 50)
        self.assertTrue(response.json()["pagination"]["has_more"])


@override_settings(KIOSK_API_KEY="secret")
class KioskKeyTests(TestCase):
    def test_rejects_missing_key(self):
        response = self.client.get(reverse("kiosk_agent:messages"))
        self.assertEqual(response.status_code, 403)

    def test_accepts_valid_key(self):
        response = self.client.get(reverse("kiosk_agent:messages"), HTTP_X_KIOSK_KEY="secret")
        self.assertEqual(response.status_code, 200)
