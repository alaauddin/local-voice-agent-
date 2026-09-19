import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-development-only-key")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [x.strip() for x in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if x.strip()]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    "kiosk_agent",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "wazen_local.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "wazen_local.wsgi.application"
ASGI_APPLICATION = "wazen_local.asgi.application"

SQLITE_PATH = Path(os.getenv("SQLITE_PATH", BASE_DIR / "db.sqlite3"))
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": SQLITE_PATH,
        "OPTIONS": {"timeout": 30},
    }
}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "ar"
TIME_ZONE = os.getenv("TZ", "Asia/Aden")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
WHITENOISE_MAX_AGE = 31536000
WHITENOISE_MANIFEST_STRICT = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL], "capacity": 1500, "expiry": 60},
    }
}
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 120
CELERY_TASK_SOFT_TIME_LIMIT = 105
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_IGNORE_RESULT = True
KIOSK_STALE_REQUEST_SECONDS = int(os.getenv("KIOSK_STALE_REQUEST_SECONDS", "180"))
KIOSK_SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("KIOSK_SQLITE_BUSY_TIMEOUT_MS", "30000"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
KIOSK_API_KEY = os.getenv("KIOSK_API_KEY", "")
KIOSK_SESSION_MAX_AGE = int(os.getenv("KIOSK_SESSION_MAX_AGE", "86400"))
VOICE_SOURCE = os.getenv("VOICE_SOURCE", "realtime")
VOICE_MODEL = os.getenv("VOICE_MODEL", "gpt-4o-mini-tts")
VOICE_NAME = os.getenv("VOICE_NAME", "coral")
VOICE_SPEED = float(os.getenv("VOICE_SPEED", "1.15"))
VOICE_WAKE_WORD = os.getenv("VOICE_WAKE_WORD", "يا غروب")
VOICE_ACTIVATION_MODE = os.getenv("VOICE_ACTIVATION_MODE", "wake").lower()
if VOICE_ACTIVATION_MODE not in {"wake", "always_on", "button"}:
    VOICE_ACTIVATION_MODE = "wake"
VOICE_INSTRUCTIONS = os.getenv(
    "VOICE_INSTRUCTIONS",
    "Speak warmly and naturally in Arabic only. Never use English words or sentences.",
)
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-realtime-2.1")
REALTIME_VOICE = os.getenv("REALTIME_VOICE", "marin")
REALTIME_TRANSCRIPTION_MODEL = os.getenv(
    "REALTIME_TRANSCRIPTION_MODEL", "gpt-4o-transcribe"
)
REALTIME_API_URL = os.getenv(
    "REALTIME_API_URL", "https://api.openai.com/v1/realtime/calls"
)
REALTIME_SESSION_TIMEOUT = float(os.getenv("REALTIME_SESSION_TIMEOUT", "25"))
REALTIME_LOCAL_SESSION_TTL_SECONDS = int(
    os.getenv("REALTIME_LOCAL_SESSION_TTL_SECONDS", "900")
)
REALTIME_VAD_MODE = os.getenv("REALTIME_VAD_MODE", "semantic_vad")
REALTIME_VAD_EAGERNESS = os.getenv("REALTIME_VAD_EAGERNESS", "high")
REALTIME_VAD_THRESHOLD = float(os.getenv("REALTIME_VAD_THRESHOLD", "0.42"))
REALTIME_VAD_PREFIX_PADDING_MS = int(os.getenv("REALTIME_VAD_PREFIX_PADDING_MS", "250"))
REALTIME_VAD_SILENCE_MS = int(os.getenv("REALTIME_VAD_SILENCE_MS", "420"))

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "120/minute"},
}

SAAS_INTEGRATION_URL = os.getenv("SAAS_INTEGRATION_URL", "")
SAAS_INTEGRATION_TOKEN = os.getenv("SAAS_INTEGRATION_TOKEN", "")
SAAS_INTEGRATION_ENABLED = os.getenv("SAAS_INTEGRATION_ENABLED", "false").lower() in {"1", "true", "yes"}
SAAS_TENANT_SUBDOMAIN = os.getenv("SAAS_TENANT_SUBDOMAIN", "")
SAAS_TIMEOUT_SECONDS = float(os.getenv("SAAS_TIMEOUT_SECONDS", "5"))

REMOTE_COMMAND_TIMEOUT_SECONDS = float(os.getenv("REMOTE_COMMAND_TIMEOUT_SECONDS", "3"))
REMOTE_BUTTON_COOLDOWN_SECONDS = float(os.getenv("REMOTE_BUTTON_COOLDOWN_SECONDS", "1.5"))
