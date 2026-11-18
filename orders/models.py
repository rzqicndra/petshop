"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class Order(TimestampedModel):
    """Fulfillment PICKUP atau DELIVERY. Total=subtotal+shipping pada baseline tanpa promo. Harga dan customer dikunci saat invoice diterbitkan."""

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=40, default="", blank=True, unique=True)
    origin = models.CharField(max_length=20, default="", blank=True)
    fulfillment = models.CharField(
        max_length=20,
        default="",
        blank=True,
        choices=[("PICKUP", "Ambil di toko"), ("DELIVERY", "Pengiriman")],
    )
    status = models.CharField(
        max_length=30,
        default="",
        blank=True,
        choices=[
            ("DRAFT", "Draft"),
            ("AWAITING_PAYMENT", "Menunggu pembayaran"),
            ("PAID", "Dibayar"),
            ("PACKED", "Siap diambil / dikirim"),
            ("IN_TRANSIT", "Dalam pengiriman"),
            ("COMPLETED", "Selesai"),
            ("CANCELED", "Dibatalkan"),
            ("EXPIRED", "Kedaluwarsa"),
            ("NEEDS_ATTENTION", "Perlu penanganan"),
        ],
    )
    subtotal_rp = models.BigIntegerField(default=0)
    shipping_rp = models.BigIntegerField(default=0)
    total_rp = models.BigIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    version = models.IntegerField(default=0)
    selected_quote = models.ForeignKey(
        "delivery.ShippingQuote", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    cart_fingerprint = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    subtotal_rp__gte=0,
                    shipping_rp__gte=0,
                    total_rp=F("subtotal_rp") + F("shipping_rp"),
                ),
                name="order_total_matches",
            ),
        ]


class OrderItem(TimestampedModel):
    """Quantity>0; line_total=unit_price*quantity. Snapshot tetap walaupun master produk berubah."""

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="+")
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.PROTECT, related_name="+"
    )
    product_name = models.CharField(max_length=180, default="", blank=True)
    sku_snapshot = models.CharField(max_length=80, default="", blank=True)
    unit_price_rp = models.BigIntegerField(default=0)
    quantity = models.IntegerField(default=0)
    line_total_rp = models.BigIntegerField(default=0)
    weight_g = models.IntegerField(default=0)
    dimensions = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    quantity__gt=0,
                    unit_price_rp__gte=0,
                    line_total_rp=F("unit_price_rp") * F("quantity"),
                ),
                name="item_quantity_total",
            ),
        ]


class OrderAddressSnapshot(TimestampedModel):
    """Wajib untuk DELIVERY; tidak perlu untuk PICKUP. Immutable setelah invoice diterbitkan; perubahan melalui alur amendemen."""

    order = models.OneToOneField("orders.Order", on_delete=models.PROTECT, related_name="+")
    recipient_name = models.CharField(max_length=150, default="", blank=True)
    recipient_phone = models.CharField(max_length=32, default="", blank=True)
    full_address = models.TextField(default="", blank=True)
    region = models.JSONField(default=dict, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, default=0)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    delivery_note = models.TextField(default="", blank=True, null=True)


class PickupHandover(TimestampedModel):
    """Satu bukti pengambilan per order. Selesai hanya setelah serah terima berhasil."""

    order = models.OneToOneField("orders.Order", on_delete=models.PROTECT, related_name="+")
    code_digest = models.CharField(max_length=255, default="", blank=True)
    recipient_name = models.CharField(max_length=150, default="", blank=True, null=True)
    handed_over_at = models.DateTimeField(null=True, blank=True)
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
