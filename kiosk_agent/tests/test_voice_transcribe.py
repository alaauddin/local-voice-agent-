from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from kiosk_agent.permissions import KIOSK_COOKIE_NAME, create_kiosk_cookie
from kiosk_agent.views import VoiceTranscribeView
from kiosk_agent.voice.transcribe import TranscribeError


def _request(data=None, fmt="multipart"):
    factory = APIRequestFactory()
    request = factory.post("/api/v1/kiosk/voice/transcribe/", data or {}, format=fmt)
    request.COOKIES[KIOSK_COOKIE_NAME] = create_kiosk_cookie()
    return request


def _audio_file(content=b"fake-opus-bytes", name="ptt.webm"):
    return SimpleUploadedFile(name, content, content_type="audio/webm")


class VoiceTranscribeViewTests(SimpleTestCase):
    def test_missing_audio_returns_400(self):
        response = VoiceTranscribeView.as_view()(_request())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "audio_missing")

    @patch("kiosk_agent.views.transcribe_audio", return_value="مرحبا")
    def test_success_returns_transcript(self, transcribe):
        response = VoiceTranscribeView.as_view()(
            _request({"audio": _audio_file()})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"transcript": "مرحبا"})
        transcribe.assert_called_once()

    @patch(
        "kiosk_agent.views.transcribe_audio",
        side_effect=TranscribeError(
            "provider_error", "Unable to transcribe.", retryable=True
        ),
    )
    def test_retryable_provider_error_returns_502(self, transcribe):
        response = VoiceTranscribeView.as_view()(
            _request({"audio": _audio_file()})
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data["error"], "provider_error")

    @patch(
        "kiosk_agent.views.transcribe_audio",
        side_effect=TranscribeError("api_key_missing", "Not configured."),
    )
    def test_configuration_error_returns_400(self, transcribe):
        response = VoiceTranscribeView.as_view()(
            _request({"audio": _audio_file()})
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "api_key_missing")

    def test_oversized_audio_rejected_by_size_guard(self):
        with (
            patch("kiosk_agent.views.MAX_AUDIO_BYTES", 10),
            patch("kiosk_agent.views.transcribe_audio") as transcribe,
        ):
            response = VoiceTranscribeView.as_view()(
                _request({"audio": _audio_file(content=b"x" * 1024)})
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.data["error"], "audio_too_large")
        transcribe.assert_not_called()
