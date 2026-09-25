from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from kiosk_agent.ac_control import ACControlError, accept_esp32_state_sync, set_ac_state
from kiosk_agent.models import ACState, RemoteControl


def confirmed_payload(*, temperature=22, version=1):
    return {
        "success": True,
        "source": "esp32",
        "brand": "gree",
        "protocol": "gree",
        "model": "default",
        "state_version": version,
        "updated_at": 1234,
        "state": {
            "power": True,
            "mode": "cool",
            "temperature": temperature,
            "fan": "auto",
            "swing_vertical": False,
            "swing_horizontal": False,
            "turbo": False,
            "sleep": False,
            "eco": False,
            "quiet": False,
            "light": False,
            "x_fan": False,
        },
    }


@override_settings(KIOSK_API_KEY="", AC_COMMAND_TIMEOUT_SECONDS=1)
class ACControlTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.get(reverse("kiosk-chat"))
        self.device = RemoteControl.objects.create(
            name="Living Room AC",
            slug="living-room-ac",
            device_name="ESP32 IR Controller",
            device_ip="192.168.1.50",
            device_type=RemoteControl.DeviceType.AC,
            brand="gree",
            protocol="gree",
            protocol_model="default",
        )
        self.state = ACState.objects.create(device=self.device)

    @patch("kiosk_agent.ac_control.httpx.Client")
    def test_django_saves_only_confirmed_esp32_state(self, client_cls):
        response = type("Response", (), {})()
        response.status_code = 200
        response.json = lambda: confirmed_payload(temperature=22, version=1)
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = response

        state = set_ac_state(self.device.pk, {"temperature": 22}, request_id="req-1")

        self.assertEqual(state.temperature, 22)
        self.assertEqual(state.state_version, 1)
        sent = client.post.call_args.kwargs["json"]
        self.assertEqual(sent["source"], "django")
        self.assertEqual(sent["request_id"], "req-1")
        self.assertEqual(sent["brand"], "gree")
        self.assertEqual(sent["protocol"], "gree")
        self.assertEqual(sent["model"], "default")
        self.assertEqual(sent["temperature"], 22)

    @patch("kiosk_agent.ac_control.httpx.Client")
    def test_failed_transmission_does_not_change_django_state(self, client_cls):
        response = type("Response", (), {})()
        response.status_code = 500
        response.json = lambda: {"success": False, "message": "send failed"}
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = response

        with self.assertRaises(ACControlError):
            set_ac_state(self.device.pk, {"temperature": 19})

        self.state.refresh_from_db()
        self.assertEqual(self.state.temperature, 24)
        self.assertEqual(self.state.state_version, 0)

    def test_internal_sync_ignores_older_version_without_looping(self):
        self.state.state_version = 5
        self.state.temperature = 25
        self.state.save()
        payload = confirmed_payload(temperature=18, version=4)
        payload["esp32_id"] = "ESP32 IR Controller"

        state, applied = accept_esp32_state_sync(payload)

        self.assertFalse(applied)
        self.assertEqual(state.temperature, 25)
        self.assertEqual(state.state_version, 5)

    def test_ac_remote_is_listed_with_state_without_raw_buttons(self):
        self.state.power = True
        self.state.mode = ACState.Mode.COOL
        self.state.temperature = 21
        self.state.fan = ACState.Fan.HIGH
        self.state.swing_vertical = True
        self.state.save()

        response = self.client.get(reverse("kiosk_agent:remotes"))

        self.assertEqual(response.status_code, 200)
        remote = response.json()["remotes"][0]
        self.assertEqual(remote["id"], self.device.pk)
        self.assertEqual(remote["device_type"], "ac")
        self.assertEqual(remote["brand"], "gree")
        self.assertEqual(remote["buttons"], [])
        self.assertTrue(remote["ac_state"]["power"])
        self.assertEqual(remote["ac_state"]["temperature"], 21)
        self.assertEqual(remote["ac_state"]["fan"], "high")
        self.assertTrue(remote["ac_state"]["swing_vertical"])

    @patch("kiosk_agent.ac_control.httpx.Client")
    def test_patch_endpoint_returns_confirmed_state(self, client_cls):
        response = type("Response", (), {})()
        response.status_code = 200
        response.json = lambda: confirmed_payload(temperature=21, version=1)
        client_cls.return_value.__enter__.return_value.post.return_value = response

        response = self.client.patch(
            reverse("kiosk_agent:ac-state", args=[self.device.pk]),
            {"temperature": 21, "request_id": "mobile-1"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"]["temperature"], 21)
        self.assertEqual(response.json()["state_version"], 1)


class ACRemoteAdminTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_superuser(
            "ac-admin",
            "ac-admin@example.com",
            "password",
        )
        self.client.force_login(self.user)

    def test_easy_ac_creation_creates_initial_state_and_returns_to_editor(self):
        response = self.client.post(
            reverse("admin:kiosk_agent_remotecontrol_add"),
            {
                "name": "Bedroom AC",
                "slug": "bedroom-ac",
                "location": "Bedroom",
                "device_type": "ac",
                "device_name": "ESP32 IR Controller",
                "brand": "haier",
                "protocol": "haier_ac_yrw02",
                "protocol_model": "default",
                "is_active": "on",
                "guest_visible": "on",
                "sort_order": 0,
                "_save": "Save",
            },
        )

        remote = RemoteControl.objects.get(slug="bedroom-ac")
        self.assertRedirects(
            response,
            reverse("admin:kiosk_agent_remotecontrol_change", args=[remote.pk]),
        )
        self.assertTrue(ACState.objects.filter(device=remote).exists())
        self.assertEqual(remote.protocol, RemoteControl.Protocol.HAIER_AC_YRW02)

    def test_ac_creation_explains_missing_configuration(self):
        response = self.client.post(
            reverse("admin:kiosk_agent_remotecontrol_add"),
            {
                "name": "Incomplete AC",
                "slug": "incomplete-ac",
                "device_type": "ac",
                "device_name": "ESP32 IR Controller",
                "protocol_model": "default",
                "is_active": "on",
                "sort_order": 0,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose the AC brand")
        self.assertContains(response, "Choose the exact AC protocol")
