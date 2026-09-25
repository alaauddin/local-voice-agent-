from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from kiosk_agent.views import InternalACStateSyncView, KioskPageView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="kiosk-chat", permanent=False)),
    path("chat/", KioskPageView.as_view(), name="kiosk-chat"),
    path("favicon.ico", RedirectView.as_view(url="/static/kiosk_agent/videos/poster.svg", permanent=True)),
    path("admin/", admin.site.urls),
    path("api/internal/ac-state-sync/", InternalACStateSyncView.as_view(), name="ac-state-sync"),
    path("api/v1/kiosk/", include("kiosk_agent.urls")),
]
