from enum import StrEnum

from django.core.exceptions import ImproperlyConfigured


class VoiceSource(StrEnum):
    REALTIME = "realtime"
    BACKEND = "backend"
    OFF = "off"


def normalize_voice_source(value: str | None) -> str:
    """Return a canonical voice source or fail fast on unsafe configuration."""
    if value is None:
        return VoiceSource.BACKEND.value
    normalized = value.strip().lower()
    try:
        return VoiceSource(normalized).value
    except ValueError as exc:
        choices = ", ".join(source.value for source in VoiceSource)
        raise ImproperlyConfigured(
            f"VOICE_SOURCE must be one of: {choices}; got {value!r}."
        ) from exc
