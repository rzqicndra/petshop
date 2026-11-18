from datetime import timedelta
from math import ceil
from django.conf import settings
from django.utils import timezone
from accounts.permissions import require_role, active_role, OPS
from core.models import StoreSettings
from core.services import BusinessError, commerce_transaction, fingerprint, audit
from orders.models import Order, OrderItem, OrderAddressSnapshot
from .models import (
    DeliveryPolicy,
    DeliveryWindow,
    ShippingQuote,
    DeliveryReservation,
    Shipment,
    ShipmentEvent,
    DeliveryAssignment,
)
from . import providers

TERMINAL = {"DELIVERED", "CANCELED", "REJECTED", "RETURNED", "DISPOSED"}
STATUS_MAP = {
    "confirmed": "CONFIRMED",
    "scheduled": "CONFIRMED",
    "allocated": "ALLOCATED",
    "picking_up": "ALLOCATED",
    "picked": "IN_TRANSIT",
    "in_transit": "IN_TRANSIT",
    "dropping_off": "IN_TRANSIT",
    "on_hold": "ON_HOLD",
    "courier_not_found": "ON_HOLD",
    "return_in_transit": "RETURNING",
    "returned": "RETURNED",
    "cancelled": "CANCELED",
    "rejected": "REJECTED",
    "disposed": "DISPOSED",
    "delivered": "DELIVERED",
}


def package_snapshot(order, policy):
    items = list(OrderItem.objects.filter(order=order).order_by("pk"))
    return {
        "weight": sum(i.weight_g * i.quantity for i in items) + policy.packaging_weight_g,
        "length": max(float(i.dimensions["length"]) for i in items),
        "width": max(float(i.dimensions["width"]) for i in items),
        "height": sum(float(i.dimensions["height"]) * i.quantity for i in items),
        "items": [
            {"sku": i.sku_snapshot, "qty": i.quantity, "price": i.unit_price_rp} for i in items
        ],
    }


def address_fingerprint(address):
    return fingerprint(
        {
            f: getattr(address, f)
            for f in (
                "recipient_name",
                "recipient_phone",
                "full_address",
                "region",
                "latitude",
                "longitude",
                "delivery_note",
            )
        }
    )


def provider_items(order, package):
    return [
        {
            "name": f"Kebutuhan hewan {order.code}",
            "value": order.subtotal_rp,
            "quantity": 1,
            **{k: package[k] for k in ("weight", "length", "width", "height")},
        }
    ]


def origin_snapshot(store):
    return {
        "business_name": store.business_name, "address": store.address,
        "cs_whatsapp": store.cs_whatsapp, "public_contact_ready": store.public_contact_ready,
        "latitude": str(store.latitude), "longitude": str(store.longitude),
    }


def quote_order(order):
    if order.status != "DRAFT" or order.fulfillment != "DELIVERY":
        raise BusinessError("Pesanan belum siap untuk menghitung ongkir.")
    policy, store = DeliveryPolicy.objects.get(pk=1), StoreSettings.objects.get(pk=1)
    address = OrderAddressSnapshot.objects.get(order=order)
    if store.latitude is None or store.longitude is None:
        raise BusinessError("Lokasi asal toko belum dikonfigurasi.")
    if not settings.LOCAL_MODE and not store.public_contact_ready:
        raise BusinessError("Data alamat dan kontak resmi toko belum disahkan.")
    if not settings.LOCAL_MODE or settings.SHIPPING_MODE == "biteship":
        from core.store_validation import validate_official_store
        validate_official_store(store)
    package = package_snapshot(order, policy)
    store_snapshot = origin_snapshot(store)
    origin, destination = (store.latitude, store.longitude), (address.latitude, address.longitude)
    messages, quotes, distance = [], [], None
    try:
        distance = providers.route_distance(origin, destination, policy.travel_mode)
    except Exception:
        messages.append("Jarak rute tidak dapat diperiksa. Kurir Toko tidak ditawarkan.")
    expiry = timezone.now() + timedelta(minutes=10)
    common = {
        "order": order,
        "route_distance_m": distance or 0,
        "travel_mode": policy.travel_mode,
        "address_fingerprint": address_fingerprint(address),
        "policy_version": policy.version,
        "origin_fingerprint": fingerprint(store_snapshot),
        "origin_snapshot": store_snapshot,
        "expires_at": expiry,
    }
    within_limits = (
        package["weight"] <= policy.max_weight_g
        and package["length"] <= policy.max_length_cm
        and package["width"] <= policy.max_width_cm
        and package["height"] <= policy.max_height_cm
    )
    if (
        policy.internal_enabled
        and distance is not None
        and distance <= policy.max_route_m
        and within_limits
    ):
        for window in DeliveryWindow.objects.filter(
            is_active=True, starts_at__gt=timezone.now()
        ).order_by("starts_at")[:20]:
            local = timezone.localtime(window.starts_at)
            hours = policy.service_hours.get(str(local.weekday()))
            if not hours or not hours[0] <= local.strftime("%H:%M") < hours[1]:
                continue
            used = (
                DeliveryReservation.objects.filter(
                    window=window, status__in={"HELD", "CONFIRMED", "FULFILLED"}
                )
                .exclude(status="HELD", expires_at__lte=timezone.now())
                .count()
            )
            if used >= window.max_orders:
                continue
            fee = policy.base_fee_rp + ceil(distance / 1000) * policy.per_km_fee_rp
            quotes.append(
                ShippingQuote.objects.create(
                    **common,
                    provider="INTERNAL",
                    method="INTERNAL",
                    service_code="store",
                    window=window,
                    fee_rp=fee,
                    package_snapshot={**package, "label": "Kurir Toko"},
                )
            )
    elif distance is not None and distance > policy.max_route_m:
        messages.append(
            "Alamat di luar jangkauan Kurir Toko. Gunakan kurir instan atau ambil di toko."
        )
    try:
        for rate in providers.instant_rates(origin, destination, provider_items(order, package)):
            value = rate.get("price")
            if not isinstance(value, (int, float)) or value < 0 or int(value) != value:
                continue
            quotes.append(
                ShippingQuote.objects.create(
                    **common,
                    provider="MOCK" if settings.SHIPPING_MODE == "mock" else "BITESHIP",
                    method="INSTANT",
                    service_code=f"{rate['courier_code']}:{rate['courier_service_code']}",
                    fee_rp=int(value),
                    package_snapshot={
                        **package,
                        "label": rate.get("courier_name", rate["courier_code"]),
                    },
                )
            )
    except Exception:
        messages.append("Tarif kurir instan belum tersedia. Coba lagi atau pilih ambil di toko.")
    return quotes, messages


def validate_quote_and_reserve(order, quote, expires_at):
    quote = ShippingQuote.objects.select_for_update().get(pk=quote.pk)
    policy = DeliveryPolicy.objects.select_for_update().get(pk=1)
    address = OrderAddressSnapshot.objects.get(order=order)
    if (
        quote.order_id != order.pk
        or quote.expires_at <= timezone.now()
        or quote.policy_version != policy.version
        or not quote.origin_fingerprint
        or quote.origin_fingerprint != fingerprint(origin_snapshot(StoreSettings.objects.select_for_update().get(pk=1)))
        or quote.address_fingerprint != address_fingerprint(address)
    ):
        raise BusinessError(
            "Tarif pengiriman melewati batas waktu atau alamat asal/tujuan berubah. Hitung ulang ongkir."
        )
    snapshot = {
        k: quote.package_snapshot[k] for k in ("weight", "length", "width", "height", "items")
    }
    if fingerprint(snapshot) != fingerprint(package_snapshot(order, policy)):
        raise BusinessError("Isi paket berubah. Hitung ulang ongkir.")
    if quote.method == "INTERNAL":
        window = DeliveryWindow.objects.select_for_update().get(pk=quote.window_id)
        if (
            not policy.internal_enabled
            or quote.route_distance_m > policy.max_route_m
            or not window.is_active
            or window.starts_at <= timezone.now()
        ):
            raise BusinessError("Kurir Toko tidak lagi tersedia untuk jadwal ini.")
        DeliveryReservation.objects.filter(
            window=window, status="HELD", expires_at__lte=timezone.now()
        ).update(status="EXPIRED")
        used = DeliveryReservation.objects.filter(
            window=window, status__in={"HELD", "CONFIRMED", "FULFILLED"}
        ).count()
        if used >= window.max_orders:
            raise BusinessError("Kuota pengantaran sudah penuh. Pilih jadwal atau metode lain.")
        DeliveryReservation.objects.create(
            order=order, window=window, status="HELD", expires_at=expires_at
        )
    # Keep exactly the selected quote attached through an immutable, explicit reference on Order.
    order.selected_quote = quote


def request_shipment(actor, order):
    require_role(actor, OPS)
    with commerce_transaction():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != "PACKED" or order.fulfillment != "DELIVERY":
            raise BusinessError("Pengiriman dibuat setelah pesanan dibayar dan dikemas.")
        current = Shipment.objects.filter(order=order).exclude(status__in=TERMINAL).first()
        if current:
            return current
        quote = order.selected_quote
        if not quote:
            raise BusinessError("Tarif pengiriman belum ditautkan.")
        store = StoreSettings.objects.select_for_update().get(pk=1)
        if not quote.origin_fingerprint or quote.origin_fingerprint != fingerprint(origin_snapshot(store)):
            raise BusinessError("Lokasi/kontak asal berubah. Tahan pengiriman dan hubungi admin untuk penanganan pesanan.")
        attempts = Shipment.objects.filter(order=order).count()
        shipment = Shipment.objects.create(
            order=order,
            quote=quote,
            attempt_no=attempts + 1,
            method=quote.method,
            provider=quote.provider,
            status="READY" if quote.method == "INTERNAL" else "REQUESTING",
            request_key=f"SS-SHIP-{order.pk}-{attempts+1}",
        )
        if quote.method == "INTERNAL":
            audit(actor, "delivery.internal_ready", shipment)
            return shipment
        store = StoreSettings.objects.get(pk=1)
        address = OrderAddressSnapshot.objects.get(order=order)
        courier, service = quote.service_code.split(":", 1)
        shipment.request_payload = {
            "reference_id": shipment.request_key,
            "origin_contact_name": store.business_name,
            "origin_contact_phone": store.cs_whatsapp,
            "origin_address": store.address,
            "origin_coordinate": {
                "latitude": float(store.latitude),
                "longitude": float(store.longitude),
            },
            "destination_contact_name": address.recipient_name,
            "destination_contact_phone": address.recipient_phone,
            "destination_address": address.full_address
            + ", "
            + ", ".join(str(x) for x in address.region.values() if x),
            "destination_note": address.delivery_note,
            "destination_coordinate": {
                "latitude": float(address.latitude),
                "longitude": float(address.longitude),
            },
            "courier_company": courier,
            "courier_type": service,
            "delivery_type": "now",
            "items": provider_items(order, quote.package_snapshot),
        }
        shipment.save(update_fields=["request_payload", "updated_at"])
    return dispatch_external(shipment)


def dispatch_external(shipment):
    try:
        if shipment.provider == "BITESHIP":
            # Revalidate the selected live service at dispatch; never silently charge a difference.
            origin = shipment.request_payload["origin_coordinate"]
            destination = shipment.request_payload["destination_coordinate"]
            current = providers.instant_rates(
                (origin["latitude"], origin["longitude"]),
                (destination["latitude"], destination["longitude"]),
                shipment.request_payload["items"],
            )
            rate = next(
                (
                    r
                    for r in current
                    if f"{r['courier_code']}:{r['courier_service_code']}"
                    == shipment.quote.service_code
                ),
                None,
            )
            if not rate:
                Shipment.objects.filter(pk=shipment.pk).update(status="ON_HOLD")
                raise BusinessError(
                    "Layanan kurir sedang tidak tersedia. Kiriman ditahan untuk penanganan admin."
                )
            new_fee = int(rate["price"])
            approved = shipment.cost_approved_by_id and shipment.actual_fee_rp == new_fee
            if new_fee != shipment.quote.fee_rp and not approved:
                Shipment.objects.filter(pk=shipment.pk).update(
                    status="ON_HOLD",
                    actual_fee_rp=new_fee,
                    cost_approved_by=None,
                    cost_approval_reason="",
                )
                raise BusinessError(
                    "Tarif dispatch berubah. Admin perlu menyetujui biaya aktual yang ditanggung toko sebelum memesan kurir."
                )
            Shipment.objects.filter(pk=shipment.pk).update(actual_fee_rp=new_fee)
        result = providers.create_external_shipment(shipment, shipment.request_payload)
        with commerce_transaction():
            locked = Shipment.objects.select_for_update().get(pk=shipment.pk)
            locked.provider_shipment_id = result["id"]
            locked.save(update_fields=["provider_shipment_id", "updated_at"])
            apply_shipment_status(locked, result, "create:" + result["id"])
    except BusinessError:
        Shipment.objects.filter(pk=shipment.pk, status="REQUESTING").update(status="UNKNOWN")
        raise
    except Exception:
        Shipment.objects.filter(pk=shipment.pk, status="REQUESTING").update(status="UNKNOWN")
        raise BusinessError(
            "Respons kurir belum pasti. Rekonsiliasi pengiriman ini sebelum mencoba kembali."
        )
    shipment.refresh_from_db()
    return shipment


def approve_dispatch_cost(actor, shipment, reason):
    require_role(actor, OPS)
    if not reason.strip():
        raise BusinessError("Alasan persetujuan selisih biaya wajib diisi.")
    with commerce_transaction():
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if (
            shipment.status != "ON_HOLD"
            or shipment.provider_shipment_id
            or shipment.actual_fee_rp is None
        ):
            raise BusinessError(
                "Kiriman tidak sedang menunggu persetujuan biaya. Rekonsiliasi kiriman aktif melalui penyedia."
            )
        shipment.cost_approved_by, shipment.cost_approval_reason = actor, reason
        shipment.status = "REQUESTING"
        shipment.save()
        audit(
            actor,
            "delivery.cost_difference_approved",
            shipment,
            after={
                "customer_fee_rp": shipment.quote.fee_rp,
                "actual_fee_rp": shipment.actual_fee_rp,
            },
            reason=reason,
        )
    return dispatch_external(shipment)


def reconcile_shipment(actor, shipment):
    require_role(actor, OPS)
    if shipment.provider == "MOCK":
        raise BusinessError("Gunakan simulasi pengiriman lokal untuk kiriman ini.")
    if shipment.provider_shipment_id:
        result = providers.get_external_shipment(shipment.provider_shipment_id)
        if result.get("reference_id") != shipment.request_key:
            raise BusinessError("Referensi kiriman tidak sesuai penyedia.")
        with commerce_transaction():
            locked = Shipment.objects.select_for_update().get(pk=shipment.pk)
            apply_shipment_status(locked, result, fingerprint(result))
        return
    if shipment.status != "UNKNOWN":
        raise BusinessError("Pengiriman masih diproses. Tunggu hasil sebelum rekonsiliasi ulang.")
    with commerce_transaction():
        locked = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if locked.status != "UNKNOWN":
            raise BusinessError("Rekonsiliasi sedang berjalan.")
        locked.status = "REQUESTING"
        locked.save()
    return dispatch_external(locked)


def apply_shipment_status(shipment, result, event_key):
    if result.get("reference_id") != shipment.request_key:
        raise BusinessError("Referensi kiriman berbeda.")
    state = STATUS_MAP.get(result.get("status"))
    if not state:
        return
    _, created = ShipmentEvent.objects.get_or_create(
        shipment=shipment,
        event_key=event_key,
        defaults={
            "status": state,
            "occurred_at": timezone.now(),
            "payload_redacted": {"status": result.get("status")},
        },
    )
    if not created or shipment.status in TERMINAL:
        return
    shipment.status = state
    courier = result.get("courier") or {}
    shipment.tracking_code = courier.get("waybill_id") or shipment.tracking_code
    if state == "DELIVERED":
        shipment.delivered_at = timezone.now()
        order = Order.objects.select_for_update().get(pk=shipment.order_id)
        order.status, order.completed_at = "COMPLETED", timezone.now()
        order.save()
        DeliveryReservation.objects.filter(order=order).update(
            status="FULFILLED", fulfilled_at=timezone.now()
        )
    elif state == "IN_TRANSIT":
        Order.objects.filter(pk=shipment.order_id, status="PACKED").update(status="IN_TRANSIT")
    shipment.save()


def assign_internal(actor, shipment, courier):
    require_role(actor, OPS)
    if not courier.can_deliver or not courier.is_active or not courier.email_verified_at:
        raise BusinessError("Petugas belum memiliki izin pengantaran aktif.")
    with commerce_transaction():
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if shipment.method != "INTERNAL" or shipment.status not in {"READY", "ALLOCATED"}:
            raise BusinessError("Kiriman tidak dapat ditugaskan pada tahap ini.")
        DeliveryAssignment.objects.update_or_create(
            shipment=shipment,
            defaults={"courier_user": courier, "assigned_by": actor, "assigned_at": timezone.now()},
        )
        shipment.status = "ALLOCATED"
        shipment.save()
        audit(actor, "delivery.assigned", shipment, after={"courier": str(courier.pk)})


def complete_internal(actor, assignment, recipient, proof):
    if not actor.can_deliver or assignment.courier_user_id != actor.pk:
        raise BusinessError("Pengantaran tidak ditugaskan kepada Anda.")
    if not recipient.strip() or not proof or proof.uploaded_by_id != actor.pk:
        raise BusinessError("Nama penerima dan bukti serah terima diperlukan.")
    with commerce_transaction():
        assignment = DeliveryAssignment.objects.select_for_update().get(pk=assignment.pk)
        if assignment.courier_user_id != actor.pk:
            raise BusinessError("Penugasan pengiriman telah berubah. Muat ulang tugas Anda.")
        shipment = Shipment.objects.select_for_update().get(pk=assignment.shipment_id)
        if shipment.status != "IN_TRANSIT" or assignment.completed_at:
            raise BusinessError("Pengantaran sudah selesai atau tidak aktif.")
        assignment.recipient_name, assignment.proof_file, assignment.completed_at = (
            recipient,
            proof,
            timezone.now(),
        )
        assignment.save()
        apply_shipment_status(
            shipment,
            {"reference_id": shipment.request_key, "status": "delivered"},
            f"internal:{assignment.pk}",
        )
        audit(actor, "delivery.completed", shipment)


def start_internal(actor, assignment):
    if not actor.can_deliver or assignment.courier_user_id != actor.pk:
        raise BusinessError("Pengantaran tidak ditugaskan kepada Anda.")
    with commerce_transaction():
        assignment = DeliveryAssignment.objects.select_for_update().get(pk=assignment.pk)
        if assignment.courier_user_id != actor.pk:
            raise BusinessError("Penugasan pengiriman telah berubah. Muat ulang tugas Anda.")
        shipment = Shipment.objects.select_for_update().get(pk=assignment.shipment_id)
        if shipment.method != "INTERNAL" or shipment.status != "ALLOCATED":
            raise BusinessError("Pengiriman belum ditugaskan atau sudah berjalan.")
        shipment.handed_over_at = timezone.now()
        shipment.save(update_fields=["handed_over_at", "updated_at"])
        apply_shipment_status(
            shipment,
            {"reference_id": shipment.request_key, "status": "in_transit"},
            "internal-start:" + str(assignment.pk),
        )
        audit(actor, "delivery.started", shipment)
