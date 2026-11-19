from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from accounts.permissions import roles_required
from core.forms import ReviewForm
from core.services import BusinessError
from core.selectors import visible_bookings, visible_orders
from orders.models import OrderItem
from .models import Review
from .services import save_review, moderate_review


@roles_required("CUSTOMER")
def review_view(request, kind, pk):
    booking, item = None, None
    if kind == "booking":
        booking = get_object_or_404(visible_bookings(request.user), pk=pk, status="COMPLETED")
        previous = Review.objects.filter(booking=booking).first()
    elif kind == "produk":
        item = get_object_or_404(
            OrderItem, pk=pk, order__in=visible_orders(request.user).filter(status="COMPLETED")
        )
        previous = Review.objects.filter(order_item=item).first()
    else:
        from django.http import Http404

        raise Http404
    form = ReviewForm(
        request.POST or None,
        initial={"rating": previous.rating, "comment": previous.comment} if previous else None,
    )
    if request.method == "POST" and form.is_valid():
        try:
            save_review(
                request.user,
                form.cleaned_data["rating"],
                form.cleaned_data["comment"],
                booking,
                item,
            )
            messages.success(
                request, "Terima kasih. Ulasan terhubung dengan transaksi Anda yang sudah selesai."
            )
            return redirect(
                "booking_detail" if booking else "order_detail",
                pk=booking.pk if booking else item.order_id,
            )
        except BusinessError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "engagement/review.html",
        {
            "form": form,
            "target": booking or item,
            "target_label": booking.package.name if booking else item.product_name,
            "target_code": booking.code if booking else item.order.code,
            "rating_options": [
                (1, "Kurang baik"),
                (2, "Perlu ditingkatkan"),
                (3, "Cukup baik"),
                (4, "Baik"),
                (5, "Sangat baik"),
            ],
        },
    )


@roles_required("SUPER_ADMIN", "ADMIN", "OWNER")
def moderation_view(request):
    if request.method == "POST":
        review = get_object_or_404(Review, pk=request.POST.get("review"))
        try:
            moderate_review(
                request.user,
                review,
                request.POST.get("action") == "hide",
                request.POST.get("reason", "")[:2000],
            )
            messages.success(request, "Keputusan moderasi dicatat.")
        except BusinessError as exc:
            messages.error(request, exc.messages[0])
        return redirect("moderation")
    return render(
        request,
        "engagement/moderation.html",
        {"reviews": Review.objects.select_related("customer").order_by("-created_at")[:100]},
    )
