"""Regressions for role separation, personal data, document revision and checkout UX."""

import io
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.utils import timezone
from PIL import Image
from accounts.models import User
from core.models import StoreSettings, PrivateFile
from core.notifications import deliver_outbox
from accounts.services import issue_otp
from accounts.permissions import PermissionDenied
from boarding.models import BoardingIntakeFile, BoardingStay
from boarding.services import replace_intake, verify_intake, approve_stay
from billing.models import Invoice
from billing.services import begin_payment
from core.services import BusinessError
from core.master import MASTERS
from customers.models import Address
from orders.services import draft_order, checkout
from scheduling.models import Booking
from .factories import fixture, login_as, booking


@override_settings(
    ROUTES_MODE="mock",
    SHIPPING_MODE="mock",
    PAYMENT_MODE="mock",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class ExperienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def image(self):
        stream = io.BytesIO()
        Image.new("RGB", (20, 20), "green").save(stream, "PNG")
        return SimpleUploadedFile("health.png", stream.getvalue(), content_type="image/png")

    def invoice(self):
        order = draft_order(self.user, {str(self.variant.pk): 1}, "PICKUP")
        checkout(self.user, order, "experience")
        return Invoice.objects.get(order=order)

    def test_cart_add_stays_in_catalog_and_ajax_returns_count(self):
        response = self.client.post(
            "/keranjang/ubah/",
            {
                "variant": self.variant.pk,
                "quantity": 1,
                "mode": "add",
                "next": "/katalog/?species=CAT",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/katalog/?species=CAT")
        response = self.client.post(
            "/keranjang/ubah/",
            {"variant": self.variant.pk, "quantity": 1, "mode": "add"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(self.client.session["cart"][str(self.variant.pk)], 2)

    def test_cart_next_cannot_redirect_to_another_site(self):
        response = self.client.post(
            "/keranjang/ubah/",
            {"variant": self.variant.pk, "quantity": 1, "next": "https://evil.example"},
        )
        self.assertEqual(response.url, "/keranjang/")

    def test_staff_cannot_pay_simulate_or_add_to_cart(self):
        invoice = self.invoice()
        for role in ["SUPER_ADMIN", "ADMIN", "OWNER", "DOCTOR", "GROOMER", "CARETAKER"]:
            with self.assertRaises(PermissionDenied):
                begin_payment(self.users[role], invoice, str(uuid.uuid4()))
        login_as(self.client, self.admin)
        response = self.client.get(f"/tagihan/{invoice.pk}/")
        self.assertNotContains(response, "Bayar sekarang")
        self.assertNotContains(response, "Periksa ke")
        self.assertNotContains(response, "refund")
        self.assertEqual(
            self.client.post(f"/tagihan/{invoice.pk}/", {"action": "pay"}).status_code, 403
        )
        self.assertEqual(
            self.client.post(f"/tagihan/{invoice.pk}/", {"action": "simulate"}).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                "/keranjang/ubah/", {"variant": self.variant.pk, "quantity": 1}
            ).status_code,
            403,
        )

    def test_personal_pet_delete_is_owned_post_only_and_preserves_history(self):
        login_as(self.client, self.user)
        self.assertEqual(self.client.get(f"/hewan/{self.pet.pk}/hapus/").status_code, 405)
        self.assertEqual(self.client.post(f"/hewan/{self.pet2.pk}/hapus/").status_code, 404)
        response = self.client.post(f"/hewan/{self.pet.pk}/hapus/")
        self.assertEqual(response.status_code, 302)
        self.pet.refresh_from_db()
        self.assertFalse(self.pet.is_active)
        self.assertNotContains(self.client.get("/hewan/"), "Edit " + self.pet.name)
        self.assertEqual(self.client.get(f"/hewan/{self.pet.pk}/").status_code, 404)

    def test_pet_with_active_booking_cannot_be_removed(self):
        booking(self)
        login_as(self.client, self.user)
        self.client.post(f"/hewan/{self.pet.pk}/hapus/")
        self.pet.refresh_from_db()
        self.assertTrue(self.pet.is_active)

    def test_address_delete_is_owned_and_excluded_from_checkout(self):
        login_as(self.client, self.other)
        self.assertEqual(self.client.post(f"/alamat/{self.address.pk}/hapus/").status_code, 404)
        login_as(self.client, self.user)
        self.client.post(f"/alamat/{self.address.pk}/hapus/")
        self.address.refresh_from_db()
        self.assertFalse(self.address.is_active)
        with self.assertRaises(BusinessError):
            draft_order(self.user, {str(self.variant.pk): 1}, "DELIVERY", self.address)
        response = self.client.get("/checkout/")
        self.assertNotContains(response, f'value="{self.address.pk}"')

    def test_customer_cannot_open_inactive_or_time_elapsed_invoice(self):
        invoice = self.invoice()
        login_as(self.client, self.user)
        Invoice.objects.filter(pk=invoice.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.client.get(f"/tagihan/{invoice.pk}/").status_code, 404)
        Invoice.objects.filter(pk=invoice.pk).update(status="VOID")
        self.assertEqual(self.client.get(f"/tagihan/{invoice.pk}/").status_code, 404)
        login_as(self.client, self.admin)
        self.assertEqual(self.client.get(f"/tagihan/{invoice.pk}/").status_code, 200)

    def test_customer_cannot_see_master_and_owner_cannot_write(self):
        login_as(self.client, self.user)
        self.assertEqual(self.client.get("/pengaturan/toko/").status_code, 403)
        login_as(self.client, self.users["OWNER"])
        self.assertEqual(self.client.get("/pengaturan/toko/").status_code, 200)
        self.assertEqual(
            self.client.post("/pengaturan/toko/", {"business_name": "Changed"}).status_code, 403
        )

    def test_all_master_sections_render_and_old_store_link_uses_workspace(self):
        login_as(self.client, self.admin)
        for key in MASTERS:
            response = self.client.get(f"/pengaturan/{key}/")
            self.assertEqual(response.status_code, 200, key)
        response = self.client.get("/management/core/storesettings/")
        self.assertContains(response, "Informasi profil toko")
        self.assertNotContains(response, 'id="django-admin-form-add-constants"')

    def test_store_editor_saves_hours_and_audits_without_json_input(self):
        login_as(self.client, self.admin)
        response = self.client.post(
            "/pengaturan/toko/",
            {
                "business_name": "Sinau Satwa Baru",
                "cs_whatsapp": "628123456789",
                "address": "Alamat toko baru",
                "latitude": "-6.2",
                "longitude": "106.8",
                "timezone": "Asia/Jakarta",
                "public_contact_ready": "on",
                "open_0": "08:00",
                "close_0": "18:00",
            },
        )
        self.assertEqual(response.status_code, 302, response.content[:200])
        store = StoreSettings.objects.get(pk=1)
        self.assertEqual(store.opening_hours, {"0": ["08:00", "18:00"]})
        self.assertTrue(store.public_contact_ready)

    def test_document_replacement_resets_verification_preserves_old_file_and_ownership(self):
        bk = booking(self, "BOARDING")
        stay = BoardingStay.objects.get(booking=bk)
        first = replace_intake(self.user, stay, self.image())
        verify_intake(self.admin, first, timezone.localdate(bk.ends_at), "OK")
        with self.assertRaises(BusinessError):
            replace_intake(self.other, stay, self.image(), first)
        revised = replace_intake(self.user, stay, self.image(), first)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertIsNone(revised.verified_at)
        self.assertTrue(PrivateFile.objects.filter(pk=first.file_id).exists())
        with self.assertRaises(BusinessError):
            approve_stay(self.admin, stay, self.unit, self.users["CARETAKER"])

    def test_verified_document_has_no_verification_form(self):
        bk = booking(self, "BOARDING")
        stay = BoardingStay.objects.get(booking=bk)
        document = replace_intake(self.user, stay, self.image())
        verify_intake(self.admin, document, timezone.localdate(bk.ends_at), "OK")
        login_as(self.client, self.admin)
        response = self.client.get(f"/booking/{bk.pk}/")
        self.assertContains(response, "Terverifikasi")
        self.assertNotContains(response, 'value="intake_verify"')
        self.assertContains(response, "Ganti dokumen")
        with self.assertRaises(BusinessError):
            verify_intake(self.admin, document, timezone.localdate(bk.ends_at), "repeat")

    def test_otp_is_html_plus_plain_text_without_purpose_codes(self):
        issue_otp(self.user, "RESET")
        deliver_outbox()
        message = mail.outbox[-1]
        self.assertIn("Kode verifikasi Anda:", message.body)
        html = message.alternatives[0][0]
        self.assertIn("RESET PASSWORD", html)
        self.assertIn("5 menit", html)
        self.assertNotIn("http://", html)

    def test_master_refund_is_unavailable_and_super_admin_lists_customers(self):
        login_as(self.client, self.users["SUPER_ADMIN"])
        response = self.client.get("/operasional/akun/")
        # Resolve by name rather than assuming a URL spelling in the workspace.
        from django.urls import reverse

        response = self.client.get(reverse("staff_accounts"))
        self.assertContains(response, self.user.email)
        self.assertEqual(self.client.get("/management/billing/refund/").status_code, 404)

    def test_public_shell_has_no_environment_provider_or_technical_expiry_copy(self):
        for path in ["/", "/login/", "/katalog/"]:
            response = self.client.get(path)
            for text in ["Lingkungan lokal", "Midtrans", "kedaluwarsa"]:
                self.assertNotContains(response, text)

    def test_invalid_replacement_keeps_verified_document_active(self):
        bk = booking(self, "BOARDING")
        stay = BoardingStay.objects.get(booking=bk)
        document = replace_intake(self.user, stay, self.image())
        verify_intake(self.admin, document, timezone.localdate(bk.ends_at), "OK")
        count = PrivateFile.objects.count()
        bad = SimpleUploadedFile("bad.pdf", b"not a pdf", content_type="application/pdf")
        with self.assertRaises(BusinessError):
            replace_intake(self.user, stay, bad, document)
        document.refresh_from_db()
        self.assertTrue(document.is_active)
        self.assertIsNotNone(document.verified_at)
        self.assertEqual(PrivateFile.objects.count(), count)

    def test_removed_default_address_promotes_an_active_address(self):
        self.address.is_default = True
        self.address.save()
        backup = Address.objects.get(pk=self.address.pk)
        backup.pk = None
        backup.is_default = False
        backup.label = "Kantor"
        backup.save()
        login_as(self.client, self.user)
        self.client.post(f"/alamat/{self.address.pk}/hapus/")
        backup.refresh_from_db()
        self.assertTrue(backup.is_default)
        self.assertEqual(Address.objects.filter(customer=self.customer, is_default=True).count(), 1)

    def test_cancelled_order_hides_invoice_link_and_rejects_direct_invoice(self):
        invoice = self.invoice()
        invoice.order.status = "CANCELED"
        invoice.order.save()
        login_as(self.client, self.user)
        self.assertEqual(self.client.get(f"/tagihan/{invoice.pk}/").status_code, 404)
        response = self.client.get(f"/pesanan/{invoice.order_id}/")
        self.assertNotContains(response, f'href="/tagihan/{invoice.pk}/"')

    def test_removed_actions_cannot_create_refund_or_check_provider(self):
        invoice = self.invoice()
        login_as(self.client, self.admin)
        from billing.models import Refund

        with patch("billing.services.reconcile_attempt") as reconcile:
            self.client.post(f"/tagihan/{invoice.pk}/", {"action": "check"})
            self.client.post(
                f"/tagihan/{invoice.pk}/", {"action": "refund_request", "amount": "10000"}
            )
            reconcile.assert_not_called()
        self.assertEqual(Refund.objects.count(), 0)

    def test_invoice_poll_is_owned_readonly_and_does_not_contact_provider(self):
        invoice = self.invoice()
        login_as(self.client, self.other)
        self.assertEqual(self.client.get(f"/tagihan/{invoice.pk}/status/").status_code, 404)
        login_as(self.client, self.user)
        with patch("billing.services.reconcile_attempt") as reconcile:
            response = self.client.get(f"/tagihan/{invoice.pk}/status/")
            self.assertEqual(response.json()["status"], "UNPAID")
            self.assertFalse(response.json()["closed"])
            reconcile.assert_not_called()
        self.assertEqual(self.client.post(f"/tagihan/{invoice.pk}/status/").status_code, 405)

    def test_pet_photo_rejects_pdf_instead_of_rendering_a_broken_image(self):
        from customers.forms import PetForm

        form = PetForm(
            {"name": "Milo", "species": self.cat.pk, "sex": "MALE"},
            {
                "photo": SimpleUploadedFile(
                    "photo.pdf", b"%PDF-not-image", content_type="application/pdf"
                )
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("photo", form.errors)

    def test_stale_pet_object_cannot_book_after_archive(self):
        from customers.models import Pet

        Pet.objects.filter(pk=self.pet.pk).update(is_active=False)
        with self.assertRaises(BusinessError):
            booking(self)

    def test_stale_address_object_cannot_create_a_new_delivery(self):
        Address.objects.filter(pk=self.address.pk).update(is_active=False)
        with self.assertRaises(BusinessError):
            draft_order(self.user, {str(self.variant.pk): 1}, "DELIVERY", self.address)
