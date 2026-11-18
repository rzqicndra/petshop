"""Configuration checks only: no credentials or provider requests in startup validation."""

from urllib.parse import urlsplit
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def validate_modes_and_urls(config=None):
    config = config if config is not None else settings
    for name, allowed in {
        "DEPLOYMENT_MODE": {"local", "production"},
        "PAYMENT_MODE": {"mock", "midtrans_sandbox", "midtrans_live", "disabled"},
        "ROUTES_MODE": {"mock", "openrouteservice", "disabled"},
        "MAP_PROVIDER": {"leaflet"},
        "SHIPPING_MODE": {"mock", "biteship", "disabled"},
    }.items():
        if getattr(config, name) not in allowed:
            raise ImproperlyConfigured(f"Nilai {name} tidak dikenal.")
    for name in ("APP_URL", "PUBLIC_WEBHOOK_BASE_URL"):
        value = getattr(config, name)
        if not value and name == "PUBLIC_WEBHOOK_BASE_URL":
            continue
        try:
            parts = urlsplit(value)
            valid = parts.hostname and parts.port != 0
        except ValueError:
            valid = False
        if (
            not valid
            or parts.scheme not in {"http", "https"}
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
        ):
            raise ImproperlyConfigured(
                f"{name} harus berupa origin HTTP/HTTPS tanpa path, kredensial, atau query."
            )
        if name == "PUBLIC_WEBHOOK_BASE_URL" and (
            parts.scheme != "https" or parts.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ImproperlyConfigured("PUBLIC_WEBHOOK_BASE_URL harus berupa origin HTTPS publik.")
    if config.EMAIL_USE_TLS and config.EMAIL_USE_SSL:
        raise ImproperlyConfigured("Pilih salah satu EMAIL_USE_TLS atau EMAIL_USE_SSL.")
    tiles = urlsplit(config.MAP_TILE_URL)
    if (
        tiles.scheme != "https"
        or not tiles.hostname
        or tiles.username
        or tiles.password
        or any(x not in config.MAP_TILE_URL for x in ("{z}", "{x}", "{y}"))
    ):
        raise ImproperlyConfigured(
            "MAP_TILE_URL harus template HTTPS {z}/{x}/{y} tanpa kredensial."
        )
    if not config.MAP_TILE_ATTRIBUTION.strip():
        raise ImproperlyConfigured("Attribution sumber peta wajib diisi.")
    origin = urlsplit(config.ORS_BASE_URL)
    if (
        not origin.hostname
        or origin.username
        or origin.password
        or origin.query
        or origin.fragment
        or origin.scheme != "https"
    ):
        raise ImproperlyConfigured("ORS_BASE_URL harus URL HTTPS tanpa kredensial/query.")
    if (
        min(config.ORS_REQUESTS_PER_MINUTE, config.ORS_REQUESTS_PER_DAY) < 1
        or not 0 <= config.ORS_CACHE_SECONDS <= 86400
    ):
        raise ImproperlyConfigured("Batas ORS harus positif; cache 0 hingga 86400 detik.")


def readiness_issues():
    issues = []
    for name in ("PAYMENT_MODE", "ROUTES_MODE", "SHIPPING_MODE"):
        if getattr(settings, name) in {"mock", "disabled"}:
            issues.append(f"{name}: integrasi nyata belum aktif.")
    if settings.PAYMENT_MODE.startswith("midtrans_") and not settings.MIDTRANS_SERVER_KEY:
        issues.append("MIDTRANS_SERVER_KEY belum diisi.")
    if settings.ROUTES_MODE == "openrouteservice" and not settings.ORS_API_KEY:
        issues.append(
            "ORS_API_KEY belum diisi. Daftar key Standard gratis di account.heigit.org; tanpa billing Google."
        )
    if settings.SHIPPING_MODE == "biteship" and not settings.BITESHIP_API_KEY:
        issues.append("BITESHIP_API_KEY belum diisi.")
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        if not getattr(settings, name):
            issues.append(f"{name} belum diisi.")
    if (
        settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend"
        or settings.EMAIL_HOST == "mailpit"
        or not settings.EMAIL_HOST_USER
        or not settings.EMAIL_HOST_PASSWORD
    ):
        issues.append(
            "SMTP internet berautentikasi belum lengkap; Mailpit tidak mengirim ke inbox internet."
        )
    if not settings.PUBLIC_WEBHOOK_BASE_URL:
        issues.append("PUBLIC_WEBHOOK_BASE_URL belum diisi; webhook publik belum disiapkan.")
    if settings.SHIPPING_MODE == "biteship" and not settings.BITESHIP_WEBHOOK_SECRET:
        issues.append("BITESHIP_WEBHOOK_SECRET belum diisi.")
    if not settings.LOCAL_MODE and settings.PAYMENT_MODE != "midtrans_live":
        issues.append("Production untuk pembayaran nyata memerlukan PAYMENT_MODE=midtrans_live.")
    if settings.PUBLIC_WEBHOOK_BASE_URL:
        host = urlsplit(settings.PUBLIC_WEBHOOK_BASE_URL).hostname
        if host not in settings.ALLOWED_HOSTS:
            issues.append("Hostname webhook belum terdaftar eksplisit pada ALLOWED_HOSTS.")
    app = urlsplit(settings.APP_URL)
    if app.hostname not in settings.ALLOWED_HOSTS:
        issues.append("Hostname APP_URL belum terdaftar eksplisit pada ALLOWED_HOSTS.")
    if settings.APP_URL not in settings.CSRF_TRUSTED_ORIGINS:
        issues.append("APP_URL belum terdaftar pada CSRF_TRUSTED_ORIGINS.")
    return issues
