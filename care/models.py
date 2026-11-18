"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class Visit(TimestampedModel):
    """Satu Visit untuk satu Booking VET; dokter harus berizin dan ditugaskan."""

    booking = models.OneToOneField("scheduling.Booking", on_delete=models.PROTECT, related_name="+")
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    examined_at = models.DateTimeField(null=True, blank=True)


class MedicalRecordVersion(TimestampedModel):
    """UQ(visit_id,version_no); satu versi current terbit per visit. Current mewajibkan published_at. Revisi setelah terbit membutuhkan alasan dan versi baru."""

    visit = models.ForeignKey("care.Visit", on_delete=models.PROTECT, related_name="+")
    version_no = models.IntegerField(default=0)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    complaint = models.TextField(default="", blank=True)
    findings = models.TextField(default="", blank=True)
    diagnosis = models.TextField(default="", blank=True)
    treatment = models.TextField(default="", blank=True)
    aftercare = models.TextField(default="", blank=True)
    followup_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    revision_reason = models.TextField(default="", blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["visit", "version_no"], name="medical_visit_version"),
            models.UniqueConstraint(
                fields=["visit"], name="medical_current_unique", condition=Q(is_current=True)
            ),
            models.CheckConstraint(
                condition=Q(is_current=False) | Q(published_at__isnull=False),
                name="current_record_published",
            ),
        ]


class ClinicalInternalNote(TimestampedModel):
    """Tidak ikut ringkasan atau ekspor pelanggan. Akses tenaga klinis berwenang."""

    visit = models.ForeignKey("care.Visit", on_delete=models.PROTECT, related_name="+")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    content = models.TextField(default="", blank=True)


class MedicalAttachment(TimestampedModel):
    """UQ(record_version_id,file_id). PDF terikat versi terbit, bukan selalu versi mutakhir saat diunduh."""

    record_version = models.ForeignKey(
        "care.MedicalRecordVersion", on_delete=models.PROTECT, related_name="+"
    )
    file = models.ForeignKey("core.PrivateFile", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=20, default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["record_version", "file"], name="medical_file_unique"),
        ]


class GroomingJob(TimestampedModel):
    """Hanya Booking GROOMING. Selesai setelah serah terima; penugasan harus sesuai resource dan izin."""

    booking = models.OneToOneField("scheduling.Booking", on_delete=models.PROTECT, related_name="+")
    groomer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    result_note = models.TextField(default="", blank=True, null=True)


class GroomingResultFile(TimestampedModel):
    """UQ(job_id,file_id); audience dari customer Booking terkait."""

    job = models.ForeignKey("care.GroomingJob", on_delete=models.PROTECT, related_name="+")
    file = models.ForeignKey("core.PrivateFile", on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "file"], name="grooming_file_unique"),
        ]
