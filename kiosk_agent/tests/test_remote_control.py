from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from kiosk_agent.models import (
    ChaletConfig,
    KioskAuditLog,
    RemoteButton,
    RemoteControl,
    RemoteTemplate,
    RemoteTemplateButton,
)
from kiosk_agent.remote_control import (
    press_remote_button,
    validate_command_url,
    validate_ir_command,
)


SAMPLE_RAW = [8980, 4470, 530, 620, 530, 570, 580]


@override_settings(
    REMOTE_BUTTON_COOLDOWN_SECONDS=0,
    KIOSK_API_KEY="",
)
class RemoteControlTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.config = ChaletConfig.load()
        self.client.get(reverse("kiosk-chat"))
        self.template = RemoteTemplate.objects.create(
            name="Fan",
            slug="fan-test",
            category=RemoteTemplate.Category.FAN,
        )
        RemoteTemplateButton.objects.create(
            template=self.template,
            key="power_on",
            label="Power On",
            icon="power",
            row=0,
            column=0,
            sort_order=0,
        )
        self.remote = RemoteControl.objects.create(
            name="Pool fan",
            slug="pool-fan",
            location="Pool",
            template=self.template,
            template_slug=self.template.slug,
            guest_visible=True,
        )
        self.button = RemoteButton.objects.create(
            remote=self.remote,
            key="power_on",
            label="Power On",
            icon="power",
            row=0,
            column=0,
            sort_order=0,
            command_url="http://192.168.1.102/ir",
            ir_id=1,
            frequency=38,
            raw=SAMPLE_RAW,
        )

    def test_validate_command_url_accepts_any_http_url(self):
        validate_command_url("http://192.168.1.2/api/ir?id-ir=1&hex=000001F2")
        validate_command_url("https://example.com/anything")
        with self.assertRaises(ValidationError):
            validate_command_url("ftp://192.168.1.2/x")
        with self.assertRaises(ValidationError):
            validate_command_url("")

    def test_validate_ir_command_rejects_invalid_timings(self):
        self.assertEqual(
            validate_ir_command(1, 38, SAMPLE_RAW),
            {"id": 1, "frequency": 38, "raw": SAMPLE_RAW},
        )
        with self.assertRaises(ValidationError):
            validate_ir_command(1, 38, [])
        with self.assertRaises(ValidationError):
            validate_ir_command(1, 38, [8980, -1])

    def test_remotes_list_does_not_expose_ir_command(self):
        response = self.client.get(reverse("kiosk_agent:remotes"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        button = payload["remotes"][0]["buttons"][0]
        self.assertTrue(button["configured"])
        self.assertNotIn("command_url", button)
        self.assertNotIn("command_payload", button)
        self.assertNotIn("192.168.1.102", str(payload))
        self.assertNotIn("8980", str(payload))

    @patch("kiosk_agent.remote_control.httpx.Client")
    def test_kiosk_press_posts_stored_command_from_backend(self, client_cls):
        controller_response = type("Resp", (), {})()
        controller_response.status_code = 200
        controller_response.json = lambda: {
            "status": "success",
            "target": "ESP01_01",
            "httpCode": 200,
        }
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = controller_response

        response = self.client.post(
            reverse("kiosk_agent:remote-button-press", args=[self.button.pk]),
            {
                "command_url": "http://attacker.invalid/ir",
                "id": 999,
                "frequency": 1,
                "raw": [1],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["execution"], "server")
        self.assertFalse(client_cls.call_args.kwargs.get("follow_redirects", True))
        client.post.assert_called_once_with(
            "http://192.168.1.102/ir",
            json={"id": 1, "frequency": 38, "raw": SAMPLE_RAW},
        )
        self.assertTrue(
            KioskAuditLog.objects.filter(event=KioskAuditLog.Event.REMOTE_PRESSED).exists()
        )
        audit = KioskAuditLog.objects.get(event=KioskAuditLog.Event.REMOTE_PRESSED)
        self.assertEqual(audit.details.get("execution"), "server")
        self.assertNotIn("8980", str(audit.details))

    def test_press_unconfigured_button(self):
        self.button.command_url = ""
        self.button.save(update_fields=["command_url"])
        response = self.client.post(
            reverse("kiosk_agent:remote-button-press", args=[self.button.pk]),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "unconfigured")

    def test_copy_from_template_creates_blank_urls(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_superuser("admin", "a@b.c", "pass")
        self.client.force_login(user)
        response = self.client.post(
            reverse("admin:kiosk_agent_remotecontrol_add_from_template"),
            {
                "template": self.template.pk,
                "name": "Living fan",
                "slug": "living-fan",
                "location": "Living",
                "guest_visible": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        remote = RemoteControl.objects.get(slug="living-fan")
        button = remote.buttons.get()
        self.assertEqual(button.label, "Power On")
        self.assertEqual(button.command_url, "")
        self.assertEqual(button.raw, [])

    def test_seeded_templates_exist(self):
        self.assertTrue(RemoteTemplate.objects.filter(slug="fan").exists())
        self.assertTrue(RemoteTemplate.objects.filter(slug="ac").exists())
        self.assertTrue(RemoteTemplate.objects.filter(slug="lights").exists())

    @patch("kiosk_agent.remote_control.httpx.Client")
    def test_admin_helper_still_server_side(self, client_cls):
        response = type("Resp", (), {})()
        response.status_code = 200
        response.json = lambda: {"status": "success"}
        client_cls.return_value.__enter__.return_value.post.return_value = response
        press_remote_button(self.button.pk, source="admin")
        client_cls.assert_called_once()
