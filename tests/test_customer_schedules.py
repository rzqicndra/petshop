from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from billing.models import Invoice
from billing.services import request_refund, process_refund
from care.models import Visit
from care.services import record_attendance, start_care, save_medical
from core.models import StoreSettings
from core.services import BusinessError
from delivery.routing import directions_base_url
from delivery.services import quote_order
from orders.models import Order
from orders.services import draft_order
from scheduling.availability import public_timetable, slot_picker
from scheduling.models import PackageResource, Resource, ResourceReservation, StaffShift
from scheduling.services import create_booking, reschedule_booking
from psycopg.types.range import Range
from .factories import fixture, booking, login_as, pay


class AppointmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def times(self, kind="VET", pet=None, **kwargs):
        return {
            slot["value"]
            for day in slot_picker(self.packages[kind], pet or self.pet, **kwargs)["slot_days"]
            for slot in day["slots"]
        }

    def test_last_date_inclusive_from_store_today_and_next_day_rejected(self):
        seventh = self.start + timedelta(days=6)
        robot = Resource.objects.get(code="DOCTOR")
        StaffShift.objects.create(
            resource=robot,
            starts_at=seventh,
            ends_at=seventh + timedelta(hours=2),
            is_available=True,
        )
        self.assertIn(seventh.isoformat(), self.times())
        booking(self, start=seventh)
        with self.assertRaisesMessage(BusinessError, "tujuh hari"):
            booking(self, start=seventh + timedelta(days=1))

    def test_first_day_releases_past_slots_using_store_timezone(self):
        now = self.start + timedelta(minutes=4)
        with patch("django.utils.timezone.now", return_value=now):
            times = self.times()
        self.assertNotIn(self.start.isoformat(), times)
        self.assertIn((self.start + timedelta(minutes=15)).isoformat(), times)

    def test_held_slot_and_cleanup_unavailable_but_normal_capacity_returns_after_expiry(self):
        booking(self, actor=self.other, pet=self.pet2)
        times = self.times()
        self.assertNotIn(self.start.isoformat(), times)
        self.assertNotIn((self.start + timedelta(hours=1)).isoformat(), times)
        self.assertIn((self.start + timedelta(minutes=75)).isoformat(), times)
        with patch(
            "django.utils.timezone.now", return_value=timezone.now() + timedelta(minutes=16)
        ):
            self.assertIn(self.start.isoformat(), self.times())

    def test_slot_blocked_by_pet_across_services_and_reschedule_excludes_own_hold(self):
        old = booking(self)
        pay(Invoice.objects.get(booking=old))
        old.refresh_from_db()
        self.assertNotIn(self.start.isoformat(), self.times("GROOMING"))
        next_start = self.start + timedelta(minutes=15)
        self.assertNotIn(next_start.isoformat(), self.times())
        self.assertIn(next_start.isoformat(), self.times(exclude=old))
        reschedule_booking(self.user, old, next_start, old.version)

    def test_second_doctor_can_serve_another_pet_but_facility_still_limits(self):
        from accounts.models import User

        doctor = User.objects.create_user(email="vet-two@example.test", full_name="Dokter kedua")
        doctor.groups.add(self.users["DOCTOR"].groups.get(name="DOCTOR"))
        res = Resource.objects.create(code="D2", kind="STAFF", staff_user=doctor)
        pkg = self.packages["VET"]
        PackageResource.objects.create(package=pkg, resource=res, pool="STAFF")
        StaffShift.objects.create(
            resource=res,
            starts_at=self.start,
            ends_at=self.start + timedelta(hours=3),
            is_available=True,
        )
        booking(self, actor=self.other, pet=self.pet2)
        self.assertIn(self.start.isoformat(), self.times())
        facility = Resource.objects.create(code="ROOM-TWO", kind="STATION")
        PackageResource.objects.create(package=pkg, resource=facility, pool="ROOM")
        facility.is_active = False
        facility.save()
        self.assertNotIn(self.start.isoformat(), self.times())
        with self.assertRaises(BusinessError):
            booking(self)

    def test_breaks_store_closure_and_unpublished_shift_never_offer_a_date(self):
        doctor = Resource.objects.get(code="DOCTOR")
        StaffShift.objects.create(
            resource=doctor,
            starts_at=self.start,
            ends_at=self.start + timedelta(hours=1),
            is_available=False,
        )
        self.assertNotIn(self.start.isoformat(), self.times())
        day = self.start.date()
        row = next(d for d in public_timetable()["days"] if d["day"] == day)
        self.assertIn("08:00–10:00, 11:00–20:00", [s["times"] for s in row["staff"]])
        store = StoreSettings.objects.get()
        store.opening_hours.pop(str(day.weekday()))
        store.save()
        self.assertNotIn(
            day.isoformat(),
            [d["value"] for d in slot_picker(self.packages["VET"], self.pet)["slot_days"]],
        )
        self.assertFalse(next(d for d in public_timetable()["days"] if d["day"] == day)["staff"])

    def test_full_day_not_offered_when_only_staff_has_a_block(self):
        start = self.start.replace(hour=8)
        end = start.replace(hour=20)
        ResourceReservation.objects.create(
            resource=Resource.objects.get(code="DOCTOR"),
            period=Range(start, end, "[)"),
            status="BLOCKED",
        )
        self.assertNotIn(
            start.date().isoformat(),
            [row["value"] for row in slot_picker(self.packages["VET"], self.pet)["slot_days"]],
        )

    def test_appointment_page_and_post_enforce_package_duration_and_grid(self):
        login_as(self.client, self.user)
        path = "/booking/baru/"
        vet = self.packages["VET"]
        response = self.client.get(
            path, {"paket": vet.pk, "pet": self.pet.pk, "hari": self.start.date().isoformat()}
        )
        self.assertContains(response, "10:00–11:00")
        self.assertNotContains(response, 'name="checkout_at"')
        with self.assertRaisesMessage(BusinessError, "salah satu jam"):
            booking(self, start=self.start + timedelta(minutes=1))
        vet.duration_minutes = 61
        with self.assertRaises(ValidationError):
            vet.full_clean()
        vet.save()
        self.assertFalse(self.times())
        with self.assertRaisesMessage(BusinessError, "Durasi paket"):
            booking(self)

    def test_boarding_dates_user_selected_beyond_a_week(self):
        login_as(self.client, self.user)
        response = self.client.get("/booking/baru/", {"paket": self.packages["BOARDING"].pk})
        self.assertContains(response, 'name="checkout_at"')
        self.assertNotContains(response, 'class="time-slots"')
        checkin = self.start + timedelta(days=24)
        checkout = checkin + timedelta(days=4, hours=2)
        stay = create_booking(
            self.user,
            self.pet,
            self.packages["BOARDING"],
            checkin,
            checkout,
            str(uuid4()),
            emergency={"phone": "62666666666", "consent": True},
        )
        self.assertEqual((stay.status, stay.ends_at), ("SUBMITTED", checkout))

    def test_timetable_is_public_and_private_booking_information_is_absent(self):
        bk = booking(self)
        response = self.client.get("/jadwal/")
        self.assertContains(response, "Dokter hewan")
        self.assertNotContains(response, bk.code)
        self.assertNotContains(response, self.users["DOCTOR"].email)

    def test_paid_booking_help_replaces_dead_cancel_then_appears_when_fully_returned(self):
        bk = booking(self)
        invoice = Invoice.objects.get(booking=bk)
        payment = pay(invoice)
        url = f"/booking/{bk.pk}/"
        login_as(self.client, self.user)
        self.assertContains(self.client.get(url), "Hubungi toko")
        login_as(self.client, self.admin)
        self.assertNotContains(self.client.get(url), 'value="cancel"')
        refund = request_refund(
            self.admin, payment, invoice.total_rp, "Permintaan pelanggan", "test-help"
        )
        process_refund(self.users["SUPER_ADMIN"], refund, "approve")
        process_refund(self.users["SUPER_ADMIN"], refund, "complete", "test-reference")
        self.assertContains(self.client.get(url), 'value="cancel"')
        login_as(self.client, self.user)
        self.assertNotContains(self.client.get(url), 'value="cancel"')

    def test_published_doctor_recommendation_is_visible_without_creating_a_stay(self):
        from boarding.models import BoardingStay

        bk = booking(self)
        pay(Invoice.objects.get(booking=bk))
        bk.refresh_from_db()
        with patch("django.utils.timezone.now", return_value=self.start):
            record_attendance(self.users["DOCTOR"], bk, "PRESENT")
            start_care(self.users["DOCTOR"], bk)
        visit = Visit.objects.get(booking=bk)
        data = {
            name: "Catatan dokter"
            for name in ("complaint", "findings", "diagnosis", "treatment", "aftercare")
        }
        data["inpatient_recommended"] = True
        save_medical(self.users["DOCTOR"], visit, data)
        login_as(self.client, self.user)
        self.assertNotContains(
            self.client.get(f"/booking/{bk.pk}/"), "Dokter merekomendasikan rawat inap"
        )
        save_medical(self.users["DOCTOR"], visit, data, publish=True)
        self.assertContains(
            self.client.get(f"/booking/{bk.pk}/"), "Dokter merekomendasikan rawat inap"
        )
        self.assertFalse(BoardingStay.objects.filter(booking=bk).exists())


@override_settings(SHIPPING_MODE="mock", ROUTES_MODE="mock", MOCK_ROUTE_DISTANCE_M=3200)
class CustomerCheckoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def setUp(self):
        login_as(self.client, self.user)
        session = self.client.session
        session["cart"] = {str(self.variant.pk): 1}
        session.save()

    def prepare(self, method):
        response = self.client.post(
            "/checkout/",
            {
                "action": "prepare",
                "fulfillment": method,
                "address": self.address.pk,
                "key": str(uuid4()),
            },
        )
        self.assertIsNotNone(response.context["draft"])
        return response.context

    def confirm(self, prepared, method, **fields):
        return self.client.post(
            "/checkout/",
            {
                "action": "confirm",
                "draft": prepared["draft"].pk,
                "key": str(uuid4()),
                "fulfillment": method,
                **fields,
            },
        )

    def test_delivery_to_pickup_rejects_stale_confirmation_and_clears_fee(self):
        prepared = self.prepare("DELIVERY")
        quote = prepared["quotes"][0]
        self.assertContains(self.confirm(prepared, "PICKUP", quote=quote.pk), "Klik Lanjutkan")
        picked = self.prepare("PICKUP")
        self.assertFalse(picked["quotes"])
        self.assertContains(self.confirm(picked, "PICKUP", quote=quote.pk), "Pilihan kurir")
        self.assertEqual(self.confirm(picked, "PICKUP").status_code, 302)
        order = Order.objects.get(status="AWAITING_PAYMENT")
        self.assertEqual((order.fulfillment, order.shipping_rp), ("PICKUP", 0))

    def test_new_draft_in_second_tab_cannot_confirm_previous_draft(self):
        old = self.prepare("PICKUP")
        self.prepare("PICKUP")
        self.assertContains(self.confirm(old, "PICKUP"), "Pilihan checkout berubah")
        self.assertFalse(Invoice.objects.exists())

    def test_changed_or_deleted_address_rejects_old_shipping_price(self):
        ctx = self.prepare("DELIVERY")
        self.address.address_line = "Alamat berubah"
        self.address.save()
        self.assertContains(
            self.confirm(ctx, "DELIVERY", address=self.address.pk, quote=ctx["quotes"][0].pk),
            "Alamat pengiriman berubah",
        )
        self.address.is_active = False
        self.address.save()
        self.assertEqual(
            self.confirm(
                ctx, "DELIVERY", address=self.address.pk, quote=ctx["quotes"][0].pk
            ).status_code,
            200,
        )
        self.assertFalse(Invoice.objects.exists())

    def test_real_confirmation_uses_only_quote_for_owned_draft(self):
        old = self.prepare("DELIVERY")
        new = self.prepare("DELIVERY")
        self.assertContains(
            self.confirm(new, "DELIVERY", address=self.address.pk, quote=old["quotes"][0].pk),
            "Hitung kembali",
        )
        self.assertContains(
            self.confirm(new, "DELIVERY", address=self.address.pk, quote="invalid"), "Pilih kurir"
        )
        quote = new["quotes"][0]
        self.assertEqual(
            self.confirm(new, "DELIVERY", address=self.address.pk, quote=quote.pk).status_code, 302
        )
        self.assertEqual(Order.objects.get(status="AWAITING_PAYMENT").shipping_rp, quote.fee_rp)

    def test_official_legacy_base_already_prefixed_and_custom_installation(self):
        for base, expected in [
            ("https://api.heigit.org", "https://api.heigit.org/openrouteservice"),
            ("https://api.heigit.org/openrouteservice/", "https://api.heigit.org/openrouteservice"),
            ("https://routing.example.test/ors/", "https://routing.example.test/ors"),
        ]:
            with self.subTest(base=base), override_settings(ORS_BASE_URL=base):
                self.assertEqual(directions_base_url(), expected)

    @patch("delivery.providers.route_distance")
    def test_ineligible_package_skips_route_request_and_keeps_instant_rates(self, route):
        self.policy.max_weight_g = 1
        self.policy.save()
        draft = draft_order(self.user, {str(self.variant.pk): 1}, "DELIVERY", self.address)
        quotes, notes = quote_order(draft)
        self.assertTrue(notes)
        self.assertEqual({q.method for q in quotes}, {"INSTANT"})
        route.assert_not_called()
