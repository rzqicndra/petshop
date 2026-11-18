import smtplib
import socket
import ssl
import requests
from urllib.parse import urlsplit
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from django.core.mail import get_connection
from config.integration_checks import readiness_issues


class Command(BaseCommand):
    help = "Periksa kesiapan integrasi tanpa mencetak secret. --network menguji SMTP login dan konektivitas TLS; tidak mengirim email atau membuat transaksi."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true")
        parser.add_argument("--network", action="store_true")

    def handle(self, *args, **options):
        for name in (
            "DEPLOYMENT_MODE",
            "PAYMENT_MODE",
            "MAP_PROVIDER",
            "ROUTES_MODE",
            "SHIPPING_MODE",
            "APP_URL",
        ):
            self.stdout.write(f"{name}={getattr(settings, name)}")
        self.stdout.write("Google redirect URI: " + settings.APP_URL + reverse("google_callback"))
        self.stdout.write("Midtrans finish: " + settings.APP_URL + reverse("payment_return"))
        for route in ("midtrans_webhook", "biteship_webhook"):
            self.stdout.write(
                f"{route}: "
                + (
                    settings.PUBLIC_WEBHOOK_BASE_URL + reverse(route)
                    if settings.PUBLIC_WEBHOOK_BASE_URL
                    else "BELUM DIATUR"
                )
            )
        issues = readiness_issues()
        try:
            from core.models import StoreSettings

            store = StoreSettings.objects.filter(pk=1).first()
            if not store or not store.public_contact_ready:
                issues.append("Kontak/lokasi resmi toko belum disahkan pada data master.")
            if store:
                from core.store_validation import store_errors
                for field, message in store_errors(store).items():
                    issues.append(f"Data toko {field}: {message}")
        except Exception:
            issues.append(
                "Data toko belum dapat diperiksa; pastikan migrasi dan database tersedia."
            )
        if options["network"]:
            hosts = {
                "accounts.google.com",
                "api.biteship.com",
            }
            hosts.add(urlsplit(settings.MAP_TILE_URL).hostname)
            if settings.ROUTES_MODE == "openrouteservice":
                hosts.add(urlsplit(settings.ORS_BASE_URL).hostname)
            hosts.add("app.midtrans.com" if settings.MIDTRANS_LIVE else "app.sandbox.midtrans.com")
            hosts.add("api.midtrans.com" if settings.MIDTRANS_LIVE else "api.sandbox.midtrans.com")
            if settings.PUBLIC_WEBHOOK_BASE_URL:
                hosts.add(urlsplit(settings.PUBLIC_WEBHOOK_BASE_URL).hostname)
            for host in sorted(hosts):
                try:
                    with socket.create_connection((host, 443), timeout=8) as sock:
                        with ssl.create_default_context().wrap_socket(sock, server_hostname=host):
                            pass
                    self.stdout.write(f"TLS {host}: OK (bukan verifikasi API key/webhook)")
                except Exception:
                    issues.append(f"TLS {host}: GAGAL; periksa jaringan/tunnel.")
            if settings.PUBLIC_WEBHOOK_BASE_URL:
                try:
                    response = requests.get(
                        settings.PUBLIC_WEBHOOK_BASE_URL + "/health/",
                        headers={"ngrok-skip-browser-warning": "1"},
                        timeout=(5, 10),
                        allow_redirects=False,
                    )
                    if response.status_code != 200 or response.json().get("status") != "ok":
                        raise ValueError
                    self.stdout.write(
                        "Endpoint publik /health/: OK; lakukan uji webhook bertanda tangan secara terpisah."
                    )
                except Exception:
                    issues.append(
                        "Endpoint publik /health/ belum mengarah ke aplikasi sehat. Periksa tunnel aktif, port 18000, hostname, dan proxy HTTPS."
                    )
            if settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD:
                try:
                    connection = get_connection(fail_silently=False)
                    try:
                        connection.open()
                    finally:
                        connection.close()
                    self.stdout.write("SMTP: koneksi dan autentikasi OK; email belum dikirim.")
                except smtplib.SMTPAuthenticationError:
                    issues.append(
                        "SMTP: kredensial ditolak. Cocokkan akun pengirim dan App Password."
                    )
                except Exception:
                    issues.append(
                        "SMTP: koneksi/autentikasi gagal; tidak ada kredensial yang dicetak."
                    )
        for issue in issues:
            self.stdout.write("PERLU DILENGKAPI: " + issue)
        if issues and options["strict"]:
            raise CommandError(f"Ada {len(issues)} pemeriksaan yang belum terpenuhi.")
        self.stdout.write(
            "Pemeriksaan selesai. Kredensial, kuota, dan alur provider tetap memerlukan UAT akun proyek."
        )
