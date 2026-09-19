from django.urls import path

from .views import (
    ChatView,
    HealthView,
    MemoryView,
    RealtimeMessageView,
    RealtimeSessionCloseView,
    RealtimeSessionView,
    RealtimeToolView,
    RemoteButtonPressView,
    RemotesListView,
    ResetView,
    StatusView,
)

app_name = "kiosk_agent"

urlpatterns = [
    path("chat/", ChatView.as_view(), name="chat"),
    path("messages/", MemoryView.as_view(), name="messages"),
    path("realtime/session/", RealtimeSessionView.as_view(), name="realtime-session"),
    path(
        "realtime/session/close/",
        RealtimeSessionCloseView.as_view(),
        name="realtime-session-close",
    ),
    path("realtime/messages/", RealtimeMessageView.as_view(), name="realtime-message"),
    path("realtime/tools/", RealtimeToolView.as_view(), name="realtime-tool"),
    path("remotes/", RemotesListView.as_view(), name="remotes"),
    path(
        "remote-buttons/<int:button_id>/press/",
        RemoteButtonPressView.as_view(),
        name="remote-button-press",
    ),
    path("reset/", ResetView.as_view(), name="reset"),
    path("health/", HealthView.as_view(), name="health"),
    path("status/", StatusView.as_view(), name="status"),
]
