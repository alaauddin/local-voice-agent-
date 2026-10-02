"""Compatibility imports for the separated backend voice service."""

from kiosk_agent.voice.service import generate_and_publish_tts
from kiosk_agent.voice.text import clean_spoken_text, split_spoken_text

__all__ = (
    "clean_spoken_text",
    "generate_and_publish_tts",
    "split_spoken_text",
)
