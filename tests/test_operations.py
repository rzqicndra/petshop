import re
import smtplib
from datetime import timedelta
from unittest.mock import Mock, patch
from django.core import mail, signing
from django.test import TestCase, override_settings
from django.utils import timezone
from accounts.models import User, OTPChallenge, ExternalIdentity
from accounts.staff import provision_staff
from accounts.services import issue_otp, verify_otp
from core.models import OutboxEvent
from core.notifications import deliver_outbox
from core.services import BusinessError
from delivery.models import Shipment, DeliveryAssignment
from delivery.services import (
    quote_order,
    request_shipment,
    approve_dispatch_cost,
    assign_internal,
    start_internal,
    complete_internal,
)
from orders.services import draft_order, checkout, pack_order
from billing.models import Invoice
from .factories import fixture, pay, login_as


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class OperationalSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def test_google_matching_staff_email_does_not_auto_link_or_login(self):
        provider = Mock()
        provider.authorize_access_token.return_value = {
            "userinfo": {
                "sub": "external-subject",
                "email": self.admin.email,
                "email_verified": True,
            }
        }
        with patch("accounts.views.google_client", return_value=provider):
            response = self.client.get("/auth/google/callback/")
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)
        self.assertFalse(ExternalIdentity.objects.exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_staff_invite_requires_otp_then_sets_verified_password(self):
        user = provision_staff(
            self.users["SUPER_ADMIN"],
            {
                "email": "newstaff@example.test",
                "full_name": "New Staff",
                "roles": ["GROOMER"],
                "can_deliver": False,
                "is_active": True,
            },
        )
        self.assertFalse(user.has_usable_password())
        self.assertIsNone(user.email_verified_at)
        deliver_outbox()
        body = mail.outbox[-1].body
        raw = re.search(r"Kode verifikasi Anda: (\d{6})", body).group(1)
        challenge = OTPChallenge.objects.get(user=user, purpose="INVITE")
        token = signing.dumps(
            {"user": str(user.pk), "version": user.auth_version, "challenge": str(challenge.pk)},
            salt="staff-invite",
        )
        self.client.get("/undangan/", {"token": token})
        self.client.post("/otp/", {"code": raw})
        self.client.post(
            "/reset-password/",
            {"password": "StaffNewPassword!123", "password_confirm": "StaffNewPassword!123"},
        )
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)
        self.assertTrue(user.check_password("StaffNewPassword!123"))

    def test_last_active_super_admin_cannot_be_removed(self):
        user = self.users["SUPER_ADMIN"]
        with self.assertRaises(BusinessError):
            provision_staff(
                user,
                {
                    "email": user.email,
                    "full_name": user.full_name,
                    "roles": ["OWNER"],
                    "can_deliver": False,
                    "is_active": True,
                },
            )

    def test_otp_binding_survives_email_change_and_old_message_is_not_sent(self):
        challenge = issue_otp(self.user, "RESET")
        self.user.email = "changed@example.test"
        self.user.save()
        deliver_outbox()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(OutboxEvent.objects.get(aggregate_id=challenge.pk).status, "CANCELED")

    def test_smtp_uncertainty_not_blindly_retried(self):
        challenge = issue_otp(self.user, "RESET")
        with patch(
            "core.notifications.EmailMultiAlternatives.send", side_effect=smtplib.SMTPServerDisconnected
        ):
            deliver_outbox()
        event = OutboxEvent.objects.get(aggregate_id=challenge.pk)
        self.assertEqual(event.status, "UNKNOWN")
        with patch("core.notifications.EmailMultiAlternatives.send") as send:
            deliver_outbox()
            send.assert_not_called()

    def test_forged_payment_webhook_rejected(self):
        self.assertEqual(
            self.client.post(
                "/webhooks/midtrans/",
                data='{"order_id":"fake","gross_amount":"1"}',
                content_type="application/json",
            ).status_code,
            403,
        )

    def test_invoice_exactly_one_target_and_owner_denial_includes_security_headers(self):
        login_as(self.client, self.users["OWNER"])
        response = self.client.post("/operasional/stok/", {})
        self.assertEqual(response.status_code, 403)
        self.assertIn("Content-Security-Policy", response)


@override_settings(ROUTES_MODE="mock", SHIPPING_MODE="mock")
class DeliveryOperationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def packed(self, method="INTERNAL", real=False):
        order = draft_order(self.user, {str(self.variant.pk): 1}, "DELIVERY", self.address)
        quotes, _ = quote_order(order)
        quote = next(q for q in quotes if q.method == method)
        if real:
            quote.provider, quote.service_code = "BITESHIP", "grab:instant"
            quote.save()
        checkout(self.user, order, "delivery-" + str(order.pk), quote)
        pay(Invoice.objects.get(order=order))
        order.refresh_from_db()
        pack_order(self.admin, order)
        order.refresh_from_db()
        return order

    def test_internal_assignment_start_proof_and_completion(self):
        order = self.packed()
        ship = request_shipment(self.admin, order)
        assign_internal(self.admin, ship, self.admin)
        assignment = DeliveryAssignment.objects.get(shipment=ship)
        start_internal(self.admin, assignment)
        order.refresh_from_db()
        self.assertEqual(order.status, "IN_TRANSIT")
        from core.models import PrivateFile

        proof = PrivateFile.objects.create(
            uploaded_by=self.admin,
            storage_key="proof.jpg",
            original_name="proof.jpg",
            mime_type="image/jpeg",
            size_bytes=10,
            sha256="0" * 64,
            classification="DELIVERY_PROOF",
            scan_status="VALIDATED",
        )
        complete_internal(self.admin, assignment, "Ayu", proof)
        order.refresh_from_db()
        self.assertEqual(order.status, "COMPLETED")

    def test_dispatch_cost_change_waits_for_explicit_approval(self):
        order = self.packed("INSTANT", real=True)
        new_fee = order.shipping_rp + 5000
        rates = [{"courier_code": "grab", "courier_service_code": "instant", "price": new_fee}]
        with (
            patch("delivery.providers.instant_rates", return_value=rates),
            patch("delivery.providers.create_external_shipment") as create,
        ):
            with self.assertRaises(BusinessError):
                request_shipment(self.admin, order)
            create.assert_not_called()
        ship = Shipment.objects.get(order=order)
        self.assertEqual(ship.status, "ON_HOLD")
        self.assertEqual(ship.actual_fee_rp, new_fee)
        with (
            patch("delivery.providers.instant_rates", return_value=rates),
            patch(
                "delivery.providers.create_external_shipment",
                side_effect=lambda s, p: {
                    "id": "provider-id",
                    "reference_id": s.request_key,
                    "status": "confirmed",
                },
            ),
        ):
            approve_dispatch_cost(
                self.admin, ship, "Selisih ditanggung toko untuk memenuhi pesanan"
            )
        ship.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(ship.status, "CONFIRMED")
        self.assertEqual(order.shipping_rp, new_fee - 5000)

    def test_reassigned_courier_cannot_start_from_stale_assignment(self):
        order = self.packed()
        ship = request_shipment(self.admin, order)
        assign_internal(self.admin, ship, self.admin)
        old_assignment = DeliveryAssignment.objects.get(shipment=ship)
        self.other.can_deliver = True
        self.other.save(update_fields=["can_deliver"])
        assign_internal(self.admin, ship, self.other)
        with self.assertRaises(BusinessError):
            start_internal(self.admin, old_assignment)

    def test_delivery_map_link_uses_unlocalized_coordinates(self):
        order = self.packed()
        ship = request_shipment(self.admin, order)
        login_as(self.client, self.admin)
        response = self.client.get(f"/pengiriman/{ship.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "query=-6.244200,106.783500")
