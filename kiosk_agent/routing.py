from django.urls import path

from .consumers import KioskConsumer

websocket_urlpatterns = [path("ws/kiosk/", KioskConsumer.as_asgi(), name="kiosk-websocket")]
