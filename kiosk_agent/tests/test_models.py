from django.core.exceptions import ValidationError
from django.test import TestCase

from kiosk_agent.models import ChaletConfig


class ChaletConfigTests(TestCase):
    def test_load_creates_singleton(self):
        first = ChaletConfig.load()
        second = ChaletConfig.load()
        self.assertEqual(first.pk, 1)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ChaletConfig.objects.count(), 1)

    def test_forces_singleton_primary_key(self):
        config = ChaletConfig(chalet_name="Test")
        config.pk = 2
        with self.assertRaises(ValidationError):
            config.full_clean()

    def test_rotate_stay_changes_identifier(self):
        config = ChaletConfig.load()
        old_stay = config.current_stay_id
        config.rotate_stay()
        self.assertNotEqual(old_stay, config.current_stay_id)
