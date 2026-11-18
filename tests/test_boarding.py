from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from billing.models import Invoice
from boarding.models import BoardingStay, ExtensionRequest
from boarding.services import (
    request_extension,
    review_extension,
    stay_transition,
    approve_stay,
    reject_stay,
)
from scheduling.models import ResourceReservation, Booking
from engagement.models import Reminder
from core.services import BusinessError
from .factories import fixture, paid_stay, pay, booking


class BoardingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def checked_in(self):
        stay = paid_stay(self)
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(minutes=1)):
            stay_transition(self.users["CARETAKER"], stay, "checkin")
        stay.refresh_from_db()
        return stay

    def test_approval_requires_verified_documents(self):
        bk = booking(self, "BOARDING")
        stay = BoardingStay.objects.get(booking=bk)
        with self.assertRaises(BusinessError):
            approve_stay(self.admin, stay, self.unit, self.users["CARETAKER"])
        self.assertFalse(Invoice.objects.filter(booking=bk).exists())

    def test_rejection_requires_reason_and_preserves_customer_reason(self):
        bk = booking(self, "BOARDING")
        stay = BoardingStay.objects.get(booking=bk)
        with self.assertRaises(BusinessError):
            reject_stay(self.admin, stay, "")
        reject_stay(self.admin, stay, "Dokumen belum memenuhi syarat")
        bk.refresh_from_db()
        self.assertEqual(bk.status, "CANCELED")
        self.assertIn("rejection_reason", bk.policy_snapshot)

    def test_extension_changes_effective_checkout_only_after_payment_once(self):
        stay = self.checked_in()
        old = stay.booking.ends_at
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(minutes=2)):
            ext = request_extension(self.user, stay, old + timedelta(days=1))
            review_extension(self.admin, ext, True)
            stay.booking.refresh_from_db()
            self.assertEqual(stay.booking.ends_at, old)
            invoice = Invoice.objects.get(extension=ext)
            payment = pay(invoice)
            from billing.services import apply_settled_payment

            apply_settled_payment(
                payment.attempt, payment.provider_transaction_id, payment.amount_rp
            )
        stay.booking.refresh_from_db()
        ext.refresh_from_db()
        self.assertEqual(stay.booking.ends_at, old + timedelta(days=1))
        self.assertEqual(stay.booking.version, 2)
        self.assertEqual(ext.status, "ACTIVE")
        self.assertEqual(stay.booking.price_snapshot_rp, 375000)
        self.assertEqual(
            ResourceReservation.objects.get(
                booking=stay.booking, extension__isnull=True
            ).period.upper,
            old + timedelta(days=1, minutes=60),
        )
        self.assertEqual(
            Reminder.objects.filter(booking=stay.booking, status="PENDING").get().source_version, 2
        )

    def test_extension_reject_and_single_active_request(self):
        stay = self.checked_in()
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(minutes=2)):
            ext = request_extension(self.user, stay, stay.booking.ends_at + timedelta(days=1))
            with self.assertRaises(BusinessError):
                request_extension(self.user, stay, stay.booking.ends_at + timedelta(days=2))
            with self.assertRaises(BusinessError):
                review_extension(self.admin, ext, False, "")
            review_extension(self.admin, ext, False, "Unit penuh untuk periode tambahan")
        ext.refresh_from_db()
        self.assertEqual(ext.status, "REJECTED")
        self.assertFalse(Invoice.objects.filter(extension=ext).exists())

    def test_extension_expiry_releases_only_extra_period(self):
        stay = self.checked_in()
        old = stay.booking.ends_at
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(minutes=2)):
            ext = request_extension(self.user, stay, old + timedelta(days=1))
            review_extension(self.admin, ext, True)
        from billing.services import expire_unpaid

        with patch("django.utils.timezone.now", return_value=self.start + timedelta(hours=2)):
            expire_unpaid()
        ext.refresh_from_db()
        stay.booking.refresh_from_db()
        self.assertEqual(ext.status, "EXPIRED")
        self.assertEqual(stay.booking.ends_at, old)
        self.assertEqual(
            ResourceReservation.objects.get(booking=stay.booking, extension__isnull=True).status,
            "IN_USE",
        )

    def test_cleaning_period_blocks_following_stay(self):
        stay = paid_stay(self)
        from psycopg.types.range import Range
        from scheduling.services import BLOCKING

        collision = Range(
            stay.booking.ends_at + timedelta(minutes=30),
            stay.booking.ends_at + timedelta(hours=3),
            "[)",
        )
        self.assertTrue(
            ResourceReservation.objects.filter(
                resource=self.unit.resource, status__in=BLOCKING, period__overlap=collision
            ).exists()
        )

    def test_paid_late_extension_does_not_change_original_stay(self):
        stay = self.checked_in()
        old = stay.booking.ends_at
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(minutes=2)):
            ext = request_extension(self.user, stay, old + timedelta(days=1))
            review_extension(self.admin, ext, True)
        invoice = Invoice.objects.get(extension=ext)
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(hours=2)):
            payment = pay(invoice)
        stay.booking.refresh_from_db()
        ext.refresh_from_db()
        self.assertEqual(stay.booking.ends_at, old)
        self.assertEqual(ext.status, "NEEDS_ATTENTION")
        self.assertEqual(payment.handling_status, "NEEDS_ATTENTION")

    def test_late_extension_can_be_closed_after_refund(self):
        from billing.services import request_refund, process_refund

        stay = self.checked_in()
        old = stay.booking.ends_at
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(minutes=2)):
            ext = request_extension(self.user, stay, old + timedelta(days=1))
            review_extension(self.admin, ext, True)
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(hours=2)):
            payment = pay(Invoice.objects.get(extension=ext))
            with self.assertRaises(BusinessError):
                review_extension(self.admin, ext, False, "Belum refund")
            refund = request_refund(
                self.admin,
                payment,
                payment.amount_rp,
                "Kapasitas tambahan tidak aktif",
                "refund-extension",
            )
            process_refund(self.users["SUPER_ADMIN"], refund, "approve")
            process_refund(self.users["SUPER_ADMIN"], refund, "complete", "BANK-EXT")
            review_extension(
                self.admin, ext, False, "Dana tambahan dikembalikan; jadwal awal tetap"
            )
        ext.refresh_from_db()
        stay.booking.refresh_from_db()
        self.assertEqual(ext.status, "REJECTED")
        self.assertEqual(stay.booking.ends_at, old)
