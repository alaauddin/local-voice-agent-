from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from kiosk_agent.views import (
    InternalACStateSyncView,
    KioskPageView,
    button_capture_start_view,
    button_capture_status_view,
    button_config_ac_test_view,
    button_config_data_view,
    button_config_save_view,
    button_config_sync_ip_view,
    button_config_view,
)

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="kiosk-chat", permanent=False)),
    path("chat/", KioskPageView.as_view(), name="kiosk-chat"),
    path("button-config/", button_config_view, name="button-config"),
    path(
        "button-config/remotes/<int:remote_id>/",
        button_config_data_view,
        name="button-config-data",
    ),
    path(
        "button-config/remotes/<int:remote_id>/save/",
        button_config_save_view,
        name="button-config-save",
    ),
    path(
        "button-config/remotes/<int:remote_id>/capture/start/",
        button_capture_start_view,
        name="button-capture-start",
    ),
    path(
        "button-config/remotes/<int:remote_id>/capture/",
        button_capture_status_view,
        name="button-capture-status",
    ),
    path(
        "button-config/remotes/<int:remote_id>/sync-ip/",
        button_config_sync_ip_view,
        name="button-config-sync-ip",
    ),
    path(
        "button-config/remotes/<int:remote_id>/ac/test/",
        button_config_ac_test_view,
        name="button-config-ac-test",
    ),
    path("favicon.ico", RedirectView.as_view(url="/static/kiosk_agent/videos/poster.svg", permanent=True)),
    path("admin/", admin.site.urls),
    path("api/internal/ac-state-sync/", InternalACStateSyncView.as_view(), name="ac-state-sync"),
    path("api/v1/kiosk/", include("kiosk_agent.urls")),
]
