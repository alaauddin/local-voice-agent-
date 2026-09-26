import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from kiosk_agent.models import ACState, RemoteButton, RemoteControl
from kiosk_agent.serializers import RemoteControlPublicSerializer


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class ButtonConfigTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="layout-editor",
            password="test-password",
            is_staff=True,
        )
        self.remote = RemoteControl.objects.create(name="Test fan", slug="test-fan")
        self.power = RemoteButton.objects.create(
            remote=self.remote,
            key="power_on",
            label="Power",
            icon="power",
            row=0,
            column=0,
            sort_order=0,
        )
        self.speed = RemoteButton.objects.create(
            remote=self.remote,
            key="speed_up",
            label="Speed",
            icon="plus",
            row=0,
            column=1,
            sort_order=1,
        )

    def button_payload(self, button, **changes):
        data = {
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
        }
        data.update(changes)
        return data

    def test_page_requires_staff_login(self):
        response = self.client.get(reverse("button-config"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

        self.client.force_login(self.staff)
        response = self.client.get(reverse("button-config"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ترتيب وتهيئة الأزرار")

    def test_staff_can_reorder_and_edit_buttons(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("button-config-save", args=[self.remote.pk]),
            data=json.dumps(
                {
                    "buttons": [
                        self.button_payload(
                            self.speed,
                            label="Fast",
                            row=0,
                            column=0,
                            sort_order=0,
                        ),
                        self.button_payload(
                            self.power,
                            row=0,
                            column=1,
                            sort_order=1,
                        ),
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.speed.refresh_from_db()
        self.power.refresh_from_db()
        self.assertEqual((self.speed.label, self.speed.row, self.speed.column), ("Fast", 0, 0))
        self.assertEqual((self.power.row, self.power.column), (0, 1))

    def test_duplicate_position_is_rejected_without_partial_update(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("button-config-save", args=[self.remote.pk]),
            data=json.dumps(
                {
                    "buttons": [
                        self.button_payload(self.power, label="Changed", row=0, column=0),
                        self.button_payload(self.speed, row=0, column=0),
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.power.refresh_from_db()
        self.assertEqual(self.power.label, "Power")

    @patch("kiosk_agent.ir_capture.httpx.Client")
    def test_staff_can_start_ir_capture(self, client_cls):
        self.remote.device_ip = "192.168.1.50"
        self.remote.save(update_fields=("device_ip", "updated_at"))
        controller_response = client_cls.return_value.__enter__.return_value.request.return_value
        controller_response.status_code = 200
        controller_response.json.return_value = {
            "success": True,
            "capturing": True,
            "frequency": 38,
            "timeout_ms": 15000,
        }
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("button-capture-start", args=[self.remote.pk]),
            data=json.dumps({"frequency": 38}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["capturing"])
        controller_response = client_cls.return_value.__enter__.return_value.request
        controller_response.assert_called_once_with(
            "POST",
            "http://192.168.1.50/api/ir/capture/start",
            json={"frequency": 38},
        )

    @patch("kiosk_agent.ir_capture.httpx.Client")
    def test_staff_can_read_captured_ir_signal(self, client_cls):
        self.remote.device_ip = "192.168.1.50"
        self.remote.save(update_fields=("device_ip", "updated_at"))
        controller_response = client_cls.return_value.__enter__.return_value.request.return_value
        controller_response.status_code = 200
        controller_response.json.return_value = {
            "success": True,
            "capturing": False,
            "ready": True,
            "revision": 2,
            "frequency": 38,
            "protocol": "NEC",
            "raw": [9000, 4500, 560, 560],
        }
        self.client.force_login(self.staff)

        response = self.client.get(reverse("button-capture-status", args=[self.remote.pk]))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["raw"], [9000, 4500, 560, 560])
        self.assertEqual(response.json()["protocol"], "NEC")

    def test_capture_requires_a_synced_device_ip(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("button-capture-start", args=[self.remote.pk]),
            data=json.dumps({"frequency": 38}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "device_unavailable")

    def test_staff_can_save_a_manual_button_action(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("button-config-save", args=[self.remote.pk]),
            data=json.dumps(
                {
                    "buttons": [
                        self.button_payload(self.power, key="custom_swing"),
                        self.button_payload(self.speed),
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.power.refresh_from_db()
        self.assertEqual(self.power.key, "custom_swing")

    def test_invalid_manual_button_action_is_rejected(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("button-config-save", args=[self.remote.pk]),
            data=json.dumps(
                {
                    "buttons": [
                        self.button_payload(self.power, key="not valid!"),
                        self.button_payload(self.speed),
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_staff_can_hide_remote_from_guest_screen(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("button-config-save", args=[self.remote.pk]),
            data=json.dumps(
                {
                    "remote": {
                        "device_name": "",
                        "is_active": True,
                        "guest_visible": False,
                        "voice_enabled": False,
                    },
                    "buttons": [
                        self.button_payload(self.power),
                        self.button_payload(self.speed),
                    ],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.remote.refresh_from_db()
        self.assertTrue(self.remote.is_active)
        self.assertFalse(self.remote.guest_visible)

    @patch("kiosk_agent.views.discover_identity_devices")
    def test_staff_can_save_device_name_and_sync_ip(self, discover):
        discover.return_value = [
            {
                "name": "Bedroom ESP32",
                "ip": "192.168.1.77",
                "firmware_version": "1.3.0",
                "capabilities": ["ir_receive", "ir_capture_api"],
            }
        ]
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("button-config-sync-ip", args=[self.remote.pk]),
            data=json.dumps({"device_name": "Bedroom ESP32"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["device_ip"], "192.168.1.77")
        self.remote.refresh_from_db()
        self.assertEqual(self.remote.device_name, "Bedroom ESP32")
        self.assertEqual(str(self.remote.device_ip), "192.168.1.77")
        self.power.refresh_from_db()
        self.speed.refresh_from_db()
        self.assertEqual(self.power.command_url, "http://192.168.1.77/ir")
        self.assertEqual(self.speed.command_url, "http://192.168.1.77/ir")
        self.assertEqual(response.json()["updated_buttons"], 2)

    def test_ac_remote_has_protocol_capabilities_and_can_save_without_raw_buttons(self):
        ac_remote = RemoteControl.objects.create(
            name="Bedroom AC",
            slug="bedroom-ac",
            device_type=RemoteControl.DeviceType.AC,
            device_name="Bedroom AC ESP32",
        )
        self.client.force_login(self.staff)

        data_response = self.client.get(reverse("button-config-data", args=[ac_remote.pk]))
        self.assertEqual(data_response.status_code, 200)
        data = data_response.json()
        self.assertEqual(data["remote"]["device_type"], "ac")
        self.assertTrue(any(item["value"] == "gree" for item in data["ac"]["protocols"]))
        gree = next(item for item in data["ac"]["protocols"] if item["value"] == "gree")
        self.assertTrue(gree["capabilities"]["turbo"])
        self.assertEqual(
            [model["value"] for model in gree["models"]],
            ["yaw1f", "ybofb", "yx1fsf"],
        )

        save_response = self.client.post(
            reverse("button-config-save", args=[ac_remote.pk]),
            data=json.dumps(
                {
                    "remote": {
                        "device_name": "Bedroom AC ESP32",
                        "is_active": True,
                        "guest_visible": True,
                        "voice_enabled": False,
                        "protocol": "gree",
                        "protocol_model": "ybofb",
                        "ac_control_visibility": {"power": False, "temperature": True},
                    },
                    "buttons": [],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(save_response.status_code, 200, save_response.content)
        ac_remote.refresh_from_db()
        self.assertEqual(ac_remote.protocol, RemoteControl.Protocol.GREE)
        self.assertEqual(ac_remote.brand, RemoteControl.Brand.GREE)
        self.assertEqual(ac_remote.protocol_model, RemoteControl.ProtocolModel.GREE_YBOFB)
        self.assertFalse(ac_remote.ac_control_visibility["power"])
        public_data = RemoteControlPublicSerializer(ac_remote).data
        self.assertFalse(public_data["ac_capabilities"]["power"])
        self.assertTrue(public_data["ac_capabilities"]["temperature"])

    def test_ac_remote_rejects_model_from_another_protocol(self):
        ac_remote = RemoteControl.objects.create(
            name="Invalid model AC",
            slug="invalid-model-ac",
            device_type=RemoteControl.DeviceType.AC,
            device_name="Invalid Model ESP32",
        )
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("button-config-save", args=[ac_remote.pk]),
            data=json.dumps(
                {
                    "remote": {
                        "device_name": "Invalid Model ESP32",
                        "is_active": True,
                        "guest_visible": True,
                        "voice_enabled": False,
                        "protocol": "gree",
                        "protocol_model": "v9014557_b",
                        "ac_control_visibility": {},
                    },
                    "buttons": [],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("model", response.json()["detail"].lower())

    @patch("kiosk_agent.views.set_ac_state")
    def test_staff_can_send_ac_test_state(self, set_state):
        ac_remote = RemoteControl.objects.create(
            name="Lounge AC",
            slug="lounge-ac",
            device_type=RemoteControl.DeviceType.AC,
            device_name="Lounge ESP32",
            device_ip="192.168.1.90",
            protocol=RemoteControl.Protocol.GREE,
            brand=RemoteControl.Brand.GREE,
            protocol_model=RemoteControl.ProtocolModel.DEFAULT,
        )
        confirmed = ACState.objects.create(device=ac_remote, power=True, temperature=22, state_version=4)
        set_state.return_value = confirmed
        self.client.force_login(self.staff)
        requested = {
            "power": True,
            "mode": "cool",
            "temperature": 22,
            "fan": "high",
            "turbo": True,
        }

        response = self.client.post(
            reverse("button-config-ac-test", args=[ac_remote.pk]),
            data=json.dumps({"state": requested}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["state_version"], 4)
        set_state.assert_called_once_with(ac_remote.pk, requested)
