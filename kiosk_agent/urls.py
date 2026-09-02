from django.urls import path

from .views import (
    ChatView,
    HealthView,
    MemoryView,
    RealtimeMessageView,
    RealtimeSessionView,
    RealtimeToolView,
    ResetView,
)

app_name = "kiosk_agent"

urlpatterns = [
    path("chat/", ChatView.as_view(), name="chat"),
    path("messages/", MemoryView.as_view(), name="messages"),
    path("realtime/session/", RealtimeSessionView.as_view(), name="realtime-session"),
    path("realtime/messages/", RealtimeMessageView.as_view(), name="realtime-message"),
    path("realtime/tools/", RealtimeToolView.as_view(), name="realtime-tool"),
    path("reset/", ResetView.as_view(), name="reset"),
    path("health/", HealthView.as_view(), name="health"),
]
