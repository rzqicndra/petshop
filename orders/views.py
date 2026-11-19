import uuid
from django.contrib import messages
from django.http import HttpResponseBadRequest, JsonResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from accounts.permissions import roles_required, verified_login, OPS, active_role
from core.selectors import visible_orders
from core.services import BusinessError
from customers.models import Customer
from delivery.models import ShippingQuote, Shipment
from catalog.models import ProductVariant
from billing.models import Invoice
from .forms import CheckoutForm
from .models import Order, OrderItem
from . import services


def cart_view(request):
    if request.user.is_authenticated and active_role(request.user) != "CUSTOMER":
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    try:
        lines = services.cart_lines(request.session.get("cart", {}))
    except (BusinessError, ValueError):
        request.session["cart"] = {}
        lines = []
        messages.error(request, "Keranjang perlu diperbarui karena ada produk yang tidak tersedia.")
    return render(
        request, "orders/cart.html", {"lines": lines, "total": sum(l["total"] for l in lines)}
    )


@require_POST
def cart_update(request):
    if request.user.is_authenticated and active_role(request.user) != "CUSTOMER":
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    variant = get_object_or_404(
        ProductVariant, pk=request.POST.get("variant"), is_active=True, product__is_active=True
    )
    try:
        qty = int(request.POST.get("quantity", 1))
        if not 0 <= qty <= 99:
            raise ValueError
    except ValueError:
        return HttpResponseBadRequest("Jumlah produk tidak valid.")
    cart = request.session.get("cart", {})
    key = str(variant.pk)
    if request.POST.get("mode") == "add":
        qty = min(99, qty + int(cart.get(key, 0)))
    if len(cart) >= 30 and key not in cart:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"message": "Maksimal 30 jenis produk per pesanan."}, status=400)
        messages.error(request, "Maksimal 30 jenis produk per pesanan.")
    else:
        if qty:
            cart[key] = qty
        else:
            cart.pop(key, None)
        request.session["cart"] = cart
        messages.success(request, "Keranjang diperbarui.")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "count": sum(int(q) for q in cart.values()),
                "message": "Produk ditambahkan ke keranjang.",
            }
        )
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, {request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect("cart")


@roles_required("CUSTOMER")
def checkout_view(request):
    customer = Customer.objects.get(user=request.user)
    form = CheckoutForm(request.POST or None, customer=customer, initial={"key": str(uuid.uuid4())})
    draft, quotes, quote_messages = None, [], []
    if request.method == "POST":
        confirm = request.POST.get("action") == "confirm"
        if not confirm:
            request.session.pop("checkout_draft", None)
            request.session.pop("checkout_address", None)
        if form.is_valid():
            method, address = form.cleaned_data["fulfillment"], form.cleaned_data["address"]
            address_id = str(address.pk) if method == "DELIVERY" else ""
            try:
                if confirm:
                    saved = request.session.get("checkout_draft")
                    if (
                        not saved
                        or saved != request.POST.get("draft")
                        or address_id != request.session.get("checkout_address")
                    ):
                        raise BusinessError(
                            "Pilihan checkout berubah. Klik Lanjutkan untuk meninjau pesanan kembali."
                        )
                    prepared = Order.objects.filter(
                        pk=saved, customer=customer, fulfillment=method, status="DRAFT"
                    ).first()
                    if not prepared:
                        raise BusinessError(
                            "Cara menerima pesanan berubah. Klik Lanjutkan untuk memperbarui ringkasan."
                        )
                    quote = None
                    if method == "DELIVERY":
                        try:
                            quote_id = uuid.UUID(request.POST.get("quote") or "")
                        except ValueError:
                            raise BusinessError(
                                "Pilih kurir dan jadwal pengiriman yang tersedia."
                            ) from None
                        quote = ShippingQuote.objects.filter(pk=quote_id, order=prepared).first()
                        if not quote:
                            raise BusinessError(
                                "Pilihan pengiriman sudah berubah. Hitung kembali ongkir."
                            )
                    elif request.POST.get("quote"):
                        raise BusinessError(
                            "Pilihan kurir tidak berlaku untuk pengambilan di toko. Klik Lanjutkan."
                        )
                    order = services.checkout(
                        request.user,
                        prepared,
                        form.cleaned_data["key"],
                        quote,
                        request.session.get("cart", {}),
                        source_address=address if method == "DELIVERY" else None,
                    )
                    request.session["cart"] = {}
                    request.session.pop("checkout_draft", None)
                    request.session.pop("checkout_address", None)
                    return redirect("order_detail", pk=order.pk)
                draft = services.draft_order(
                    request.user, request.session.get("cart", {}), method, address
                )
                if method == "DELIVERY":
                    from delivery.services import quote_order

                    quotes, quote_messages = quote_order(draft)
                request.session["checkout_draft"] = str(draft.pk)
                request.session["checkout_address"] = address_id
            except BusinessError as exc:
                draft = None
                form.add_error(None, exc)
    try:
        lines = services.cart_lines(request.session.get("cart", {}))
    except BusinessError as exc:
        lines = []
        form.add_error(None, exc)
    return render(
        request,
        "orders/checkout.html",
        {
            "form": form,
            "lines": lines,
            "total": sum(l["total"] for l in lines),
            "draft": draft,
            "quotes": quotes,
            "quote_messages": quote_messages,
        },
    )


@verified_login
def orders_list(request):
    qs = visible_orders(request.user).exclude(status="DRAFT").order_by("-created_at")
    if request.GET.get("q"):
        qs = qs.filter(code__icontains=request.GET["q"][:80])
    from django.core.paginator import Paginator

    return render(
        request, "orders/list.html", {"page": Paginator(qs, 20).get_page(request.GET.get("page"))}
    )


@verified_login
def order_detail(request, pk):
    order = get_object_or_404(visible_orders(request.user), pk=pk)
    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "cancel":
                services.cancel_order(request.user, order, request.POST.get("reason", ""))
            elif action == "pack":
                services.pack_order(request.user, order)
            elif action == "handover":
                services.handover_pickup(
                    request.user, order, request.POST.get("recipient_name", "")[:150]
                )
            elif action == "ship":
                from delivery.services import request_shipment

                request_shipment(request.user, order)
            else:
                raise BusinessError("Tindakan tidak tersedia.")
            messages.success(request, "Pesanan diperbarui.")
        except BusinessError as exc:
            messages.error(request, exc.messages[0])
        return redirect("order_detail", pk=pk)
    from customers.models import Address
    from .models import OrderAddressSnapshot
    from engagement.models import Review

    items = list(OrderItem.objects.filter(order=order))
    for item in items:
        item.review = Review.objects.filter(order_item=item).first()
    from billing.services import cancellation_options
    from delivery.services import TERMINAL

    cancellation = {}
    if order.status in {"AWAITING_PAYMENT", "PAID", "PACKED", "NEEDS_ATTENTION"}:
        cancellation = cancellation_options(
            Invoice.objects.filter(order=order), active_role(request.user)
        )
        if (
            Shipment.objects.filter(order=order)
            .exclude(status__in=TERMINAL)
            .exclude(method="INTERNAL", status__in={"READY", "ALLOCATED"})
            .exists()
        ):
            cancellation = {"shipment_in_progress": True}
    return render(
        request,
        "orders/detail.html",
        {
            **cancellation,
            "order": order,
            "items": items,
            "invoice": Invoice.objects.filter(order=order).first(),
            "shipments": Shipment.objects.filter(order=order).order_by("-created_at"),
            "address": OrderAddressSnapshot.objects.filter(order=order).first(),
            "can_operate": active_role(request.user) in OPS,
        },
    )
