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
from kiosk_agent.remote_control import press_remote_button, validate_command_url


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
            command_url="http://192.168.1.2/api/ir?id-ir=1&hex=000001F2",
        )

    def test_validate_command_url_accepts_any_http_url(self):
        validate_command_url("http://192.168.1.2/api/ir?id-ir=1&hex=000001F2")
        validate_command_url("https://example.com/anything")
        validate_command_url("http://192.168.1.8/api/send?id=ESP01_01&code=1")
        with self.assertRaises(ValidationError):
            validate_command_url("ftp://192.168.1.2/x")
        with self.assertRaises(ValidationError):
            validate_command_url("not-a-url")
        with self.assertRaises(ValidationError):
            validate_command_url("")

    def test_remotes_list_hides_urls(self):
        response = self.client.get(reverse("kiosk_agent:remotes"))
        self.assertEqual(response.status_code, 200)
        remotes = response.json()["remotes"]
        self.assertEqual(len(remotes), 1)
        button = remotes[0]["buttons"][0]
        self.assertTrue(button["configured"])
        self.assertNotIn("command_url", button)
        self.assertNotIn("85649F80", str(response.json()))

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

    @patch("kiosk_agent.remote_control.httpx.Client")
    def test_press_success_parses_controller_payload(self, client_cls):
        response = type("Resp", (), {})()
        response.status_code = 200
        response.json = lambda: {
            "status": "success",
            "target": "ESP01_01",
            "ip": "192.168.1.9",
            "httpCode": 200,
            "response": '{"status":"success","id":"ESP01_01","code":"85649F80"}',
        }
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value = response

        api = self.client.post(
            reverse("kiosk_agent:remote-button-press", args=[self.button.pk]),
            {},
            format="json",
        )
        self.assertEqual(api.status_code, 200)
        self.assertTrue(api.json()["ok"])
        self.assertEqual(api.json()["target"], "ESP01_01")
        client.get.assert_called_once()
        called_url = client.get.call_args.args[0]
        self.assertTrue(called_url.startswith("http://192.168.1.2/api/ir"))
        self.assertTrue(
            KioskAuditLog.objects.filter(event=KioskAuditLog.Event.REMOTE_PRESSED).exists()
        )
        audit = KioskAuditLog.objects.get(event=KioskAuditLog.Event.REMOTE_PRESSED)
        self.assertNotIn("85649F80", str(audit.details))
        self.assertNotIn("command_url", audit.details)

    @patch("kiosk_agent.remote_control.httpx.Client")
    def test_press_does_not_follow_redirects(self, client_cls):
        response = type("Resp", (), {})()
        response.status_code = 200
        response.json = lambda: {"status": "success", "httpCode": 200}
        client_cls.return_value.__enter__.return_value.get.return_value = response
        press_remote_button(self.button.pk, source="admin")
        kwargs = client_cls.call_args.kwargs
        self.assertFalse(kwargs.get("follow_redirects", True))

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

    def test_seeded_templates_exist(self):
        self.assertTrue(RemoteTemplate.objects.filter(slug="fan").exists())
        self.assertTrue(RemoteTemplate.objects.filter(slug="ac").exists())
        self.assertTrue(RemoteTemplate.objects.filter(slug="lights").exists())
