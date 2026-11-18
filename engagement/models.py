"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class Review(TimestampedModel):
    """CHECK tepat satu target dan rating 1..5. Kepemilikan, selesai dan pembayaran diperiksa di server."""

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    order_item = models.OneToOneField(
        "orders.OrderItem", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    booking = models.OneToOneField(
        "scheduling.Booking", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    rating = models.SmallIntegerField(default=0)
    comment = models.TextField(default="", blank=True)
    status = models.CharField(
        max_length=25,
        default="",
        blank=True,
        choices=[("PUBLISHED", "Ditampilkan"), ("HIDDEN", "Disembunyikan")],
    )
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(order_item__isnull=False, booking__isnull=True)
                    | Q(order_item__isnull=True, booking__isnull=False)
                )
                & Q(rating__gte=1, rating__lte=5),
                name="review_target_rating",
            ),
        ]


class ReviewFile(TimestampedModel):
    """UQ(review_id,file_id); file publik hanya setelah pemeriksaan dan status ulasan mengizinkan."""

    review = models.ForeignKey("engagement.Review", on_delete=models.PROTECT, related_name="+")
    file = models.ForeignKey("core.PrivateFile", on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["review", "file"], name="review_file_unique"),
        ]


class ReviewModeration(TimestampedModel):
    """Tindakan dan alasan tidak menimpa komentar asli; ulasan negatif yang sah tetap tampil."""

    review = models.ForeignKey("engagement.Review", on_delete=models.PROTECT, related_name="+")
    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    action = models.CharField(max_length=30, default="", blank=True)
    reason = models.TextField(default="", blank=True)


class Reminder(TimestampedModel):
    """Tepat satu sumber. Boarding checkout memakai sumber Booking; pengingat medis hanya dari versi terbit."""

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    booking = models.ForeignKey(
        "scheduling.Booking", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    record_version = models.ForeignKey(
        "care.MedicalRecordVersion",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    invoice = models.ForeignKey(
        "billing.Invoice", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    kind = models.CharField(max_length=30, default="", blank=True)
    source_version = models.IntegerField(default=0)
    scheduled_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=25, default="", blank=True)
    dedupe_key = models.CharField(max_length=180, default="", blank=True, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(booking__isnull=False, record_version__isnull=True, invoice__isnull=True)
                    | Q(booking__isnull=True, record_version__isnull=False, invoice__isnull=True)
                    | Q(booking__isnull=True, record_version__isnull=True, invoice__isnull=False)
                ),
                name="reminder_exact_source",
            ),
        ]


class NotificationDelivery(TimestampedModel):
    """Maksimal satu dari reminder dan OTP. Payload OTP terenkripsi sementara di outbox, lalu dipurge; log tidak menyimpan kode."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    outbox_event = models.ForeignKey("core.OutboxEvent", on_delete=models.PROTECT, related_name="+")
    reminder = models.ForeignKey(
        "engagement.Reminder", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    otp_challenge = models.ForeignKey(
        "accounts.OTPChallenge", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    channel = models.CharField(max_length=20, default="", blank=True)
    status = models.CharField(max_length=25, default="", blank=True)
    attempt_count = models.IntegerField(default=0)
    provider_message_id = models.CharField(max_length=160, default="", blank=True, null=True)
    dedupe_key = models.CharField(max_length=180, default="", blank=True, unique=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(reminder__isnull=True) | Q(otp_challenge__isnull=True),
                name="notification_not_two_sources",
            ),
        ]
