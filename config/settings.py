"""Environment-driven settings. The local environment never implies a live provider."""

import os
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes"}


DEPLOYMENT_MODE = os.environ.get("DEPLOYMENT_MODE", "local")
LOCAL_MODE = DEPLOYMENT_MODE == "local"
SECRET_KEY = os.environ.get("SECRET_KEY", "")
DATA_ENCRYPTION_KEY = os.environ.get("DATA_ENCRYPTION_KEY", "")
if len(SECRET_KEY) < 50 or not DATA_ENCRYPTION_KEY:
    raise ImproperlyConfigured(
        "Jalankan python scripts/init_local.py untuk membuat .env dengan kunci acak."
    )
DEBUG = False  # Computed below after the public exposure settings are available.
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
    if h.strip()
]
CSRF_TRUSTED_ORIGINS = [x for x in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if x]
APP_URL = os.environ.get("APP_URL", "http://localhost:8000").rstrip("/")
PUBLIC_WEBHOOK_BASE_URL = os.environ.get("PUBLIC_WEBHOOK_BASE_URL", "").rstrip("/")
from .debug_policy import debug_allowed
DEBUG = debug_allowed(env_bool("DEBUG", False), LOCAL_MODE, ALLOWED_HOSTS, PUBLIC_WEBHOOK_BASE_URL)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "accounts",
    "core",
    "customers",
    "catalog",
    "inventory",
    "orders",
    "scheduling",
    "care",
    "boarding",
    "billing",
    "delivery",
    "engagement",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.ResponseSecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.AccessMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.application",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

db_url = urlparse(os.environ.get("DATABASE_URL", "postgresql://sinau:sinau@db:5432/sinau"))
db_options = {k: v[-1] for k, v in parse_qs(db_url.query).items()}
db_host = db_options.pop("host", None) or db_url.hostname or "db"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(db_url.path.lstrip("/")),
        "USER": unquote(db_url.username or "sinau"),
        "PASSWORD": unquote(db_url.password or ""),
        "HOST": db_host,
        "PORT": db_url.port or 5432,
        "OPTIONS": db_options,
        "CONN_MAX_AGE": 0 if LOCAL_MODE else 60,
        "ATOMIC_REQUESTS": False,
    }
}
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ["email", "full_name"]},
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not LOCAL_MODE
CSRF_COOKIE_SECURE = not LOCAL_MODE
SECURE_SSL_REDIRECT = not LOCAL_MODE
SECURE_HSTS_SECONDS = 0 if LOCAL_MODE else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not LOCAL_MODE
SECURE_HSTS_PRELOAD = not LOCAL_MODE
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
# Do not trust forwarded headers by default; configure the trusted reverse proxy at deployment.
if env_bool("TRUST_PROXY_HTTPS"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
REQUIRE_STAFF_MFA = env_bool("REQUIRE_STAFF_MFA", not LOCAL_MODE)

LANGUAGE_CODE = "id"
TIME_ZONE = "Asia/Jakarta"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedStaticFilesStorage"
            if LOCAL_MODE
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
PRIVATE_ROOT = BASE_DIR / "var" / "private"
MEDIA_ROOT = PRIVATE_ROOT
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 8 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 200
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "mailpit")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "1025"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS")
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL")
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "20"))
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Sinau Satwa <noreply@sinau.test>")
OTP_TTL_SECONDS = 300
OTP_RESEND_SECONDS = 60
OTP_MAX_ATTEMPTS = 5

PAYMENT_MODE = os.environ.get("PAYMENT_MODE", "mock")
MIDTRANS_SERVER_KEY = os.environ.get("MIDTRANS_SERVER_KEY", "")
MIDTRANS_CLIENT_KEY = os.environ.get("MIDTRANS_CLIENT_KEY", "")
MIDTRANS_LIVE = PAYMENT_MODE == "midtrans_live"
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
MAP_PROVIDER = os.environ.get("MAP_PROVIDER", "leaflet")
MAP_TILE_URL = os.environ.get("MAP_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
MAP_TILE_ATTRIBUTION = os.environ.get("MAP_TILE_ATTRIBUTION", "© OpenStreetMap contributors")
ROUTES_MODE = os.environ.get("ROUTES_MODE", "openrouteservice")
ORS_API_KEY = os.environ.get("ORS_API_KEY", "")
ORS_BASE_URL = os.environ.get("ORS_BASE_URL", "https://api.heigit.org/openrouteservice").rstrip("/")
ORS_REQUESTS_PER_MINUTE = int(os.environ.get("ORS_REQUESTS_PER_MINUTE", "30"))
ORS_REQUESTS_PER_DAY = int(os.environ.get("ORS_REQUESTS_PER_DAY", "1500"))
ORS_CACHE_SECONDS = int(os.environ.get("ORS_CACHE_SECONDS", "3600"))
SHIPPING_MODE = os.environ.get("SHIPPING_MODE", "mock")
BITESHIP_API_KEY = os.environ.get("BITESHIP_API_KEY", "")
BITESHIP_WEBHOOK_HEADER = os.environ.get("BITESHIP_WEBHOOK_HEADER", "X-Sinau-Shipping-Secret")
BITESHIP_WEBHOOK_SECRET = os.environ.get("BITESHIP_WEBHOOK_SECRET", "")
MOCK_ROUTE_DISTANCE_M = int(os.environ.get("MOCK_ROUTE_DISTANCE_M", "3200"))
MOCK_INSTANT_FEE_RP = int(os.environ.get("MOCK_INSTANT_FEE_RP", "18000"))
from config.integration_checks import validate_modes_and_urls
from types import SimpleNamespace

validate_modes_and_urls(SimpleNamespace(**globals()))
if not LOCAL_MODE:
    if "*" in ALLOWED_HOSTS or not APP_URL.startswith("https://"):
        raise ImproperlyConfigured("Production memerlukan hostname eksplisit dan APP_URL HTTPS.")
    if PAYMENT_MODE == "mock" or ROUTES_MODE == "mock" or SHIPPING_MODE == "mock":
        raise ImproperlyConfigured("Mode simulasi hanya diizinkan untuk lingkungan lokal.")
    if not REQUIRE_STAFF_MFA:
        raise ImproperlyConfigured("MFA staf wajib di production.")

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BEAT_SCHEDULE = {"maintenance": {"task": "core.tasks.maintenance", "schedule": 30.0}}
CELERY_TIMEZONE = TIME_ZONE
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"sinau": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
