import secrets

from django.conf import settings
from rest_framework.permissions import BasePermission


class OptionalKioskKeyPermission(BasePermission):
    """Require X-Kiosk-Key only when KIOSK_API_KEY is configured."""

    def has_permission(self, request, view):
        expected = settings.KIOSK_API_KEY
        return not expected or secrets.compare_digest(request.headers.get("X-Kiosk-Key", ""), expected)
