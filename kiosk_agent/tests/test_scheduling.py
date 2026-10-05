from django.conf import settings
from django.test import SimpleTestCase


class RemoteIpSyncScheduleTests(SimpleTestCase):
    def test_remote_ip_sync_is_scheduled(self):
        entry = settings.CELERY_BEAT_SCHEDULE["sync-remote-control-ips"]

        self.assertEqual(entry["task"], "kiosk_agent.sync_remote_ips")
        self.assertEqual(entry["schedule"], settings.REMOTE_IP_SYNC_INTERVAL_SECONDS)
        self.assertGreaterEqual(entry["schedule"], 10)
