from unittest.mock import AsyncMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from kiosk_agent.voice.config import normalize_voice_source
from kiosk_agent.voice.service import generate_and_publish_tts


class VoiceConfigurationTests(SimpleTestCase):
    def test_voice_source_is_normalized(self):
        self.assertEqual(normalize_voice_source(" Backend "), "backend")

    def test_unset_voice_source_defaults_to_realtime(self):
        self.assertEqual(normalize_voice_source(None), "realtime")

    def test_empty_or_unknown_voice_source_is_rejected(self):
        for value in ("", "browser", "unknown"):
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                normalize_voice_source(value)


class VoiceServiceTests(SimpleTestCase):
    @override_settings(VOICE_SOURCE="off")
    @patch("kiosk_agent.voice.service.voice_skipped", new_callable=AsyncMock)
    async def test_off_mode_emits_terminal_skipped_event(self, skipped):
        await generate_and_publish_tts(
            text="مرحبا", stay_id="stay", request_id="request"
        )

        skipped.assert_awaited_once_with(
            "stay", "request", nonce="request", reason="voice_off"
        )

    @override_settings(VOICE_SOURCE="backend", OPENAI_API_KEY="")
    @patch("kiosk_agent.voice.service.voice_fallback", new_callable=AsyncMock)
    async def test_missing_key_emits_browser_fallback(self, fallback):
        await generate_and_publish_tts(
            text="مرحبا", stay_id="stay", request_id="request"
        )

        fallback.assert_awaited_once_with(
            "stay",
            "request",
            nonce="request",
            text="مرحبا",
            reason="api_key_missing",
        )

    @override_settings(
        VOICE_SOURCE="backend", OPENAI_API_KEY="test", VOICE_TTS_CONCURRENCY=2
    )
    @patch("kiosk_agent.voice.service.voice_completed", new_callable=AsyncMock)
    @patch("kiosk_agent.voice.service.voice_chunk", new_callable=AsyncMock)
    @patch("kiosk_agent.voice.service.voice_status", new_callable=AsyncMock)
    @patch("kiosk_agent.voice.service.synthesize_mp3", new_callable=AsyncMock)
    async def test_backend_mode_has_status_chunks_and_terminal_event(
        self, synthesize, status, chunk, completed
    ):
        synthesize.return_value = "encoded"

        await generate_and_publish_tts(
            text="مرحبا.",
            stay_id="stay",
            request_id="request",
            client=object(),
        )

        status.assert_awaited_once_with(
            "stay", "request", nonce="request", total=1
        )
        chunk.assert_awaited_once_with(
            "stay",
            "request",
            nonce="request",
            seq=0,
            total=1,
            text="مرحبا.",
            audio="encoded",
        )
        completed.assert_awaited_once_with(
            "stay", "request", nonce="request", total=1
        )
