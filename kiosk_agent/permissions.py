import secrets
from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from rest_framework.permissions import BasePermission

KIOSK_COOKIE_NAME = "wazen_kiosk_session"
KIOSK_COOKIE_SALT = "wazen-local-kiosk"


def create_kiosk_cookie() -> str:
    return signing.dumps({"scope": "kiosk"}, salt=KIOSK_COOKIE_SALT, compress=True)


def valid_kiosk_cookie(value: str) -> bool:
    if not value:
        return False
    try:
        payload = signing.loads(
            value,
            salt=KIOSK_COOKIE_SALT,
            max_age=settings.KIOSK_SESSION_MAX_AGE,
        )
    except signing.BadSignature:
        return False
    return payload == {"scope": "kiosk"}


class OptionalKioskKeyPermission(BasePermission):
    """Accept a local signed kiosk session or the optional provisioning key."""

    def has_permission(self, request, view):
        expected = settings.KIOSK_API_KEY
        supplied = request.headers.get("X-Kiosk-Key", "")
        if expected and supplied and secrets.compare_digest(supplied, expected):
            return True
        if request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"}:
            origin = request.headers.get("Origin") or request.headers.get("Referer")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme != request.scheme or parsed.netloc != request.get_host():
                    return False
        return valid_kiosk_cookie(request.COOKIES.get(KIOSK_COOKIE_NAME, ""))
