"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class Invoice(TimestampedModel):
    """CHECK tepat satu target; total>=0, currency IDR. Business key mencegah invoice tujuan yang sama dibuat ulang. Parent invoice untuk tambahan boarding."""

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    order = models.ForeignKey(
        "orders.Order", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    booking = models.ForeignKey(
        "scheduling.Booking", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    extension = models.ForeignKey(
        "boarding.ExtensionRequest",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    parent_invoice = models.ForeignKey(
        "billing.Invoice", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    code = models.CharField(max_length=40, default="", blank=True, unique=True)
    business_key = models.CharField(max_length=180, default="", blank=True, unique=True)
    stage = models.CharField(max_length=25, default="", blank=True)
    status = models.CharField(
        max_length=20,
        default="",
        blank=True,
        choices=[
            ("UNPAID", "Belum dibayar"),
            ("PAID", "Lunas"),
            ("EXPIRED", "Kedaluwarsa"),
            ("VOID", "Dibatalkan"),
        ],
    )
    currency = models.CharField(max_length=3, default="", blank=True)
    total_rp = models.BigIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(order__isnull=False, booking__isnull=True, extension__isnull=True)
                    | Q(order__isnull=True, booking__isnull=False, extension__isnull=True)
                    | Q(order__isnull=True, booking__isnull=True, extension__isnull=False)
                )
                & Q(total_rp__gte=0, currency="IDR"),
                name="invoice_exact_target",
            ),
        ]


class InvoiceLine(TimestampedModel):
    """Quantity>0; line_total=quantity*unit_amount. Jumlah semua baris harus sama total invoice, diperiksa layanan penerbitan."""

    invoice = models.ForeignKey("billing.Invoice", on_delete=models.PROTECT, related_name="+")
    description = models.TextField(default="", blank=True)
    quantity = models.IntegerField(default=0)
    unit_amount_rp = models.BigIntegerField(default=0)
    line_total_rp = models.BigIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    quantity__gt=0,
                    unit_amount_rp__gte=0,
                    line_total_rp=F("quantity") * F("unit_amount_rp"),
                ),
                name="invoice_line_total",
            ),
        ]


class PaymentAttempt(TimestampedModel):
    """Setiap upaya mempunyai provider_order_id sendiri. Status UNKNOWN ditelusuri sebelum mengulang create sesi."""

    invoice = models.ForeignKey("billing.Invoice", on_delete=models.PROTECT, related_name="+")
    provider = models.CharField(max_length=30, default="", blank=True)
    environment = models.CharField(max_length=30, default="", blank=True)
    provider_order_id = models.CharField(max_length=100, default="", blank=True, unique=True)
    method = models.CharField(max_length=40, default="", blank=True)
    status = models.CharField(max_length=25, default="", blank=True)
    expected_amount_rp = models.BigIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    request_key = models.CharField(max_length=160, default="", blank=True, unique=True)
    session_url = models.TextField(blank=True)


class PaymentEvent(TimestampedModel):
    """UQ(provider,event_key) bila ID stabil tersedia; bila tidak, gunakan digest stabil lalu proses tetap idempoten pada payment dan invoice."""

    attempt = models.ForeignKey(
        "billing.PaymentAttempt", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    provider = models.CharField(max_length=30, default="", blank=True)
    event_key = models.CharField(max_length=180, default="", blank=True)
    payload_redacted = models.JSONField(default=dict, blank=True)
    authentic = models.BooleanField(default=False)
    received_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_status = models.CharField(max_length=25, default="", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "event_key"], name="payment_event_unique"),
        ]


class PaymentTransaction(TimestampedModel):
    """UQ(provider,provider_transaction_id); maksimal satu is_applied per invoice. Dana tambahan disimpan sebagai unapplied dan ditangani, bukan dibuang."""

    attempt = models.ForeignKey(
        "billing.PaymentAttempt", on_delete=models.PROTECT, related_name="+"
    )
    invoice = models.ForeignKey("billing.Invoice", on_delete=models.PROTECT, related_name="+")
    provider = models.CharField(max_length=30, default="", blank=True)
    provider_transaction_id = models.CharField(max_length=160, default="", blank=True)
    amount_rp = models.BigIntegerField(default=0)
    currency = models.CharField(max_length=3, default="", blank=True)
    settled_at = models.DateTimeField(default=timezone.now)
    is_applied = models.BooleanField(default=False)
    handling_status = models.CharField(max_length=30, default="", blank=True)
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_transaction_id"], name="provider_transaction_unique"
            ),
            models.UniqueConstraint(
                fields=["invoice"], name="one_payment_applied", condition=Q(is_applied=True)
            ),
            models.CheckConstraint(
                condition=Q(amount_rp__gt=0, currency="IDR"), name="payment_positive_idr"
            ),
        ]


class Refund(TimestampedModel):
    """Amount>0. Jumlah refund berjalan dan sukses tidak melebihi dana terkait; kunci payment sebelum menghitung."""

    payment = models.ForeignKey(
        "billing.PaymentTransaction", on_delete=models.PROTECT, related_name="+"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    amount_rp = models.BigIntegerField(default=0)
    reason = models.TextField(default="", blank=True)
    status = models.CharField(
        max_length=25,
        default="",
        blank=True,
        choices=[
            ("REQUESTED", "Diajukan"),
            ("APPROVED", "Disetujui"),
            ("PROCESSING", "Diproses"),
            ("COMPLETED", "Selesai"),
            ("REJECTED", "Ditolak"),
            ("UNKNOWN", "Perlu rekonsiliasi"),
        ],
    )
    request_key = models.CharField(max_length=160, default="", blank=True, unique=True)
    provider_refund_id = models.CharField(max_length=160, default="", blank=True, null=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount_rp__gt=0), name="refund_positive"),
        ]
