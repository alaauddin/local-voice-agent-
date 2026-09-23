import uuid
from unittest.mock import AsyncMock, patch

from celery.exceptions import Retry
from django.test import TestCase, override_settings

from kiosk_agent.models import ChaletConfig, KioskMessage
from kiosk_agent.tasks import run_concierge_task

IN_MEMORY_CHANNELS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


@override_settings(CHANNEL_LAYERS=IN_MEMORY_CHANNELS)
class ConciergeTaskTests(TestCase):
    def test_missing_request_is_retried_instead_of_silently_ignored(self):
        with patch.object(run_concierge_task, "retry", side_effect=Retry()) as retry:
            with self.assertRaises(Retry):
                run_concierge_task.run(str(uuid.uuid4()), str(uuid.uuid4()))

        retry.assert_called_once_with(countdown=1)

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
