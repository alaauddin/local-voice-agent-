import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wazen_local.settings")

app = Celery("wazen_local")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
