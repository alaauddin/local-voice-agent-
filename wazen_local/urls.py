from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from kiosk_agent.views import KioskPageView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="kiosk-chat", permanent=False)),
    path("chat/", KioskPageView.as_view(), name="kiosk-chat"),
    path("admin/", admin.site.urls),
    path("api/v1/kiosk/", include("kiosk_agent.urls")),
]
