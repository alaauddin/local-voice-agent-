import uuid
from unittest.mock import AsyncMock, patch

from django.test import TestCase, override_settings

from kiosk_agent.models import ChaletConfig, KioskMessage
from kiosk_agent.tasks import run_concierge_task

IN_MEMORY_CHANNELS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


@override_settings(CHANNEL_LAYERS=IN_MEMORY_CHANNELS)
class ConciergeTaskTests(TestCase):
    @patch("kiosk_agent.tasks.publish", new_callable=AsyncMock)
    @patch("kiosk_agent.tasks.run_agent", new_callable=AsyncMock)
    def test_agent_failure_marks_streaming_request_failed(self, run_agent, publish):
        run_agent.side_effect = RuntimeError("upstream failed")
        config = ChaletConfig.load()
        request_id = uuid.uuid4()
        message = KioskMessage.objects.create(
            stay_id=config.current_stay_id,
            request_id=request_id,
            role=KioskMessage.Role.USER,
            content="test",
            status=KioskMessage.Status.QUEUED,
        )

        with self.assertRaises(RuntimeError):
            run_concierge_task.run(str(config.current_stay_id), str(request_id))

        message.refresh_from_db()
        self.assertEqual(message.status, KioskMessage.Status.FAILED)
        publish.assert_awaited_once()
