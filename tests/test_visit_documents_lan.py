import io
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, TransactionTestCase, SimpleTestCase, override_settings
from django.utils import timezone
from pypdf import PdfReader

from billing.models import Invoice, InvoiceLine
from care.models import Visit, MedicalRecordVersion
from care.services import record_attendance, start_care, save_medical
from core.models import StoreSettings
from core.services import BusinessError
from engagement.models import Reminder, Review
from scheduling.availability import slot_picker
from scheduling.models import Booking, ResourceReservation
from scheduling.services import reschedule_booking
from scripts.enable_lan import lan_environment, environment_values
from .factories import fixture, booking, pay, login_as


@override_settings(REQUIRE_STAFF_MFA=False)
class AttendanceAndDocumentsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def confirmed(self):
        item = booking(self)
        pay(Invoice.objects.get(booking=item))
        item.refresh_from_db()
        return item

    def pdf_text(self, response):
        self.assertEqual(response.status_code, 200)
        return "\n".join(
            page.extract_text()
            for page in PdfReader(io.BytesIO(b"".join(response.streaming_content))).pages
        )

    def test_attendance_requires_assigned_doctor_and_arrival_before_start(self):
        item = self.confirmed()
        with patch("django.utils.timezone.now", return_value=self.start):
            with self.assertRaisesMessage(BusinessError, "Konfirmasi pelanggan hadir"):
                start_care(self.users["DOCTOR"], item)
            for actor in (self.user, self.admin, self.users["GROOMER"]):
                with self.assertRaises(PermissionDenied):
                    record_attendance(actor, item, "PRESENT")
        with patch("django.utils.timezone.now", return_value=self.start - timedelta(minutes=31)):
            with self.assertRaises(BusinessError):
                record_attendance(self.users["DOCTOR"], item, "PRESENT")
        with patch("django.utils.timezone.now", return_value=self.start - timedelta(minutes=30)):
            record_attendance(self.users["DOCTOR"], item, "PRESENT")
            item.refresh_from_db()
            self.assertEqual(item.status, "CONFIRMED")
            start_care(self.users["DOCTOR"], item)
            with self.assertRaises(BusinessError):
                record_attendance(
                    self.users["DOCTOR"], item, "ABSENT", "Cannot change after check-in"
                )
        item.refresh_from_db()
        self.assertEqual(item.status, "IN_SERVICE")

    def test_absence_closes_visit_frees_capacity_and_preserves_payment(self):
        item = self.confirmed()
        invoice = Invoice.objects.get(booking=item)
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(minutes=14)):
            with self.assertRaisesMessage(BusinessError, "15 menit"):
                record_attendance(self.users["DOCTOR"], item, "ABSENT", "Not arrived")
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(minutes=15)):
            with self.assertRaisesMessage(BusinessError, "catatan"):
                record_attendance(self.users["DOCTOR"], item, "ABSENT")
            record_attendance(self.users["DOCTOR"], item, "ABSENT", "PRIVATE-ATTENDANCE-NOTE")
            self.assertIn(
                (self.start + timedelta(minutes=30)).isoformat(),
                {
                    s["value"]
                    for d in slot_picker(item.package, item.pet)["slot_days"]
                    for s in d["slots"]
                },
            )
            with self.assertRaises(BusinessError):
                start_care(self.users["DOCTOR"], item)
            with self.assertRaises(BusinessError):
                reschedule_booking(self.user, item, self.start + timedelta(hours=3), item.version)
            login_as(self.client, self.user)
            response = self.client.get(f"/booking/{item.pk}/")
            self.assertContains(response, "Tidak hadir")
            self.assertNotContains(response, "PRIVATE-ATTENDANCE-NOTE")
            self.assertContains(response, "Lihat pembayaran")
        item.refresh_from_db()
        invoice.refresh_from_db()
        self.assertEqual(item.status, "NO_SHOW")
        self.assertEqual(invoice.status, "PAID")
        self.assertFalse(
            ResourceReservation.objects.filter(booking=item).exclude(status="RELEASED").exists()
        )
        self.assertFalse(Reminder.objects.filter(booking=item, status="PENDING").exists())
        self.assertFalse(MedicalRecordVersion.objects.filter(visit__booking=item).exists())

    def test_attendance_tolerance_is_dynamic_and_stale_doctor_is_rejected(self):
        item = self.confirmed()
        StoreSettings.objects.filter(pk=1).update(attendance_grace_minutes=40)
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(minutes=20)):
            with self.assertRaisesMessage(BusinessError, "40 menit"):
                record_attendance(self.users["DOCTOR"], item, "ABSENT", "Not arrived")
        Visit.objects.filter(booking=item).update(doctor=self.admin)
        with patch("django.utils.timezone.now", return_value=self.start):
            with self.assertRaisesMessage(BusinessError, "ditugaskan"):
                record_attendance(self.users["DOCTOR"], item, "PRESENT")

    def test_doctor_ui_hides_start_until_attendance_then_post_starts(self):
        item = self.confirmed()
        url = f"/booking/{item.pk}/"
        with patch("django.utils.timezone.now", return_value=self.start):
            login_as(self.client, self.users["DOCTOR"])
            response = self.client.get(url)
            self.assertContains(response, "Pelanggan hadir")
            self.assertNotContains(response, 'value="start"')
            response = self.client.post(url, {"action": "attendance", "attendance": "PRESENT"})
            self.assertEqual(response.status_code, 302)
            self.assertContains(self.client.get(url), 'value="start"')
            self.assertEqual(self.client.post(url, {"action": "start"}).status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, "IN_SERVICE")

    def test_invoice_pdf_matches_items_and_ownership_without_provider_names(self):
        item = self.confirmed()
        invoice = Invoice.objects.get(booking=item)
        login_as(self.client, self.user)
        html = self.client.get(f"/tagihan/{invoice.pk}/")
        self.assertContains(html, "INVOICE")
        self.assertContains(html, "Harga satuan")
        self.assertContains(html, "Unduh PDF")
        url = f"/tagihan/{invoice.pk}/pdf/"
        content = self.pdf_text(self.client.get(url))
        for value in (invoice.code, "INVOICE", "Lunas", "100.000", "Halaman 1"):
            self.assertIn(value, content)
        self.assertNotIn("Midtrans", content)
        self.assertEqual(self.client.post(url).status_code, 405)
        login_as(self.client, self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        login_as(self.client, self.users["DOCTOR"])
        self.assertEqual(self.client.get(url).status_code, 404)
        login_as(self.client, self.users["OWNER"])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_closed_invoice_cannot_be_exported_by_customer(self):
        item = booking(self)
        invoice = Invoice.objects.get(booking=item)
        login_as(self.client, self.user)
        url = f"/tagihan/{invoice.pk}/pdf/"
        Invoice.objects.filter(pk=invoice.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.client.get(url).status_code, 404)
        Invoice.objects.filter(pk=invoice.pk).update(status="PAID")
        Booking.objects.filter(pk=item.pk).update(status="CANCELED")
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_invoice_pdf_wraps_long_lines_and_repeats_headers(self):
        from billing.documents import invoice_document

        item = self.confirmed()
        invoice = Invoice.objects.get(booking=item)
        line = InvoiceLine.objects.filter(invoice=invoice).first()
        line.description = "Deskripsi panjang <aman> & teruji. " * 25
        line.save()
        for i in range(16):
            InvoiceLine.objects.create(
                invoice=invoice,
                description=f"Item {i} " + line.description,
                quantity=1,
                unit_amount_rp=0,
                line_total_rp=0,
            )
        data = invoice_document(invoice)
        pages = PdfReader(data).pages
        self.assertGreater(len(pages), 1)
        self.assertIn("Terima kasih", pages[-1].extract_text())
        self.assertIn("Halaman 2", pages[1].extract_text())


class PublicRatingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def test_summary_filters_only_published_reviews_and_rating_input_remains_owned(self):
        first = booking(self)
        second = booking(self, start=self.start + timedelta(days=1))
        third = booking(self, start=self.start + timedelta(days=2))
        for item in (first, second, third):
            pay(Invoice.objects.get(booking=item))
            Booking.objects.filter(pk=item.pk).update(status="COMPLETED")
        for item, rating, status, comment in [
            (first, 5, "PUBLISHED", "Sangat baik"),
            (second, 1, "PUBLISHED", "Perlu perhatian"),
            (third, 5, "HIDDEN", "HIDDEN-RATING-COMMENT"),
        ]:
            Review.objects.create(
                customer=self.customer, booking=item, rating=rating, status=status, comment=comment
            )
        response = self.client.get("/ulasan/?rating=1")
        self.assertEqual(response.context["rating_summary"]["total"], 2)
        self.assertEqual(response.context["rating_summary"]["average"], 3)
        self.assertEqual(len(response.context["reviews"]), 1)
        self.assertNotContains(response, "HIDDEN-RATING-COMMENT")
        self.assertContains(response, "Perlu perhatian")
        login_as(self.client, self.user)
        response = self.client.get(f"/ulasan/tulis/booking/{first.pk}/")
        self.assertContains(response, 'type="radio"', count=5)
        self.assertContains(response, 'name="comment"')
        response = self.client.post(
            f"/ulasan/tulis/booking/{first.pk}/", {"rating": 6, "comment": "Tidak valid"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Review.objects.get(booking=first).rating, 5)
        login_as(self.client, self.other)
        self.assertEqual(self.client.get(f"/ulasan/tulis/booking/{first.pk}/").status_code, 404)


class LanConfigurationTests(SimpleTestCase):
    def test_lan_keeps_existing_integrations_and_rejects_public_or_production(self):
        original = "DEPLOYMENT_MODE=local\nWEB_PORT=18000\nSECRET_KEY=never-echo-this\nAPP_URL=http://localhost:18000\nALLOWED_HOSTS=localhost,tunnel.example\nCSRF_TRUSTED_ORIGINS=https://tunnel.example\n"
        updated, url, port = lan_environment(original, "192.168.1.10")
        values = environment_values(updated)
        self.assertEqual(url, "http://192.168.1.10:18000")
        self.assertEqual(values["WEB_BIND_IP"], "0.0.0.0")
        self.assertEqual(values["APP_URL"], "http://localhost:18000")
        self.assertEqual(values["SECRET_KEY"], "never-echo-this")
        self.assertIn("192.168.1.10", values["ALLOWED_HOSTS"].split(","))
        self.assertIn("https://tunnel.example", values["CSRF_TRUSTED_ORIGINS"])
        for host in ("8.8.8.8", "0.0.0.0", "127.0.0.1", "::1", "example.com"):
            with self.assertRaises(ValueError):
                lan_environment(original, host)
        with self.assertRaises(ValueError):
            lan_environment(original.replace("=local", "=production"), "192.168.1.10")
        self.assertEqual(lan_environment(updated, "192.168.1.10")[0], updated)

    def test_dry_run_never_writes_or_prints_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / ".env"
            original = "DEPLOYMENT_MODE=local\nSECRET_KEY=never-echo-this\nWEB_PORT=18000\n"
            target.write_text(original)
            result = subprocess.run(
                [
                    sys.executable,
                    str(settings.BASE_DIR / "scripts/enable_lan.py"),
                    "--env-file",
                    str(target),
                    "--host",
                    "192.168.1.10",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(target.read_text(), original)
            self.assertIn("http://192.168.1.10:18000", result.stdout)
            self.assertNotIn("never-echo-this", result.stdout + result.stderr)


class LanHttpTests(TestCase):
    @override_settings(
        ALLOWED_HOSTS=["192.168.1.10"], CSRF_TRUSTED_ORIGINS=["http://192.168.1.10:18000"]
    )
    def test_django_accepts_lan_host_and_csrf_form_submission(self):
        client = Client(enforce_csrf_checks=True)
        response = client.get("/login/", HTTP_HOST="192.168.1.10:18000")
        self.assertEqual(response.status_code, 200)
        response = client.post(
            "/login/",
            {
                "email": "invalid@example.test",
                "password": "invalid",
                "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
            },
            HTTP_HOST="192.168.1.10:18000",
            HTTP_ORIGIN="http://192.168.1.10:18000",
        )
        self.assertNotEqual(response.status_code, 403)


class AttendanceMigrationTests(TransactionTestCase):
    def test_migration_keeps_existing_examined_records_present(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        fixture(self)
        examined = booking(self)
        pending = booking(self, start=self.start + timedelta(days=1))
        Visit.objects.filter(booking=examined).update(examined_at=self.start)
        Booking.objects.filter(pk=examined.pk).update(status="IN_SERVICE")
        executor = MigrationExecutor(connection)
        executor.migrate([("care", "0002_medicalrecord_inpatient_recommendation")])
        try:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
            self.assertEqual(Visit.objects.get(booking=examined).attendance, "PRESENT")
            self.assertEqual(Visit.objects.get(booking=examined).attendance_at, self.start)
            self.assertEqual(Visit.objects.get(booking=pending).attendance, "PENDING")
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
