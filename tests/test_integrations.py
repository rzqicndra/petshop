from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from billing.models import Invoice, PaymentAttempt
from billing.providers import create_snap
from config.integration_checks import validate_modes_and_urls, readiness_issues
from .factories import fixture, booking, login_as


class IntegrationConfigTests(SimpleTestCase):
    @override_settings(PAYMENT_MODE="typo")
    def test_unknown_modes_fail_instead_of_choosing_real_provider(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_modes_and_urls()

    @override_settings(PUBLIC_WEBHOOK_BASE_URL="http://localhost:18000")
    def test_public_callback_rejects_local_http(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_modes_and_urls()

    @override_settings(APP_URL="https://secret:password@example.com/path?token=abc")
    def test_app_origin_rejects_credentials_paths_and_query(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_modes_and_urls()

    @override_settings(EMAIL_USE_TLS=True, EMAIL_USE_SSL=True)
    def test_mutually_exclusive_smtp_encryption(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_modes_and_urls()

    @override_settings(PAYMENT_MODE="midtrans_sandbox", MIDTRANS_SERVER_KEY="")
    def test_missing_enabled_credentials_reported(self):
        self.assertIn("MIDTRANS_SERVER_KEY belum diisi.", readiness_issues())

    @override_settings(
        APP_URL="http://localhost:18000",
        PUBLIC_WEBHOOK_BASE_URL="https://current.example",
        MIDTRANS_SERVER_KEY="SECRET-NEVER-LOG",
        MIDTRANS_LIVE=False,
    )
    @patch("billing.providers.requests.post")
    def test_local_snap_finish_and_webhook_are_separate(self, post):
        post.return_value.json.return_value = {
            "redirect_url": "https://app.sandbox.midtrans.com/snap/test",
            "token": "token",
        }
        now = timezone.now()
        create_snap(
            SimpleNamespace(
                provider_order_id="SS-PAY-LOCAL",
                expected_amount_rp=10000,
                created_at=now,
                expires_at=now + timedelta(minutes=15),
            )
        )
        kwargs = post.call_args.kwargs
        self.assertEqual(
            kwargs["json"]["callbacks"]["finish"],
            "http://localhost:18000/pembayaran/kembali/?order_id=SS-PAY-LOCAL",
        )
        self.assertEqual(
            kwargs["headers"]["X-Override-Notification"],
            "https://current.example/webhooks/midtrans/",
        )

    @override_settings(
        APP_URL="https://shop.example",
        PUBLIC_WEBHOOK_BASE_URL="",
        MIDTRANS_SERVER_KEY="key",
        MIDTRANS_LIVE=True,
    )
    @patch("billing.providers.requests.post")
    def test_production_snap_uses_live_endpoint_and_own_finish(self, post):
        post.return_value.json.return_value = {"redirect_url": "https://app.midtrans.com/snap/test"}
        now = timezone.now()
        create_snap(
            SimpleNamespace(
                provider_order_id="SS-PAY-LIVE",
                expected_amount_rp=10000,
                created_at=now,
                expires_at=now + timedelta(minutes=15),
            )
        )
        self.assertEqual(post.call_args.args[0], "https://app.midtrans.com/snap/v1/transactions")
        self.assertTrue(
            post.call_args.kwargs["json"]["callbacks"]["finish"].startswith("https://shop.example/")
        )
        self.assertNotIn("X-Override-Notification", post.call_args.kwargs["headers"])


class IntegrationFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def attempt(self):
        bk = booking(self, "VET")
        invoice = Invoice.objects.get(booking=bk)
        return PaymentAttempt.objects.create(
            invoice=invoice,
            provider="MIDTRANS",
            environment="midtrans_sandbox",
            provider_order_id="SS-PAY-RETURN",
            method="SNAP",
            status="PENDING",
            expected_amount_rp=invoice.total_rp,
            expires_at=invoice.expires_at,
            request_key="return",
        )

    def test_return_query_cannot_settle_payment_or_choose_arbitrary_redirect(self):
        attempt = self.attempt()
        login_as(self.client, self.user)
        response = self.client.get(
            "/pembayaran/kembali/",
            {
                "order_id": attempt.provider_order_id,
                "transaction_status": "settlement",
                "status_code": "200",
                "next": "https://evil.example",
            },
        )
        self.assertRedirects(
            response, f"/tagihan/{attempt.invoice_id}/", fetch_redirect_response=False
        )
        attempt.invoice.refresh_from_db()
        self.assertEqual(attempt.invoice.status, "UNPAID")

    def test_return_enforces_invoice_ownership(self):
        attempt = self.attempt()
        login_as(self.client, self.other)
        self.assertEqual(
            self.client.get(
                "/pembayaran/kembali/", {"order_id": attempt.provider_order_id}
            ).status_code,
            404,
        )

    def test_return_requires_login_and_retains_reference(self):
        attempt = self.attempt()
        response = self.client.get("/pembayaran/kembali/", {"order_id": attempt.provider_order_id})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/login/?next="))
        self.assertIn("order_id", response.url)

    def test_legacy_return_is_supported(self):
        attempt = self.attempt()
        login_as(self.client, self.user)
        self.assertEqual(
            self.client.get("/cek-pesanan", {"order_id": attempt.provider_order_id}).status_code,
            302,
        )

    @override_settings(
        MIDTRANS_SERVER_KEY="DO-NOT-PRINT-MIDTRANS",
        EMAIL_HOST_PASSWORD="DO-NOT-PRINT-SMTP",
        GOOGLE_CLIENT_SECRET="DO-NOT-PRINT-GOOGLE",
    )
    def test_diagnostics_never_print_credentials_and_strict_fails_incomplete_config(self):
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command("check_integrations", strict=True, stdout=output)
        for secret in ("DO-NOT-PRINT-MIDTRANS", "DO-NOT-PRINT-SMTP", "DO-NOT-PRINT-GOOGLE"):
            self.assertNotIn(secret, output.getvalue())
        self.assertIn("Google redirect URI", output.getvalue())
