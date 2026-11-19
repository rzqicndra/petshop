"""The published cutoff, offered slots and final reservation use the same policy."""

from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from billing.models import Invoice
from core.models import StoreSettings
from core.services import BusinessError
from scheduling.availability import reschedule_window, slot_picker
from scheduling.models import ResourceReservation
from scheduling.services import reschedule_booking
from .factories import fixture, booking, login_as, pay


@override_settings(REQUIRE_STAFF_MFA=False)
class ReschedulePolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def paid_booking(self, start=None):
        item = booking(self, start=start or self.start)
        pay(Invoice.objects.get(booking=item))
        item.refresh_from_db()
        return item

    def allocations(self, item):
        return list(
            ResourceReservation.objects.filter(booking=item)
            .order_by("pk")
            .values_list("pk", "resource_id", "period", "status", "expires_at")
        )

    def test_original_cutoff_uses_locked_record_for_customer_and_staff(self):
        stale = self.paid_booking()
        # Another request already moved the booking closer to its start.
        type(stale).objects.filter(pk=stale.pk).update(starts_at=self.start - timedelta(hours=1))
        before = self.allocations(stale)
        with patch("django.utils.timezone.now", return_value=self.start - timedelta(hours=2)):
            for actor in (self.user, self.admin):
                with self.subTest(actor=actor.email):
                    with self.assertRaisesMessage(BusinessError, "2 jam sebelum"):
                        reschedule_booking(
                            actor, stale, self.start + timedelta(hours=2), stale.version
                        )
        stale.refresh_from_db()
        self.assertEqual(stale.starts_at, self.start - timedelta(hours=1))
        self.assertEqual(self.allocations(stale), before)

    def test_exact_cutoff_allowed_and_one_microsecond_later_hides_choices(self):
        item = self.paid_booking()
        now = self.start - timedelta(hours=2)
        with patch("django.utils.timezone.now", return_value=now):
            self.assertTrue(reschedule_window(item)["allowed"])
            reschedule_booking(self.user, item, self.start + timedelta(minutes=15), item.version)
        item.refresh_from_db()
        self.assertEqual(item.starts_at, self.start + timedelta(minutes=15))
        with patch(
            "django.utils.timezone.now",
            return_value=item.starts_at - timedelta(hours=2) + timedelta(microseconds=1),
        ):
            self.assertFalse(reschedule_window(item)["allowed"])
            self.assertFalse(slot_picker(item.package, item.pet, exclude=item)["slot_days"])

    def test_replacement_must_also_meet_notice_and_is_filtered_from_picker(self):
        item = self.paid_booking(self.start + timedelta(hours=4))
        before = self.allocations(item)
        with patch("django.utils.timezone.now", return_value=self.start):
            values = {
                slot["value"]
                for day in slot_picker(item.package, item.pet, exclude=item)["slot_days"]
                for slot in day["slots"]
            }
            self.assertNotIn((self.start + timedelta(minutes=105)).isoformat(), values)
            self.assertIn((self.start + timedelta(minutes=120)).isoformat(), values)
            with self.assertRaisesMessage(BusinessError, "minimal 2 jam dari sekarang"):
                reschedule_booking(
                    self.user, item, self.start + timedelta(minutes=105), item.version
                )
            self.assertEqual(self.allocations(item), before)
            reschedule_booking(self.user, item, self.start + timedelta(minutes=120), item.version)
        item.refresh_from_db()
        self.assertEqual(item.starts_at, self.start + timedelta(hours=2))

    def test_final_capacity_check_rolls_back_old_reservations(self):
        item = self.paid_booking()
        version = item.version
        target = self.start + timedelta(hours=2)
        booking(self, actor=self.other, pet=self.pet2, start=target)
        before = self.allocations(item)
        with self.assertRaises(BusinessError):
            reschedule_booking(self.user, item, target, item.version)
        item.refresh_from_db()
        self.assertEqual(item.starts_at, self.start)
        self.assertEqual(item.version, version)
        self.assertEqual(self.allocations(item), before)

    def test_edited_notice_applies_immediately_and_out_of_range_is_rejected(self):
        item = self.paid_booking()
        store = StoreSettings.objects.get(pk=1)
        store.reschedule_notice_minutes = 90
        store.save()
        now = self.start - timedelta(minutes=100)
        with patch("django.utils.timezone.now", return_value=now):
            self.assertTrue(reschedule_window(item)["allowed"])
            self.assertEqual(reschedule_window(item)["notice"], "1 jam 30 menit")
            store.reschedule_notice_minutes = 180
            store.save()
            self.assertFalse(reschedule_window(item)["allowed"])
        for value in (0, 14, 1441):
            store.reschedule_notice_minutes = value
            with self.assertRaises(ValidationError):
                store.full_clean()
            with self.assertRaises(IntegrityError), transaction.atomic():
                StoreSettings.objects.filter(pk=1).update(reschedule_notice_minutes=value)

    def test_operations_can_publish_the_notice_from_store_settings(self):
        login_as(self.client, self.admin)
        response = self.client.get("/pengaturan/toko/")
        self.assertContains(response, 'name="reschedule_notice_minutes"')
        response = self.client.post(
            "/pengaturan/toko/",
            {
                "business_name": "Sinau Satwa",
                "timezone": "Asia/Jakarta",
                "reschedule_notice_minutes": "90",
                "attendance_grace_minutes": "15",
                **{f"open_{day}": "08:00" for day in range(7)},
                **{f"close_{day}": "20:00" for day in range(7)},
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StoreSettings.objects.get(pk=1).reschedule_notice_minutes, 90)

    def test_payment_labels_and_cutoff_are_consistent_with_post_permissions(self):
        item = booking(self)
        invoice = Invoice.objects.get(booking=item)
        url = f"/booking/{item.pk}/"
        login_as(self.client, self.user)
        self.assertContains(self.client.get(url), "Lanjutkan pembayaran")
        pay(invoice)
        item.refresh_from_db()
        response = self.client.get(url)
        self.assertContains(response, "Lihat pembayaran")
        self.assertContains(response, "Ubah jadwal kunjungan")
        self.assertNotContains(response, "Buka tagihan")
        self.assertNotContains(response, "Slot disimpan")
        self.assertNotContains(response, "Waktu toko ·")
        with patch(
            "django.utils.timezone.now", return_value=item.starts_at - timedelta(minutes=119)
        ):
            login_as(self.client, self.user)
            response = self.client.get(url)
            self.assertContains(response, "Perubahan jadwal ditutup")
            self.assertNotContains(response, 'name="starts_at"')
            response = self.client.post(
                url,
                {
                    "action": "reschedule",
                    "version": item.version,
                    "starts_at": (self.start + timedelta(hours=2)).isoformat(),
                },
            )
            self.assertContains(response, "2 jam sebelum layanan")
        item.refresh_from_db()
        self.assertEqual(item.starts_at, self.start)
        login_as(self.client, self.admin)
        response = self.client.get(url)
        self.assertContains(response, "Lihat transaksi")
        self.assertNotContains(response, "Lanjutkan pembayaran")
        self.assertNotContains(response, "Ubah jadwal kunjungan")
        login_as(self.client, self.users["DOCTOR"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, f'href="/tagihan/{invoice.pk}/"')
        login_as(self.client, self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
