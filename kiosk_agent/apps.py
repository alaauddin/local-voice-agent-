from django.apps import AppConfig


class KioskAgentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "kiosk_agent"
    verbose_name = "Chalet Kiosk Agent"

    def ready(self):
        from . import db  # noqa: F401
