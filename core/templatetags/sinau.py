from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def rating_marks(value):
    return [index <= int(value or 0) for index in range(1, 6)]


@register.filter
def reviewer_name(value):
    names = str(value or "Pelanggan").split() or ["Pelanggan"]
    return names[0] + (" " + names[-1][0] + "." if len(names) > 1 else "")


@register.filter
def rupiah(value):
    try:
        return "Rp" + f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


@register.filter
def status_tone(value):
    if value in {
        "COMPLETED",
        "PAID",
        "ACTIVE",
        "DELIVERED",
        "SENT",
        "DONE",
        "CONFIRMED",
        "PUBLISHED",
    }:
        return "green"
    if value in {"EXPIRED", "REJECTED", "CANCELED", "VOID", "HIDDEN", "FAILED", "NO_SHOW"}:
        return "red"
    if value in {
        "NEEDS_ATTENTION",
        "UNKNOWN",
        "SUBMITTED",
        "AWAITING_PAYMENT",
        "UNPAID",
        "APPROVED_AWAITING_PAYMENT",
    }:
        return "amber"
    return "blue"


@register.filter
def initials(value):
    return "".join(part[0].upper() for part in str(value).split()[:2])


@register.filter
def payment_label(value):
    return {
        "CREATING": "Menyiapkan pembayaran",
        "PENDING": "Menunggu pembayaran",
        "UNKNOWN": "Perlu rekonsiliasi",
        "SETTLED": "Diterima",
        "FAILED": "Tidak berhasil",
        "APPLIED": "Diterapkan ke tagihan",
        "DUPLICATE_FUNDS": "Dana ganda perlu ditangani",
        "NEEDS_ATTENTION": "Perlu penanganan",
        "REFUNDED": "Dana dikembalikan penuh",
        "PARTIALLY_REFUNDED": "Sebagian dana dikembalikan",
        "MOCK": "Pembayaran uji",
        "MIDTRANS": "Pembayaran online",
        "CASH": "Tunai",
    }.get(value, value)


@register.filter
def status_label(value):
    labels = {
        "EXPIRED": "Waktu habis",
        "CANCELED": "Dibatalkan",
        "VOID": "Ditutup",
        "SUBMITTED": "Menunggu persetujuan",
        "AWAITING_PAYMENT": "Menunggu pembayaran",
        "UNPAID": "Belum dibayar",
        "PAID": "Lunas",
        "COMPLETED": "Selesai",
        "NO_SHOW": "Tidak hadir",
        "CONFIRMED": "Dikonfirmasi",
        "IN_SERVICE": "Dalam perawatan",
        "READY_PICKUP": "Siap dijemput",
        "PACKED": "Siap dikirim",
        "DELIVERED": "Diterima",
        "REJECTED": "Ditolak",
        "NEEDS_ATTENTION": "Perlu ditinjau",
        "APPROVED_AWAITING_PAYMENT": "Disetujui, menunggu pembayaran",
    }
    return labels.get(value, str(value).replace("_", " ").capitalize())


@register.filter
def invoice_available(invoice):
    if not invoice or invoice.status in {"VOID", "EXPIRED"}:
        return False
    if invoice.status == "UNPAID" and invoice.expires_at and invoice.expires_at <= timezone.now():
        return False
    if invoice.order_id and invoice.order.status in {"CANCELED", "EXPIRED"}:
        return False
    if invoice.booking_id and invoice.booking.status in {"CANCELED", "EXPIRED", "REJECTED"}:
        return False
    return True


ICON_PATHS = {
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "close": '<path d="m6 6 12 12M6 18 18 6"/>',
    "home": '<path d="m3 10 9-7 9 7v10H3zM9 20v-7h6v7"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4M17 3v4M3 11h18M7 15h2M13 15h2"/>',
    "paw": '<ellipse cx="12" cy="16" rx="6" ry="4"/><ellipse cx="5" cy="8" rx="2" ry="3"/><ellipse cx="10" cy="5" rx="2" ry="3"/><ellipse cx="16" cy="5" rx="2" ry="3"/><ellipse cx="20" cy="10" rx="2" ry="3"/>',
    "box": '<path d="m3 7 9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4M12 11v10M7 5l10 4"/>',
    "bag": '<path d="M5 7h14l1 14H4zM8 8V6a4 4 0 0 1 8 0v2"/>',
    "pin": '<path d="M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
    "users": '<circle cx="9" cy="8" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2M17 4a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 5v2"/>',
    "shield": '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6"/>',
    "truck": '<path d="M3 5h12v12H3zM15 9h4l3 4v4h-7"/><circle cx="7" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',
    "chart": '<path d="M4 3v17h17M8 15l4-5 4 2 5-7"/>',
    "star": '<path d="m12 3 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z"/>',
    "settings": '<path d="m9 3-1 3-3 1 1 4-2 2 2 4 3-1 2 2 3-1 2-2 3 1 2-4-2-2 1-4-3-1-1-3z"/><circle cx="12" cy="12" r="3"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "edit": '<path d="m15 4 5 5M4 20l5-1L21 7l-4-4L5 15z"/>',
    "trash": '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    "arrow": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "upload": '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
    "file": '<path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8M8 17h6"/>',
    "heart": '<path d="M20 5a5 5 0 0 1 0 7l-8 9-8-9a5 5 0 0 1 8-6 5 5 0 0 1 8-1Z"/>',
    "store": '<path d="M3 10h18l-2-7H5zM5 10v11h14V10M9 21v-7h6v7"/>',
    "tag": '<path d="M3 3h9l9 9-9 9-9-9z"/><circle cx="8" cy="8" r="1"/>',
    "logout": '<path d="M9 3H4v18h5M9 12h12m-5-5 5 5-5 5"/>',
    "lock": '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m3 6 9 7 9-7"/>',
    "chevron": '<path d="m9 5 7 7-7 7"/>',
    "google": '<path fill="#4285F4" stroke="none" d="M21.6 12.2c0-.7-.1-1.4-.2-2.1H12v4h5.4a4.6 4.6 0 0 1-2 3v2.5h3.3c1.9-1.8 2.9-4.3 2.9-7.4Z"/><path fill="#34A853" stroke="none" d="M12 22c2.7 0 5-1 6.7-2.4l-3.3-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.2H3v2.6A10 10 0 0 0 12 22Z"/><path fill="#FBBC05" stroke="none" d="M6.4 13.9a6 6 0 0 1 0-3.8V7.5H3a10 10 0 0 0 0 9l3.4-2.6Z"/><path fill="#EA4335" stroke="none" d="M12 5.9c1.5 0 2.8.5 3.9 1.5L18.8 4A9.5 9.5 0 0 0 12 2a10 10 0 0 0-9 5.5l3.4 2.6C7.2 7.7 9.4 5.9 12 5.9Z"/>',
    "whatsapp": '<g transform="scale(1.5)"><path fill="currentColor" stroke="none" d="M13.601 2.326A7.85 7.85 0 0 0 7.994 0C3.627 0 .068 3.558.064 7.926c0 1.399.366 2.76 1.057 3.965L0 16l4.204-1.102a7.9 7.9 0 0 0 3.79.965h.004c4.368 0 7.926-3.558 7.93-7.93A7.9 7.9 0 0 0 13.6 2.326zM7.994 14.521a6.6 6.6 0 0 1-3.356-.92l-.24-.144-2.494.654.666-2.433-.156-.251a6.56 6.56 0 0 1-1.007-3.505c0-3.626 2.957-6.584 6.591-6.584a6.56 6.56 0 0 1 4.66 1.931 6.56 6.56 0 0 1 1.928 4.66c-.004 3.639-2.961 6.592-6.592 6.592m3.615-4.934c-.197-.099-1.17-.578-1.353-.646-.182-.065-.315-.099-.445.099-.133.197-.513.646-.627.775-.114.133-.232.148-.43.05-.197-.1-.836-.308-1.592-.985-.59-.525-.985-1.175-1.103-1.372-.114-.198-.011-.304.088-.403.087-.088.197-.232.296-.346.1-.114.133-.198.198-.33.065-.134.034-.248-.015-.347-.05-.099-.445-1.076-.612-1.47-.16-.389-.323-.335-.445-.34-.114-.007-.247-.007-.38-.007a.73.73 0 0 0-.529.247c-.182.198-.691.677-.691 1.654s.71 1.916.81 2.049c.098.133 1.394 2.132 3.383 2.992.47.205.84.326 1.129.418.475.152.904.129 1.246.08.38-.058 1.171-.48 1.338-.943.164-.464.164-.86.114-.943-.049-.084-.182-.133-.38-.232"/></g>',
}


@register.simple_tag
def icon(name):
    from django.utils.safestring import mark_safe

    paths = ICON_PATHS.get(name, ICON_PATHS["grid"])
    return mark_safe(
        '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        + paths
        + "</svg>"
    )


@register.simple_tag
def content_image(content):
    from django.urls import reverse
    from django.templatetags.static import static

    if content and content.image_file_id:
        return reverse("site_image", args=[content.image_file_id])
    return static(content.fallback_image) if content and content.fallback_image else ""


@register.simple_tag
def service_image(service):
    from django.urls import reverse
    from django.templatetags.static import static

    if service.image_file_id:
        return reverse("site_image", args=[service.image_file_id])
    return static(
        {"GROOMING": "images/grooming-care.jpg", "VET": "images/vet-care.jpg"}.get(
            service.kind, "images/dog-hero.jpg"
        )
    )
