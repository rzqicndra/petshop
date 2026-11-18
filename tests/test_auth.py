import re
from datetime import timedelta
from unittest.mock import patch
from django.core import mail
from django.test import TestCase, override_settings, Client
from django.utils import timezone
from accounts.models import User, OTPChallenge, AccountSecurity
from accounts.services import issue_otp, verify_otp, rate_limit, verify_totp
from core.models import OutboxEvent
from core.notifications import deliver_outbox
from core.services import BusinessError, cipher
from .factories import fixture, login_as


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class AuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def raw_code(self, user, purpose):
        issue_otp(user, purpose)
        deliver_outbox()
        return re.search(r"Kode verifikasi Anda: (\d{6})", mail.outbox[-1].body).group(1)

    def test_register_uses_email_otp_and_only_customer_role(self):
        response = self.client.post(
            "/register/",
            {
                "email": "New@Example.test",
                "full_name": "New Person",
                "password": "UniquePassw0rd!ABC",
                "password_confirm": "UniquePassw0rd!ABC",
                "consent": "on",
                "roles": "SUPER_ADMIN",
            },
        )
        self.assertRedirects(response, "/otp/", fetch_redirect_response=False)
        user = User.objects.get(email="new@example.test")
        self.assertIsNone(user.email_verified_at)
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["CUSTOMER"])
        deliver_outbox()
        self.assertEqual(len(mail.outbox), 1)
        raw = re.search(r"Kode verifikasi Anda: (\d{6})", mail.outbox[0].body).group(1)
        challenge = OTPChallenge.objects.get(user=user)
        self.assertNotEqual(challenge.code_digest, raw)
        event = OutboxEvent.objects.get(topic="auth.otp", aggregate_id=challenge.pk)
        self.assertNotIn(raw, str(event.payload))
        self.assertIsNone(event.sensitive_ciphertext)
        self.client.post("/otp/", {"code": raw})
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)

    def test_forgot_password_invalidates_previous_sessions(self):
        self.user.set_password("OldPassword!123")
        self.user.save()
        login_as(self.client, self.user)
        fresh = Client()
        fresh.post("/forgot-password/", {"email": self.user.email})
        deliver_outbox()
        raw = re.search(r"Kode verifikasi Anda: (\d{6})", mail.outbox[-1].body).group(1)
        self.assertRedirects(
            fresh.post("/otp/", {"code": raw}), "/reset-password/", fetch_redirect_response=False
        )
        fresh.post(
            "/reset-password/",
            {"password": "NewPassword!12345", "password_confirm": "NewPassword!12345"},
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPassword!12345"))
        self.assertEqual(self.user.auth_version, 2)
        self.assertRedirects(
            self.client.get("/dashboard/"),
            "/login/?next=/dashboard/",
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            fresh.get("/reset-password/"), "/forgot-password/", fetch_redirect_response=False
        )

    def test_otp_wrong_attempts_commit_and_lock_after_five(self):
        raw = self.raw_code(self.user, "RESET")
        bad = "000000" if raw != "000000" else "999999"
        for _ in range(5):
            with self.assertRaises(BusinessError):
                verify_otp(self.user.pk, "RESET", bad)
        challenge = OTPChallenge.objects.get(user=self.user, purpose="RESET")
        self.assertEqual(challenge.attempt_count, 5)
        self.assertIsNotNone(challenge.invalidated_at)
        with self.assertRaises(BusinessError):
            verify_otp(self.user.pk, "RESET", raw)

    def test_otp_is_purpose_bound_single_use_and_email_bound(self):
        raw = self.raw_code(self.user, "REGISTER")
        with self.assertRaises(BusinessError):
            verify_otp(self.user.pk, "RESET", raw)
        self.assertEqual(verify_otp(self.user.pk, "REGISTER", raw).pk, self.user.pk)
        with self.assertRaises(BusinessError):
            verify_otp(self.user.pk, "REGISTER", raw)

    def test_expired_otp_rejected_and_resend_invalidates_old(self):
        raw = self.raw_code(self.user, "RESET")
        challenge = OTPChallenge.objects.get(user=self.user)
        OTPChallenge.objects.filter(pk=challenge.pk).update(
            created_at=timezone.now() - timedelta(seconds=61),
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        with self.assertRaises(BusinessError):
            verify_otp(self.user.pk, "RESET", raw)
        new = issue_otp(self.user, "RESET")
        self.assertNotEqual(new.pk, challenge.pk)
        self.assertIsNone(issue_otp(self.user, "RESET"))

    def test_rate_limits_persist_after_rejection(self):
        rate_limit("test", "identifier", 1, 60)
        with self.assertRaises(BusinessError):
            rate_limit("test", "identifier", 1, 60)
        from accounts.models import RateLimitBucket

        self.assertEqual(RateLimitBucket.objects.get().count, 2)

    def test_login_redirects_to_role_after_password_not_email_alone(self):
        user = self.admin
        user.set_password("StaffPassword!12345")
        user.save()
        failed = self.client.post("/login/", {"email": user.email, "password": "wrong"})
        self.assertEqual(failed.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(
            self.client.post("/login/", {"email": user.email, "password": "StaffPassword!12345"}),
            "/staf/admin/",
            fetch_redirect_response=False,
        )

    def test_csrf_and_logout_post_only(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post("/register/", {}).status_code, 403)
        self.assertEqual(self.client.get("/logout/").status_code, 405)

    def test_owner_cannot_mutate_and_cannot_switch_to_unassigned_role(self):
        login_as(self.client, self.users["OWNER"])
        self.assertEqual(
            self.client.post("/operasional/stok/", {"action": "anything"}).status_code, 403
        )
        self.assertEqual(self.client.post("/workspace/", {"role": "SUPER_ADMIN"}).status_code, 403)

    def test_open_redirect_and_role_url_do_not_grant_access(self):
        self.user.set_password("UniquePassword!123")
        self.user.save()
        self.client.get("/login/?next=https://evil.example/")
        self.assertRedirects(
            self.client.post(
                "/login/", {"email": self.user.email, "password": "UniquePassword!123"}
            ),
            "/dashboard/",
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            self.client.get("/staf/super-admin/"), "/dashboard/", fetch_redirect_response=False
        )
        self.assertEqual(self.client.get("/management/").status_code, 403)

    def test_totp_and_recovery_cannot_be_replayed(self):
        import pyotp
        from django.contrib.auth.hashers import make_password

        secret = pyotp.random_base32()
        AccountSecurity.objects.create(
            user=self.admin,
            totp_ciphertext=cipher().encrypt(secret.encode()).decode(),
            enabled_at=timezone.now(),
            recovery_digests=[make_password("recover-once")],
        )
        code = pyotp.TOTP(secret).now()
        self.assertTrue(verify_totp(self.admin, code))
        self.assertFalse(verify_totp(self.admin, code))
        self.assertTrue(verify_totp(self.admin, "recover-once"))
        self.assertFalse(verify_totp(self.admin, "recover-once"))

    def test_unknown_email_has_same_forgot_response(self):
        response = self.client.post("/forgot-password/", {"email": "unknown@example.test"})
        self.assertRedirects(response, "/otp/", fetch_redirect_response=False)
        self.assertEqual(OTPChallenge.objects.count(), 0)

    def test_owner_can_link_personal_google_without_business_write_access(self):
        from unittest.mock import Mock
        from django.http import HttpResponseRedirect

        owner = self.users["OWNER"]
        owner.set_password("OwnerPassword!12345")
        owner.save()
        login_as(self.client, owner)
        provider = Mock()
        provider.authorize_redirect.return_value = HttpResponseRedirect(
            "https://accounts.google.com/test"
        )
        with patch("accounts.views.google_client", return_value=provider):
            response = self.client.post(
                "/auth/google/tautkan/", {"password": "OwnerPassword!12345"}
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://accounts.google.com/test")
        self.assertEqual(self.client.post("/operasional/stok/", {}).status_code, 403)
