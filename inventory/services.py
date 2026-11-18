from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone
from core.services import BusinessError, commerce_transaction, audit
from .models import InventoryBatch, StockHold, StockMovement


def available(variant):
    return (
        InventoryBatch.objects.filter(variant=variant, is_active=True)
        .filter(Q(expires_on__isnull=True) | Q(expires_on__gt=timezone.localdate()))
        .aggregate(value=Sum(F("on_hand") - F("reserved")))["value"]
        or 0
    )


def reserve(item, expires_at):
    remaining = item.quantity
    batches = (
        InventoryBatch.objects.select_for_update()
        .filter(variant=item.variant, is_active=True)
        .filter(Q(expires_on__isnull=True) | Q(expires_on__gt=timezone.localdate()))
        .order_by(F("expires_on").asc(nulls_last=True), "pk")
    )
    for batch in batches:
        qty = min(remaining, batch.on_hand - batch.reserved)
        if qty > 0:
            batch.reserved += qty
            batch.save(update_fields=["reserved", "updated_at"])
            StockHold.objects.create(
                order_item=item, batch=batch, quantity=qty, status="HELD", expires_at=expires_at
            )
            remaining -= qty
        if not remaining:
            break
    if remaining:
        raise BusinessError(f"Stok {item.product_name} tidak mencukupi. Perbarui keranjang.")


def release_order(order):
    for hold in (
        StockHold.objects.select_for_update()
        .filter(order_item__order=order, status="HELD")
        .order_by("batch_id")
    ):
        batch = InventoryBatch.objects.select_for_update().get(pk=hold.batch_id)
        batch.reserved -= hold.quantity
        batch.save(update_fields=["reserved", "updated_at"])
        hold.status = "RELEASED"
        hold.save(update_fields=["status", "updated_at"])


def consume_order(order):
    holds = list(
        StockHold.objects.select_for_update()
        .filter(order_item__order=order, status="HELD")
        .order_by("batch_id")
    )
    if not holds or order.expires_at <= timezone.now():
        return False
    if any(
        h.expires_at <= timezone.now()
        or (h.batch.expires_on and h.batch.expires_on <= timezone.localdate())
        for h in holds
    ):
        return False
    for hold in holds:
        batch = InventoryBatch.objects.select_for_update().get(pk=hold.batch_id)
        batch.reserved -= hold.quantity
        batch.on_hand -= hold.quantity
        batch.save(update_fields=["reserved", "on_hand", "updated_at"])
        StockMovement.objects.create(
            batch=batch,
            order_item=hold.order_item,
            quantity_delta=-hold.quantity,
            kind="SALE",
            reason="Pembayaran pesanan terverifikasi",
            operation_key=f"sale:{hold.pk}",
        )
        hold.status, hold.consumed_at = "CONSUMED", timezone.now()
        hold.save(update_fields=["status", "consumed_at", "updated_at"])
    return True


def receive_stock(actor, batch, quantity, reason, key):
    from accounts.permissions import require_role, OPS

    require_role(actor, OPS)
    if quantity == 0 or not reason.strip():
        raise BusinessError("Jumlah perubahan dan alasan wajib diisi.")
    with commerce_transaction():
        previous = StockMovement.objects.filter(operation_key=key).first()
        if previous:
            if previous.batch_id != batch.pk or previous.quantity_delta != quantity:
                raise BusinessError("Kunci mutasi telah digunakan untuk perubahan lain.")
            return previous
        batch = InventoryBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.on_hand + quantity < batch.reserved:
            raise BusinessError("Stok fisik tidak boleh lebih kecil dari stok yang direservasi.")
        batch.on_hand += quantity
        batch.save(update_fields=["on_hand", "updated_at"])
        move = StockMovement.objects.create(
            batch=batch,
            quantity_delta=quantity,
            kind="ADJUSTMENT",
            reason=reason,
            actor=actor,
            operation_key=key,
        )
        audit(actor, "inventory.adjust", batch, after={"delta": quantity}, reason=reason)
        return move
