import io
from datetime import timedelta
from unittest.mock import patch
from PIL import Image
from pypdf import PdfReader
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from core.files import store_upload
from core.models import AuditLog
from core.services import BusinessError
from billing.models import Invoice
from care.models import Visit, MedicalRecordVersion
from care.services import record_attendance, start_care, save_medical, finish_care
from engagement.models import Review
from engagement.services import save_review
from orders.services import draft_order, checkout, pack_order, handover_pickup
from orders.models import OrderItem
from .factories import fixture, booking, pay, login_as


class CareAndReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def medical(self):
        bk = booking(self)
        pay(Invoice.objects.get(booking=bk))
        bk.refresh_from_db()
        with patch("django.utils.timezone.now", return_value=self.start):
            record_attendance(self.users["DOCTOR"], bk, "PRESENT")
            start_care(self.users["DOCTOR"], bk)
        return Visit.objects.get(booking=bk)

    def data(self):
        return {
            "complaint": "Gatal",
            "findings": "Kulit memerah",
            "diagnosis": "Diagnosis uji dokter",
            "treatment": "Terapi sesuai dokter",
            "aftercare": "Panduan rumah untuk pemilik",
            "internal_note": "INTERNAL-SECRET-NOTE",
            "followup_at": self.start + timedelta(days=3),
            "revision_reason": "",
        }

    def test_draft_hidden_published_pdf_excludes_internal_notes(self):
        visit = self.medical()
        draft = save_medical(self.users["DOCTOR"], visit, self.data())
        login_as(self.client, self.user)
        response = self.client.get(f"/booking/{visit.booking_id}/")
        self.assertNotContains(response, "Diagnosis uji dokter")
        self.assertEqual(self.client.get(f"/rekam-medis/{draft.pk}/pdf/").status_code, 404)
        record = save_medical(self.users["DOCTOR"], visit, self.data(), publish=True)
        response = self.client.get(f"/rekam-medis/{record.pk}/pdf/")
        self.assertEqual(response.status_code, 200)
        pdf = b"".join(response.streaming_content)
        text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
        self.assertIn("Panduan rumah", text)
        self.assertNotIn("INTERNAL-SECRET-NOTE", text)
        login_as(self.client, self.other)
        self.assertEqual(self.client.get(f"/rekam-medis/{record.pk}/pdf/").status_code, 404)

    def test_published_record_immutable_revision_is_new_version(self):
        visit = self.medical()
        first = save_medical(self.users["DOCTOR"], visit, self.data(), publish=True)
        with self.assertRaises(DatabaseError), transaction.atomic():
            MedicalRecordVersion.objects.filter(pk=first.pk).update(diagnosis="Overwrite")
        data = self.data()
        data["diagnosis"] = "Revised diagnosis"
        data["revision_reason"] = "Hasil pemeriksaan lanjutan"
        second = save_medical(self.users["DOCTOR"], visit, data, publish=True)
        first.refresh_from_db()
        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)
        self.assertEqual(second.version_no, 2)
        self.assertEqual(first.diagnosis, "Diagnosis uji dokter")

    def test_doctor_required_and_finish_needs_published_record(self):
        visit = self.medical()
        with self.assertRaises(BusinessError):
            finish_care(self.users["DOCTOR"], visit.booking)
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            save_medical(self.admin, visit, self.data(), publish=True)

    def test_audit_is_append_only(self):
        bk = booking(self)
        row = AuditLog.objects.first()
        with self.assertRaises(DatabaseError), transaction.atomic():
            AuditLog.objects.filter(pk=row.pk).update(reason="tampered")

    def test_review_requires_completed_paid_owned_target_and_is_unique(self):
        order = draft_order(self.user, {str(self.variant.pk): 1}, "PICKUP")
        checkout(self.user, order, "review")
        item = OrderItem.objects.get(order=order)
        with self.assertRaises(BusinessError):
            save_review(self.user, 5, "Good", order_item=item)
        pay(Invoice.objects.get(order=order))
        order.refresh_from_db()
        pack_order(self.admin, order)
        order.refresh_from_db()
        handover_pickup(self.admin, order, "Ayu")
        item.refresh_from_db()
        with self.assertRaises(BusinessError):
            save_review(self.other, 5, "Fake", order_item=item)
        one = save_review(self.user, 2, "Pengalaman perlu ditingkatkan", order_item=item)
        two = save_review(self.user, 3, "Catatan diperbarui", order_item=item)
        self.assertEqual(one.pk, two.pk)
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(two.status, "PUBLISHED")

    def test_upload_type_validated_and_private_download_scoped(self):
        with self.assertRaises(BusinessError):
            store_upload(
                self.user,
                SimpleUploadedFile(
                    "fake.jpg", b"<script>alert(1)</script>", content_type="image/jpeg"
                ),
                "PET_PHOTO",
            )
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), (20, 80, 50)).save(buf, "PNG")
        file = store_upload(
            self.user,
            SimpleUploadedFile("photo.png", buf.getvalue(), content_type="image/png"),
            "PET_PHOTO",
        )
        self.pet.photo_file = file
        self.pet.save()
        login_as(self.client, self.other)
        self.assertEqual(self.client.get(f"/berkas/{file.pk}/").status_code, 404)
        login_as(self.client, self.user)
        response = self.client.get(f"/berkas/{file.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(file.mime_type, "image/jpeg")
        response.close()

    def test_failed_business_attachment_removes_blob_and_metadata(self):
        from core.files import upload_transaction
        from core.models import PrivateFile
        from django.conf import settings

        buf = io.BytesIO()
        Image.new("RGB", (20, 20), (40, 100, 70)).save(buf, "PNG")
        upload = SimpleUploadedFile("result.png", buf.getvalue(), content_type="image/png")
        with self.assertRaises(BusinessError):
            with upload_transaction(self.user, upload, "MEDICAL") as file:
                path = settings.PRIVATE_ROOT / file.storage_key
                self.assertTrue(path.exists())
                raise BusinessError("Parent transaction rejected")
        self.assertFalse(path.exists())
        self.assertEqual(PrivateFile.objects.count(), 0)
