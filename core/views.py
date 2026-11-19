import csv
from datetime import timedelta
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.db import connection
from django.db.models import Q, Sum
from django.http import JsonResponse, FileResponse, HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from accounts.permissions import (
    verified_login,
    roles_required,
    active_role,
    workspace_url,
    ROLES,
    OPS,
    READ_ALL,
)
from catalog.models import Product, ProductVariant, ProductSpecies, Species, Category
from scheduling.models import Service
from scheduling.models import ServicePackage, Booking
from orders.models import Order
from billing.models import Invoice, PaymentTransaction, Refund
from engagement.models import Review, Reminder, NotificationDelivery
from inventory.models import InventoryBatch, StockMovement
from .models import PrivateFile, AuditLog, OutboxEvent, StoreSettings, SiteContent
from .selectors import visible_bookings, visible_orders
from .files import can_read_file
from .services import BusinessError


def home(request):
    from engagement.presentation import rating_summary

    public = Review.objects.filter(status="PUBLISHED")
    return render(
        request,
        "public/home.html",
        {
            "services": Service.objects.filter(is_active=True).order_by("created_at"),
            "packages": ServicePackage.objects.filter(
                is_active=True, service__is_active=True
            ).select_related("service")[:6],
            "products": ProductVariant.objects.filter(
                is_active=True, product__is_active=True, product__category__is_active=True
            ).select_related("product")[:4],
            "reviews": Review.objects.filter(status="PUBLISHED")
            .select_related("customer", "booking__package")
            .order_by("-created_at")[:3],
            "rating_summary": rating_summary(public),
        },
    )


def catalog_view(request):
    products = Product.objects.filter(is_active=True, category__is_active=True)
    species = Species.objects.filter(code=request.GET.get("species"), is_active=True).first()
    if species:
        products = products.filter(
            Q(pk__in=ProductSpecies.objects.filter(species=species).values("product_id"))
            | ~Q(pk__in=ProductSpecies.objects.values("product_id"))
        )
    categories = Category.objects.filter(
        pk__in=products.values("category_id"), is_active=True
    ).order_by("name")
    category = categories.filter(code=request.GET.get("category")).first()
    reset_category = bool(request.GET.get("category") and not category)
    if category:
        products = products.filter(category=category)
    if request.GET.get("q"):
        products = products.filter(name__icontains=request.GET["q"][:100])
    variants = (
        ProductVariant.objects.filter(product__in=products, is_active=True)
        .select_related("product__category")
        .order_by("product__name", "price_rp")
    )
    sort = request.GET.get("sort", "new")
    ordering = {
        "new": "-created_at",
        "price_asc": "price_rp",
        "price_desc": "-price_rp",
        "name": "product__name",
    }
    variants = variants.order_by(ordering.get(sort, "-created_at"), "pk")
    from inventory.services import available
    from django.core.paginator import Paginator

    page = Paginator(variants, 12).get_page(request.GET.get("page"))
    for item in page:
        item.available = available(item)
    return render(
        request,
        "public/catalog.html",
        {
            "page": page,
            "species_list": Species.objects.filter(is_active=True),
            "selected_species": species,
            "categories": categories,
            "selected_category": category,
            "reset_category": reset_category,
            "selected_sort": sort,
        },
    )


def services_view(request):
    return render(
        request,
        "public/services.html",
        {
            "packages": ServicePackage.objects.filter(is_active=True, service__is_active=True)
            .select_related("service")
            .order_by("service__kind", "price_rp")
        },
    )


def contact_view(request):
    store = StoreSettings.objects.filter(pk=1).first()
    maps_url = (
        "https://www.google.com/maps/search/?"
        + urlencode({"api": 1, "query": f"{store.latitude},{store.longitude}"})
        if store and store.latitude is not None and store.public_contact_ready
        else None
    )
    wa_url = (
        "https://wa.me/" + store.cs_whatsapp
        if store and store.cs_whatsapp and store.public_contact_ready
        else None
    )
    days = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    operating_hours = (
        [(day, (store.opening_hours or {}).get(str(index))) for index, day in enumerate(days)]
        if store and store.public_contact_ready
        else []
    )
    return render(
        request,
        "public/contact.html",
        {"maps_url": maps_url, "wa_url": wa_url, "operating_hours": operating_hours},
    )


def public_reviews(request):
    from engagement.presentation import rating_summary
    from django.core.paginator import Paginator

    public = Review.objects.filter(status="PUBLISHED")
    shown = public.select_related("customer", "booking__package")
    rating = request.GET.get("rating", "")
    if rating in {"1", "2", "3", "4", "5"}:
        shown = shown.filter(rating=int(rating))
    else:
        rating = ""
    sort = request.GET.get("sort", "new")
    ordering = {"new": "-created_at", "high": "-rating", "low": "rating"}
    sort = sort if sort in ordering else "new"
    page = Paginator(shown.order_by(ordering[sort], "-created_at", "pk"), 12).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "public/reviews.html",
        {
            "reviews": page,
            "page": page,
            "rating_summary": rating_summary(public),
            "selected_rating": rating,
            "selected_sort": sort,
        },
    )


@verified_login
def dashboard(request, role_slug=None):
    role = active_role(request.user)
    expected_slug = ROLES.get(role, ("", ""))[1]
    if role_slug and (role == "CUSTOMER" or role_slug != expected_slug):
        return redirect(workspace_url(role))
    if not role_slug and role != "CUSTOMER":
        return redirect(workspace_url(role))
    bookings, orders = visible_bookings(request.user), visible_orders(request.user)
    from delivery.models import DeliveryAssignment
    from customers.models import Pet

    return render(
        request,
        "core/staff_dashboard.html" if role != "CUSTOMER" else "core/dashboard.html",
        {
            "today_count": bookings.filter(starts_at__date=timezone.localdate()).count(),
            "bookings": bookings.exclude(
                status__in={"COMPLETED", "CANCELED", "EXPIRED", "NO_SHOW"}
            ).order_by("starts_at")[:6],
            "orders": orders.exclude(status="DRAFT").order_by("-created_at")[:5],
            "booking_count": bookings.filter(
                status__in={"SUBMITTED", "CONFIRMED", "IN_SERVICE", "AWAITING_PAYMENT"}
            ).count(),
            "order_count": orders.filter(
                status__in={"PAID", "PACKED", "IN_TRANSIT", "AWAITING_PAYMENT"}
            ).count(),
            "attention_count": (
                (
                    bookings.filter(status="NEEDS_ATTENTION").count()
                    + orders.filter(status="NEEDS_ATTENTION").count()
                )
                if role in READ_ALL
                else None
            ),
            "pets": (
                Pet.objects.filter(customer__user=request.user, is_active=True).select_related(
                    "species", "photo_file"
                )
                if role == "CUSTOMER"
                else []
            ),
            "reminders": Reminder.objects.filter(
                customer__user=request.user, status__in={"PENDING", "QUEUED"}
            ).order_by("scheduled_at")[:5],
            "assignments": DeliveryAssignment.objects.filter(
                courier_user=request.user, completed_at__isnull=True
            ).select_related("shipment__order")[:5],
        },
    )


@verified_login
def file_download(request, pk):
    file = get_object_or_404(PrivateFile, pk=pk, purged_at__isnull=True)
    if not can_read_file(request.user, file):
        raise Http404
    path = (settings.PRIVATE_ROOT / file.storage_key).resolve()
    if not path.is_relative_to(settings.PRIVATE_ROOT.resolve()) or not path.is_file():
        raise Http404
    response = FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename=f"sinau-{file.pk}{path.suffix}",
        content_type=file.mime_type,
    )
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    from .services import audit

    audit(request.user, "file.downloaded", file)
    return response


@roles_required("SUPER_ADMIN", "ADMIN", "OWNER")
def inventory_view(request):
    if request.method == "POST":
        try:
            from inventory.services import receive_stock

            batch = get_object_or_404(InventoryBatch, pk=request.POST.get("batch"))
            try:
                qty = int(request.POST.get("quantity", 0))
            except ValueError:
                raise BusinessError("Jumlah perubahan tidak valid.")
            if abs(qty) > 100000:
                raise BusinessError("Jumlah perubahan terlalu besar.")
            receive_stock(
                request.user,
                batch,
                qty,
                request.POST.get("reason", "")[:2000],
                request.POST.get("key", ""),
            )
            messages.success(request, "Mutasi stok dicatat dalam ledger.")
        except BusinessError as exc:
            messages.error(request, exc.messages[0])
        return redirect("inventory")
    import uuid

    return render(
        request,
        "core/inventory.html",
        {
            "batches": InventoryBatch.objects.select_related("variant__product").order_by(
                "variant__sku", "expires_on"
            ),
            "movements": StockMovement.objects.select_related("batch__variant", "actor").order_by(
                "-created_at"
            )[:40],
            "key": str(uuid.uuid4()),
        },
    )


@roles_required("SUPER_ADMIN", "ADMIN", "OWNER")
def reports_view(request):
    days = 30
    try:
        days = min(366, max(1, int(request.GET.get("days", 30))))
    except ValueError:
        pass
    since = timezone.now() - timedelta(days=days)
    payments = PaymentTransaction.objects.filter(settled_at__gte=since)
    refunds = Refund.objects.filter(status="COMPLETED", completed_at__gte=since)
    received = payments.aggregate(value=Sum("amount_rp"))["value"] or 0
    refunded = refunds.aggregate(value=Sum("amount_rp"))["value"] or 0
    if request.GET.get("format") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="sinau-laporan-transaksi.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(["Tanggal", "Invoice", "Provider", "Dana diterima Rp", "Status penerapan"])
        for payment in payments.select_related("invoice"):
            row = [
                payment.settled_at.isoformat(),
                payment.invoice.code,
                payment.provider,
                payment.amount_rp,
                payment.handling_status,
            ]
            writer.writerow(["'" + v if isinstance(v, str) and v[:1] in "=+-@" else v for v in row])
        return response
    return render(
        request,
        "core/reports.html",
        {
            "days": days,
            "received": received,
            "refunded": refunded,
            "net": received - refunded,
            "unapplied": payments.filter(is_applied=False).aggregate(value=Sum("amount_rp"))[
                "value"
            ]
            or 0,
            "payments": payments.select_related("invoice").order_by("-settled_at")[:100],
            "refunds": refunds.select_related("payment__invoice").order_by("-completed_at")[:50],
        },
    )


@roles_required("SUPER_ADMIN", "OWNER")
def audit_view(request):
    return render(
        request,
        "core/audit.html",
        {
            "logs": AuditLog.objects.select_related("actor").order_by("-occurred_at")[:150],
            "notifications": NotificationDelivery.objects.select_related("user").order_by(
                "-created_at"
            )[:50],
            "outbox_attention": OutboxEvent.objects.filter(
                status__in={"UNKNOWN", "FAILED"}
            ).order_by("-created_at")[:50],
        },
    )


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)


def privacy(request):
    return render(request, "public/privacy.html")


def product_image(request, pk):
    variant = get_object_or_404(
        ProductVariant.objects.select_related("image_file"),
        pk=pk,
        is_active=True,
        product__is_active=True,
        image_file__classification="PRODUCT_PUBLIC",
        image_file__mime_type="image/jpeg",
        image_file__scan_status="VALIDATED",
        image_file__purged_at__isnull=True,
    )
    path = (settings.PRIVATE_ROOT / variant.image_file.storage_key).resolve()
    if not path.is_relative_to(settings.PRIVATE_ROOT.resolve()) or not path.is_file():
        raise Http404
    return FileResponse(path.open("rb"), content_type="image/jpeg")


def site_image(request, pk):
    """Only referenced, validated marketing images may be served publicly."""
    file = get_object_or_404(
        PrivateFile,
        pk=pk,
        classification="SITE_PUBLIC",
        mime_type="image/jpeg",
        scan_status="VALIDATED",
        purged_at__isnull=True,
    )
    public = (
        StoreSettings.objects.filter(logo_file=file).exists()
        or SiteContent.objects.filter(image_file=file, is_active=True).exists()
        or Species.objects.filter(image_file=file, is_active=True).exists()
        or Category.objects.filter(image_file=file, is_active=True).exists()
        or Service.objects.filter(image_file=file, is_active=True).exists()
    )
    if not public and not (request.user.is_authenticated and active_role(request.user) in READ_ALL):
        raise Http404
    path = (settings.PRIVATE_ROOT / file.storage_key).resolve()
    if not path.is_relative_to(settings.PRIVATE_ROOT.resolve()) or not path.is_file():
        raise Http404
    return FileResponse(path.open("rb"), content_type="image/jpeg")


def product_detail(request, pk):
    product = get_object_or_404(
        ProductVariant.objects.select_related("product__category", "image_file"),
        pk=pk,
        is_active=True,
        product__is_active=True,
        product__category__is_active=True,
    )
    from inventory.services import available

    product.available = available(product)
    variants = ProductVariant.objects.filter(product=product.product, is_active=True).order_by(
        "price_rp"
    )
    return render(request, "public/product_detail.html", {"product": product, "variants": variants})
