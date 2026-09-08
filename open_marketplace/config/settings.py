import os
from base64 import b64decode
from binascii import Error as BinasciiError
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _required(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _decoded_key(name):
    value = _required(name)
    try:
        decoded = b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (BinasciiError, UnicodeEncodeError, ValueError):
        raise RuntimeError(f"{name} is invalid") from None
    return value, decoded


def _fernet_key(name):
    value, decoded = _decoded_key(name)
    if len(decoded) != 32:
        raise RuntimeError(f"{name} is invalid")
    return value


def _hmac_key(name):
    value, decoded = _decoded_key(name)
    if len(decoded) < 32:
        raise RuntimeError(f"{name} is invalid")
    return value


def _origin(name):
    value = _required(name)
    try:
        parsed = urlsplit(value)
        parsed.port
        authority_is_clean = (
            not parsed.netloc.endswith(":")
            and all(
                ord(character) >= 33 and character != "\\"
                for character in parsed.netloc
            )
        )
        valid = (
            parsed.geturl() == value
            and parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and authority_is_clean
            and parsed.username is None
            and parsed.password is None
            and parsed.path == ""
            and parsed.query == ""
            and parsed.fragment == ""
        )
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError(f"{name} is invalid") from None
    return value


SECRET_KEY = _required("DJANGO_SECRET_KEY")
_database_password = _required("DATABASE_PASSWORD")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "open_marketplace.identity.apps.IdentityConfig",
    "open_marketplace.access.apps.AccessConfig",
    "open_marketplace.seller_onboarding.apps.SellerOnboardingConfig",
    "open_marketplace.audit.apps.AuditConfig",
    "open_marketplace.outbox.apps.OutboxConfig",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

AUTH_USER_MODEL = "identity.Account"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "open_marketplace.web.middleware.RequestIdMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "open_marketplace.identity.middleware.SessionRegistryMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "open_marketplace.config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "open_marketplace" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "open_marketplace.config.wsgi.application"
ASGI_APPLICATION = "open_marketplace.config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DATABASE_NAME"],
        "USER": os.environ["DATABASE_USER"],
        "PASSWORD": _database_password,
        "HOST": os.environ["DATABASE_HOST"],
        "PORT": os.environ["DATABASE_PORT"],
    }
}

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": PASSWORD_MIN_LENGTH},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ["EMAIL_HOST"]
EMAIL_PORT = int(os.environ["EMAIL_PORT"])
APP_BASE_URL = _origin("APP_BASE_URL")

TOTP_ENCRYPTION_KEY = _fernet_key("TOTP_ENCRYPTION_KEY")
OUTBOX_ENCRYPTION_KEY = _fernet_key("OUTBOX_ENCRYPTION_KEY")
LINK_EXCHANGE_ENCRYPTION_KEY = _fernet_key("LINK_EXCHANGE_ENCRYPTION_KEY")
THROTTLE_HASH_KEY = _hmac_key("THROTTLE_HASH_KEY")

_secure_cookies = os.environ.get("DJANGO_SECURE_COOKIES", "false").lower() == "true"
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = _secure_cookies
CSRF_COOKIE_SECURE = _secure_cookies
SECURE_SSL_REDIRECT = _secure_cookies
SECURE_HSTS_SECONDS = 31536000 if _secure_cookies else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = _secure_cookies
SECURE_HSTS_PRELOAD = _secure_cookies

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "sensitive_routes": {
            "()": "open_marketplace.web.logging.SensitiveRouteFilter",
        },
    },
    "formatters": {
        "default": {
            "format": "{levelname} {name} request_id={request_id} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["sensitive_routes"],
            "formatter": "default",
        },
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.server": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "open_marketplace": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

EMAIL_VERIFICATION_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(minutes=30)
STAFF_INVITATION_TTL = timedelta(hours=24)
MANDATORY_TOTP_RECOVERY_TTL = timedelta(minutes=30)
SENSITIVE_ACTION_REAUTH_TTL = timedelta(minutes=15)
TOTP_SETUP_TTL = timedelta(minutes=10)
RECOVERY_CODE_COUNT = 10
ORDINARY_SESSION_ABSOLUTE_TTL = timedelta(days=30)
SERVICE_SESSION_ABSOLUTE_TTL = timedelta(hours=12)
SERVICE_SESSION_IDLE_TTL = timedelta(minutes=30)
LOGIN_THROTTLE_THRESHOLD = 5
LOGIN_THROTTLE_WINDOW = timedelta(minutes=15)
LOGIN_THROTTLE_DELAYS = (5, 10, 20, 40, 60)
EMAIL_THROTTLE_LIMIT = 3
EMAIL_THROTTLE_WINDOW = timedelta(hours=1)
