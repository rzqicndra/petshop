"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class InventoryBatch(TimestampedModel):
    """UQ(variant_id,batch_code); 0<=reserved<=on_hand. Produk kedaluwarsa tidak boleh dijual. Batch non-expiry tetap memiliki batch penerimaan."""

    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.PROTECT, related_name="+"
    )
    batch_code = models.CharField(max_length=80, default="", blank=True)
    expires_on = models.DateField(null=True, blank=True)
    on_hand = models.IntegerField(default=0)
    reserved = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["variant", "batch_code"], name="batch_variant_code"),
            models.CheckConstraint(
                condition=Q(on_hand__gte=0, reserved__gte=0, reserved__lte=F("on_hand")),
                name="batch_nonnegative_balances",
            ),
        ]


class StockHold(TimestampedModel):
    """UQ(order_item_id,batch_id); quantity>0. Order yang sudah habis menggunakan Checkout baru, bukan mengaktifkan hold lama."""

    order_item = models.ForeignKey("orders.OrderItem", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(
        "inventory.InventoryBatch", on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.IntegerField(default=0)
    status = models.CharField(max_length=20, default="", blank=True)
    expires_at = models.DateTimeField(default=timezone.now)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order_item", "batch"], name="hold_item_batch"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="hold_positive_quantity"),
        ]


class StockMovement(TimestampedModel):
    """Delta bukan nol; actor kosong untuk proses sistem. Mutasi dan saldo diubah pada transaksi yang sama. Retur setelah barang diterima; refund tidak otomatis menambah stok."""

    batch = models.ForeignKey(
        "inventory.InventoryBatch", on_delete=models.PROTECT, related_name="+"
    )
    order_item = models.ForeignKey(
        "orders.OrderItem", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    quantity_delta = models.IntegerField(default=0)
    kind = models.CharField(max_length=25, default="", blank=True)
    reason = models.TextField(default="", blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    operation_key = models.CharField(max_length=160, default="", blank=True, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~Q(quantity_delta=0), name="stock_delta_nonzero"),
        ]
