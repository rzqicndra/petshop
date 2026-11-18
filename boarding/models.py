"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class BoardingUnit(TimestampedModel):
    """Satu unit kapasitas untuk satu hewan selama periode; harga dan cleaning disalin pada stay."""

    resource = models.OneToOneField(
        "scheduling.Resource", on_delete=models.PROTECT, related_name="+"
    )
    species = models.ForeignKey("catalog.Species", on_delete=models.PROTECT, related_name="+")
    category = models.CharField(max_length=60, default="", blank=True)
    nightly_rate_rp = models.BigIntegerField(default=0)
    cleaning_minutes = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(nightly_rate_rp__gt=0, cleaning_minutes__gte=0),
                name="boarding_price_cleaning",
            ),
        ]


class BoardingStay(TimestampedModel):
    """Unit boleh kosong pada pengajuan; wajib saat disetujui menunggu bayar. Berkas intake terkait melalui BoardingIntakeFile; JSON menyimpan salinan syarat, bukan FK file bebas."""

    booking = models.OneToOneField("scheduling.Booking", on_delete=models.PROTECT, related_name="+")
    unit = models.ForeignKey(
        "boarding.BoardingUnit", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    caretaker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    nightly_rate_rp = models.BigIntegerField(default=0)
    cleaning_minutes = models.IntegerField(default=0)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    emergency_snapshot = models.JSONField(default=dict, blank=True)
    intake_snapshot = models.JSONField(default=dict, blank=True)
    belongings = models.TextField(default="", blank=True, null=True)


class ExtensionRequest(TimestampedModel):
    """Satu permintaan aktif per stay untuk SUBMITTED/APPROVED_AWAITING_PAYMENT/NEEDS_ATTENTION. Tanggal baru>lama; penolakan wajib alasan. Dana terlambat tidak mengaktifkan tanpa cek ulang."""

    stay = models.ForeignKey("boarding.BoardingStay", on_delete=models.PROTECT, related_name="+")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    old_checkout_at = models.DateTimeField(default=timezone.now)
    requested_checkout_at = models.DateTimeField(default=timezone.now)
    base_booking_version = models.IntegerField(default=0)
    extra_nights = models.IntegerField(default=0)
    extra_amount_rp = models.BigIntegerField(default=0)
    status = models.CharField(
        max_length=25,
        default="",
        blank=True,
        choices=[
            ("SUBMITTED", "Menunggu tinjauan"),
            ("APPROVED_AWAITING_PAYMENT", "Disetujui, menunggu pembayaran"),
            ("REJECTED", "Ditolak"),
            ("ACTIVE", "Aktif"),
            ("EXPIRED", "Kedaluwarsa"),
            ("NEEDS_ATTENTION", "Perlu penanganan"),
        ],
    )
    review_reason = models.TextField(default="", blank=True, null=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    payment_expires_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["stay"],
                name="one_active_extension",
                condition=Q(
                    status__in=["SUBMITTED", "APPROVED_AWAITING_PAYMENT", "NEEDS_ATTENTION"]
                ),
            ),
            models.CheckConstraint(
                condition=Q(
                    requested_checkout_at__gt=F("old_checkout_at"),
                    extra_nights__gt=0,
                    extra_amount_rp__gt=0,
                ),
                name="extension_positive",
            ),
        ]


class BoardingIntakeFile(TimestampedModel):
    """UQ(stay_id,file_id). Dokumen privat mengikuti syarat penerimaan; keputusan verifikasi dan masa berlaku dicatat."""

    stay = models.ForeignKey("boarding.BoardingStay", on_delete=models.PROTECT, related_name="+")
    file = models.ForeignKey("core.PrivateFile", on_delete=models.PROTECT, related_name="+")
    is_active = models.BooleanField(default=True)
    document_type = models.CharField(max_length=60, default="", blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    review_note = models.TextField(default="", blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["stay", "file"], name="intake_file_unique"),
        ]


class CareLog(TimestampedModel):
    """Pelanggan hanya melihat catatan terbit dari stay miliknya."""

    stay = models.ForeignKey("boarding.BoardingStay", on_delete=models.PROTECT, related_name="+")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    recorded_at = models.DateTimeField(default=timezone.now)
    feeding = models.TextField(default="", blank=True)
    condition = models.TextField(default="", blank=True)
    activity = models.TextField(default="", blank=True, null=True)
    published_at = models.DateTimeField(null=True, blank=True)


class CareLogFile(TimestampedModel):
    """UQ(care_log_id,file_id)."""

    care_log = models.ForeignKey("boarding.CareLog", on_delete=models.PROTECT, related_name="+")
    file = models.ForeignKey("core.PrivateFile", on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["care_log", "file"], name="care_log_file_unique"),
        ]
