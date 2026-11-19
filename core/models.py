"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class StoreSettings(TimestampedModel):
    """Singleton id=1 untuk satu lokasi. Konten resmi dan origin pengiriman wajib valid sebelum fungsi produksi diaktifkan."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    business_name = models.CharField(max_length=150, default="", blank=True)
    address = models.TextField(default="", blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    cs_whatsapp = models.CharField(max_length=32, default="", blank=True, null=True)
    timezone = models.CharField(max_length=60, default="", blank=True)
    opening_hours = models.JSONField(default=dict, blank=True)
    attendance_grace_minutes = models.PositiveSmallIntegerField(
        default=15,
        validators=[MaxValueValidator(120)],
        verbose_name="Toleransi keterlambatan konsultasi (menit)",
        help_text="Dokter dapat menandai tidak hadir setelah jadwal mulai ditambah toleransi ini. Maksimal 120 menit.",
    )
    reschedule_notice_minutes = models.PositiveSmallIntegerField(
        default=120,
        validators=[MinValueValidator(15), MaxValueValidator(1440)],
        verbose_name="Batas ubah jadwal (menit sebelum layanan)",
        help_text="Berlaku untuk jadwal lama dan jadwal pengganti. 120 menit = 2 jam. Isi 15–1440 menit.",
    )
    public_contact_ready = models.BooleanField(default=False)
    tagline = models.CharField(
        max_length=160, default="Care, with a little more heart.", blank=True
    )
    footer_text = models.CharField(
        max_length=240, default="Kebutuhan dan perawatan, dekat dengan Anda.", blank=True
    )
    cs_label = models.CharField(max_length=60, default="Chat dengan kami", blank=True)
    logo_file = models.ForeignKey(
        "core.PrivateFile", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )

    def clean(self):
        super().clean()
        if self.public_contact_ready:
            from .store_validation import validate_official_store

            validate_official_store(self)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="store_singleton"),
            models.CheckConstraint(
                condition=Q(attendance_grace_minutes__lte=120), name="store_attendance_grace_range"
            ),
            models.CheckConstraint(
                condition=Q(reschedule_notice_minutes__gte=15, reschedule_notice_minutes__lte=1440),
                name="store_reschedule_notice_range",
            ),
        ]


class PrivateFile(TimestampedModel):
    """File asli privat; izin diturunkan dari attachment atau pemilik profil. Tipe dan ukuran divalidasi; file ulasan publik memakai turunan tersanitasi."""

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    storage_key = models.TextField(default="", blank=True, unique=True)
    original_name = models.CharField(max_length=255, default="", blank=True)
    mime_type = models.CharField(max_length=120, default="", blank=True)
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, default="", blank=True)
    classification = models.CharField(max_length=30, default="", blank=True)
    scan_status = models.CharField(max_length=20, default="", blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)


class SiteContent(TimestampedModel):
    """Managed plain text and validated images. Templates and permissions stay in code."""

    SLOTS = [
        ("home", "Beranda · pembuka"),
        ("services", "Beranda · layanan"),
        ("care", "Beranda · perawatan"),
        ("shop", "Katalog · pembuka"),
        ("auth", "Login & Register · visual"),
        ("reviews", "Ulasan · pembuka"),
        ("contact", "Kontak · pembuka"),
        ("privacy", "Privasi & ketentuan"),
        ("service_page", "Halaman layanan"),
        ("products", "Beranda · produk"),
    ]
    key = models.CharField(max_length=30, unique=True, choices=SLOTS)
    overline = models.CharField(max_length=120, blank=True)
    heading = models.CharField(max_length=240)
    body = models.TextField(blank=True)
    image_file = models.ForeignKey(
        "core.PrivateFile", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    image_alt = models.CharField(max_length=240, blank=True)
    fallback_image = models.CharField(
        max_length=120,
        blank=True,
        choices=[
            ("images/cat-hero.jpg", "Kucing · pembuka"),
            ("images/dog-hero.jpg", "Anjing · pembuka"),
            ("images/cat-luna.jpg", "Kucing · perawatan"),
            ("", "Tanpa gambar"),
        ],
    )
    button_label = models.CharField(max_length=80, blank=True)
    link_route = models.CharField(
        max_length=40,
        blank=True,
        choices=[
            ("new_booking", "Booking layanan"),
            ("catalog", "Katalog"),
            ("register", "Register"),
            ("contact", "Kontak"),
            ("services", "Layanan"),
            ("", "Tanpa tautan"),
        ],
    )
    is_active = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        if bool(self.button_label) != bool(self.link_route):
            from django.core.exceptions import ValidationError

            raise ValidationError("Isi teks dan tujuan tombol bersama, atau kosongkan keduanya.")

    def __str__(self):
        return self.get_key_display()


class AuditLog(TimestampedModel):
    """Append only dari service; actor kosong berarti sistem. Tidak menyimpan kata sandi, OTP, token atau isi sensitif berlebihan."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    action = models.CharField(max_length=80, default="", blank=True)
    aggregate_type = models.CharField(max_length=60, default="", blank=True)
    aggregate_id = models.UUIDField()
    before_redacted = models.JSONField(default=dict, blank=True, null=True)
    after_redacted = models.JSONField(default=dict, blank=True, null=True)
    reason = models.TextField(default="", blank=True, null=True)
    request_id = models.UUIDField()
    occurred_at = models.DateTimeField(default=timezone.now)


class OutboxEvent(TimestampedModel):
    """Event disimpan bersama commit bisnis. Worker retry idempoten; isi OTP terenkripsi, umur pendek, dihapus setelah kebutuhan kirim selesai."""

    topic = models.CharField(max_length=80, default="", blank=True)
    aggregate_type = models.CharField(max_length=60, default="", blank=True)
    aggregate_id = models.UUIDField()
    payload = models.JSONField(default=dict, blank=True)
    sensitive_ciphertext = models.TextField(default="", blank=True, null=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default="", blank=True)
    attempt_count = models.IntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)


class IdempotencyRecord(TimestampedModel):
    """UQ(scope,key). Kunci sama dengan isi berbeda ditolak. Batas unik finansial tetap permanen meski catatan permintaan dipurge."""

    scope = models.CharField(max_length=80, default="", blank=True)
    key = models.CharField(max_length=180, default="", blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    request_fingerprint = models.CharField(max_length=64, default="", blank=True)
    status = models.CharField(max_length=20, default="", blank=True)
    result_reference = models.JSONField(default=dict, blank=True, null=True)
    expires_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["scope", "key"], name="idempotency_scope_key"),
        ]
