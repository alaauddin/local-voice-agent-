from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from kiosk_agent.ac_control import (
    ACControlError,
    accept_esp32_state_sync,
    protocol_models,
    set_ac_state,
)
from kiosk_agent.models import ACState, RemoteControl


def confirmed_payload(*, temperature=22, version=1, model="default"):
    return {
        "success": True,
        "source": "esp32",
        "brand": "gree",
        "protocol": "gree",
        "model": model,
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

    def test_all_firmware_model_variants_are_exposed_by_protocol(self):
        self.assertEqual(protocol_models("gree"), ("yaw1f", "ybofb", "yx1fsf"))
        for protocol in ("haier_ac_yrw02", "haier_ac176"):
            self.assertEqual(protocol_models(protocol), ("v9014557_a", "v9014557_b"))
        self.assertEqual(protocol_models("haier_ac"), ("default",))
        self.assertEqual(protocol_models("haier_ac160"), ("default",))
        self.assertEqual(protocol_models("midea"), ("default",))
        self.assertEqual(protocol_models("kelon168"), ("dg11r2-01",))

    def test_cross_protocol_model_is_rejected_before_transmission(self):
        self.device.protocol_model = RemoteControl.ProtocolModel.HAIER_V9014557_B
        self.device.save(update_fields=("protocol_model", "updated_at"))
        with self.assertRaisesMessage(ACControlError, "not supported by this AC protocol"):
            set_ac_state(self.device.pk, {"power": True})

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
        self.assertNotIn("quiet", sent)
        self.assertNotIn("swing_vertical", sent)

    @patch("kiosk_agent.ac_control.httpx.Client")
    def test_version_conflict_fetches_current_state_and_retries_once(self, client_cls):
        conflict = type("Response", (), {})()
        conflict.status_code = 409
        conflict.json = lambda: {
            "success": False,
            "message": "state_version is older than the ESP32 state",
        }
        
        current = type("Response", (), {})()
        current.status_code = 200
        current_payload = confirmed_payload(temperature=19, version=7)
        current_payload.pop("success")
        current.json = lambda: current_payload
        retried = type("Response", (), {})()
        retried.status_code = 200
        retried.json = lambda: confirmed_payload(temperature=22, version=8)
        client = client_cls.return_value.__enter__.return_value
        client.post.side_effect = (conflict, retried)
        client.get.return_value = current

        state = set_ac_state(self.device.pk, {"temperature": 22}, request_id="req-retry")

        self.assertEqual(state.temperature, 22)
        self.assertEqual(state.state_version, 8)
        self.assertEqual(client.post.call_count, 2)
        client.get.assert_called_once_with("http://192.168.1.50/api/ac/state")
        first_payload = client.post.call_args_list[0].kwargs["json"]
        retry_payload = client.post.call_args_list[1].kwargs["json"]
        self.assertEqual(first_payload["state_version"], 1)
        self.assertEqual(retry_payload["state_version"], 8)
        self.assertEqual(retry_payload["temperature"], 22)
        self.assertEqual(retry_payload["request_id"], "req-retry")

    def test_unsupported_field_is_rejected_before_contacting_esp32(self):
        with self.assertRaisesMessage(
            ACControlError,
            "quiet is not supported by the selected protocol",
        ):
            set_ac_state(self.device.pk, {"quiet": True})

    @patch("kiosk_agent.ac_control.httpx.Client")
    def test_selected_gree_model_variant_is_sent_and_verified(self, client_cls):
        self.device.protocol_model = RemoteControl.ProtocolModel.GREE_YX1FSF
        self.device.save(update_fields=("protocol_model", "updated_at"))
        response = type("Response", (), {})()
        response.status_code = 200
        response.json = lambda: confirmed_payload(model="yx1fsf")
        client_cls.return_value.__enter__.return_value.post.return_value = response

        set_ac_state(self.device.pk, {"power": True})

        sent = client_cls.return_value.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(sent["model"], "yx1fsf")

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

    @patch("kiosk_agent.ac_control.httpx.Client")
    def test_old_firmware_endpoint_error_is_explained(self, client_cls):
        response = type("Response", (), {})()
        response.status_code = 404
        response.json = lambda: {"status": "error", "message": "endpoint not found"}
        client_cls.return_value.__enter__.return_value.post.return_value = response

        with self.assertRaisesMessage(
            ACControlError,
            "This ESP32 is running firmware without AC control",
        ):
            set_ac_state(self.device.pk, {"power": True})

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
        self.assertFalse(remote["ac_capabilities"]["quiet"])
        self.assertTrue(remote["ac_capabilities"]["turbo"])
        self.assertEqual(remote["ac_capabilities"]["temperature_max"], 30)

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
                "protocol": "haier_ac_yrw02",
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
        self.assertEqual(remote.brand, RemoteControl.Brand.HAIER)
        self.assertEqual(remote.protocol, RemoteControl.Protocol.HAIER_AC_YRW02)
        self.assertEqual(
            remote.protocol_model,
            RemoteControl.ProtocolModel.HAIER_V9014557_A,
        )

    def test_ac_creation_explains_missing_configuration(self):
        response = self.client.post(
            reverse("admin:kiosk_agent_remotecontrol_add"),
            {
                "name": "Incomplete AC",
                "slug": "incomplete-ac",
                "device_type": "ac",
                "device_name": "ESP32 IR Controller",
                "is_active": "on",
                "sort_order": 0,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose the exact AC protocol")

    @patch("kiosk_agent.admin.discover_identity_devices")
    def test_ac_ip_sync_rejects_firmware_without_ac_control(self, discover):
        remote = RemoteControl.objects.create(
            name="Old firmware AC",
            slug="old-firmware-ac",
            device_name="ESP32 IR Controller",
            device_ip="10.173.92.23",
            device_type=RemoteControl.DeviceType.AC,
            brand=RemoteControl.Brand.GREE,
            protocol=RemoteControl.Protocol.GREE,
            protocol_model=RemoteControl.ProtocolModel.DEFAULT,
        )
        discover.return_value = [{
            "name": "ESP32 IR Controller",
            "type": "esp32",
            "ip": "10.173.92.23",
            "firmware_version": "1.0.0",
            "capabilities": ["ir_receive", "ir_transmit", "http_api"],
        }]

        response = self.client.post(
            reverse("admin:kiosk_agent_remotecontrol_changelist"),
            {"action": "sync_device_ips", "_selected_action": [remote.pk]},
        )

        self.assertEqual(response.status_code, 302)
        remote.refresh_from_db()
        self.assertIsNone(remote.device_ip)

    @patch("kiosk_agent.admin.discover_identity_devices")
    def test_ac_ip_sync_accepts_ac_capable_firmware(self, discover):
        remote = RemoteControl.objects.create(
            name="Current firmware AC",
            slug="current-firmware-ac",
            device_name="ESP32 IR Controller",
            device_type=RemoteControl.DeviceType.AC,
            brand=RemoteControl.Brand.GREE,
            protocol=RemoteControl.Protocol.GREE,
            protocol_model=RemoteControl.ProtocolModel.DEFAULT,
        )
        discover.return_value = [{
            "name": "ESP32 IR Controller",
            "type": "esp32",
            "ip": "10.173.92.23",
            "firmware_version": "1.2.0",
            "capabilities": ["ir_receive", "ir_transmit", "http_api", "ac_control"],
        }]

        response = self.client.post(
            reverse("admin:kiosk_agent_remotecontrol_changelist"),
            {"action": "sync_device_ips", "_selected_action": [remote.pk]},
        )

        self.assertEqual(response.status_code, 302)
        remote.refresh_from_db()
        self.assertEqual(str(remote.device_ip), "10.173.92.23")
