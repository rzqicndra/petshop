from datetime import timedelta
from django.db.models import F
from django.utils import timezone
from accounts.permissions import require_role, active_role, OPS
from catalog.models import ProductVariant
from core.services import BusinessError, commerce_transaction, code, audit, idempotent, fingerprint
from customers.models import Customer, Address
from inventory import services as stock
from .models import Order, OrderItem, OrderAddressSnapshot, PickupHandover


def cart_lines(cart):
    if not isinstance(cart, dict) or len(cart) > 30:
        raise BusinessError("Keranjang tidak valid.")
    lines = []
    for variant_id, qty in cart.items():
        if not isinstance(qty, int) or not 1 <= qty <= 99:
            raise BusinessError("Jumlah produk harus 1 sampai 99.")
        variant = (
            ProductVariant.objects.select_related("product")
            .filter(pk=variant_id, is_active=True, product__is_active=True)
            .first()
        )
        if not variant:
            raise BusinessError("Salah satu produk sudah tidak tersedia. Perbarui keranjang.")
        lines.append(
            {
                "variant": variant,
                "quantity": qty,
                "total": variant.price_rp * qty,
                "available": stock.available(variant),
            }
        )
    return lines


def draft_order(actor, cart, fulfillment, address=None, customer=None):
    require_role(actor, OPS | {"CUSTOMER"})
    customer = customer or Customer.objects.get(user=actor, is_active=True)
    if active_role(actor) == "CUSTOMER" and customer.user_id != actor.pk:
        raise BusinessError("Pelanggan tidak sesuai.")
    if fulfillment not in {"PICKUP", "DELIVERY"}:
        raise BusinessError("Pilih cara menerima pesanan.")
    lines = cart_lines(cart)
    if not lines:
        raise BusinessError("Keranjang masih kosong.")
    if fulfillment == "DELIVERY" and (
        not address or (address.customer_id != customer.pk or not address.is_active)
    ):
        raise BusinessError("Pilih alamat beserta titik Maps yang sudah dikonfirmasi.")
    with commerce_transaction():
        if fulfillment == "DELIVERY":
            Customer.objects.select_for_update().get(pk=customer.pk)
            address = Address.objects.select_for_update().get(pk=address.pk)
            if address.customer_id != customer.pk or not address.is_active:
                raise BusinessError(
                    "Alamat sudah dihapus. Pilih alamat pengiriman yang masih aktif."
                )
        order = Order.objects.create(
            customer=customer,
            code=code("OR"),
            origin="ONLINE" if active_role(actor) == "CUSTOMER" else "CASHIER",
            fulfillment=fulfillment,
            status="DRAFT",
            subtotal_rp=sum(l["total"] for l in lines),
            shipping_rp=0,
            total_rp=sum(l["total"] for l in lines),
            created_by=actor,
            version=1,
            cart_fingerprint=fingerprint(cart),
        )
        for line in lines:
            v = line["variant"]
            OrderItem.objects.create(
                order=order,
                variant=v,
                product_name=f"{v.product.name} · {v.label}",
                sku_snapshot=v.sku,
                unit_price_rp=v.price_rp,
                quantity=line["quantity"],
                line_total_rp=line["total"],
                weight_g=v.weight_g,
                dimensions={
                    "length": str(v.length_cm),
                    "width": str(v.width_cm),
                    "height": str(v.height_cm),
                },
            )
        if fulfillment == "DELIVERY":
            OrderAddressSnapshot.objects.create(
                order=order,
                recipient_name=address.recipient_name,
                recipient_phone=address.recipient_phone,
                full_address=address.address_line,
                latitude=address.latitude,
                longitude=address.longitude,
                delivery_note=address.delivery_note,
                region={
                    "province": address.province,
                    "city": address.city,
                    "district": address.district,
                    "village": address.village,
                    "postal_code": address.postal_code,
                },
            )
        return order


def checkout(actor, draft, key, quote=None, cart=None):
    require_role(actor, OPS | {"CUSTOMER"})
    with commerce_transaction():
        from billing.services import expire_unpaid

        expire_unpaid()
        idem, created = idempotent(
            "checkout", key, actor, {"draft": draft.pk, "quote": quote.pk if quote else None}
        )
        if not created and idem.result_reference:
            return Order.objects.get(pk=idem.result_reference["id"])
        order = Order.objects.select_for_update().get(pk=draft.pk)
        if active_role(actor) == "CUSTOMER" and order.customer.user_id != actor.pk:
            raise BusinessError("Pesanan tidak tersedia.")
        if order.status != "DRAFT":
            raise BusinessError("Pesanan sudah diproses. Buka detail pesanan.")
        if cart is not None and order.cart_fingerprint != fingerprint(cart):
            raise BusinessError(
                "Keranjang berubah. Periksa kembali ringkasan dan ongkir sebelum Checkout."
            )
        expiry = timezone.now() + timedelta(minutes=15)
        items = list(OrderItem.objects.filter(order=order).select_related("variant__product"))
        for item in items:
            current = ProductVariant.objects.select_for_update().get(pk=item.variant_id)
            if (
                not current.is_active
                or not current.product.is_active
                or current.price_rp != item.unit_price_rp
            ):
                raise BusinessError(
                    "Harga atau ketersediaan berubah. Ulangi Checkout untuk memperbarui ringkasan."
                )
            stock.reserve(item, expiry)
        if order.fulfillment == "DELIVERY":
            from delivery.services import validate_quote_and_reserve

            if not quote:
                raise BusinessError("Pilih metode pengiriman.")
            validate_quote_and_reserve(order, quote, expiry)
            order.shipping_rp = quote.fee_rp
        order.total_rp = order.subtotal_rp + order.shipping_rp
        order.expires_at, order.status = expiry, "AWAITING_PAYMENT"
        order.save()
        from billing.services import issue_invoice

        invoice = issue_invoice(
            order, order.customer, order.total_rp, f"Pesanan {order.code}", expiry
        )
        audit(
            actor,
            "order.checkout",
            order,
            after={"total_rp": order.total_rp, "fulfillment": order.fulfillment},
        )
        idem.status, idem.result_reference = "DONE", {"id": str(order.pk)}
        idem.save()
        return order


def pack_order(actor, order):
    require_role(actor, OPS)
    with commerce_transaction():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != "PAID":
            raise BusinessError("Pesanan harus sudah dibayar dan stok teralokasi.")
        order.status = "PACKED"
        order.save()
        audit(actor, "order.packed", order)


def handover_pickup(actor, order, recipient_name):
    require_role(actor, OPS)
    if not recipient_name.strip():
        raise BusinessError(
            "Nama penerima wajib diisi setelah pemeriksaan identitas / nomor pesanan."
        )
    with commerce_transaction():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != "PACKED" or order.fulfillment != "PICKUP":
            raise BusinessError("Pesanan belum siap diambil.")
        PickupHandover.objects.create(
            order=order,
            code_digest="",
            recipient_name=recipient_name,
            handed_over_at=timezone.now(),
            staff=actor,
        )
        order.status, order.completed_at = "COMPLETED", timezone.now()
        order.save()
        audit(actor, "order.handed_over", order, after={"status": order.status})


def cancel_order(actor, order, reason):
    require_role(actor, OPS | {"CUSTOMER"})
    with commerce_transaction():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if active_role(actor) == "CUSTOMER" and order.customer.user_id != actor.pk:
            raise BusinessError("Pesanan tidak tersedia.")
        if (
            order.status
            not in {"DRAFT", "AWAITING_PAYMENT", "PAID", "PACKED", "NEEDS_ATTENTION", "EXPIRED"}
            or not reason.strip()
        ):
            raise BusinessError(
                "Pesanan pada tahap ini tidak dapat dibatalkan. Isi alasan pembatalan."
            )
        from billing.models import Invoice
        from billing.services import fully_refunded

        paid = list(Invoice.objects.filter(order=order, status="PAID"))
        if paid and (active_role(actor) not in OPS or not all(fully_refunded(i) for i in paid)):
            raise BusinessError(
                "Pesanan sudah dibayar. Admin dapat membatalkan setelah refund penuh selesai."
            )
        from delivery.models import Shipment
        from delivery.services import TERMINAL

        active_shipments = Shipment.objects.filter(order=order).exclude(status__in=TERMINAL)
        if active_shipments.exclude(method="INTERNAL", status__in={"READY", "ALLOCATED"}).exists():
            raise BusinessError(
                "Kiriman masih aktif atau belum pasti. Rekonsiliasi dan batalkan kurir melalui penyedia sebelum menutup pesanan."
            )
        active_shipments.update(status="CANCELED")
        stock.release_order(order)
        from delivery.models import DeliveryReservation

        DeliveryReservation.objects.filter(order=order, status__in={"HELD", "CONFIRMED"}).update(
            status="RELEASED"
        )
        from billing.models import Invoice

        Invoice.objects.filter(order=order, status="UNPAID").update(status="VOID")
        order.status = "CANCELED"
        order.save()
        audit(actor, "order.canceled", order, reason=reason)
