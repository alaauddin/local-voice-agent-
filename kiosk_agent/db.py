from django.conf import settings
from django.db.backends.signals import connection_created
from django.dispatch import receiver


@receiver(connection_created)
def configure_sqlite(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute(f"PRAGMA busy_timeout={settings.KIOSK_SQLITE_BUSY_TIMEOUT_MS}")
        if connection.settings_dict["NAME"] != ":memory:":
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
