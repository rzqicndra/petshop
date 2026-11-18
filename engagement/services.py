from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from accounts.permissions import require_role, OPS
from billing.models import Invoice
from core.services import BusinessError, commerce_transaction, emit, audit
from .models import Review, ReviewModeration, Reminder


def save_review(actor, rating, comment, booking=None, order_item=None):
    require_role(actor, {"CUSTOMER"})
    if (
        bool(booking) == bool(order_item)
        or not 1 <= rating <= 5
        or not comment.strip()
        or len(comment) > 2000
    ):
        raise BusinessError("Pilih transaksi dan tulis ulasan dengan rating 1 sampai 5.")
    target = booking or order_item.order
    if target.customer.user_id != actor.pk or target.status != "COMPLETED":
        raise BusinessError("Ulasan tersedia setelah transaksi milik Anda selesai.")
    paid = (
        Invoice.objects.filter(booking=booking, status="PAID").exists()
        if booking
        else Invoice.objects.filter(order=target, status="PAID").exists()
    )
    if not paid:
        raise BusinessError("Pembayaran transaksi belum selesai.")
    with commerce_transaction():
        query = {"booking": booking} if booking else {"order_item": order_item}
        review = Review.objects.select_for_update().filter(**query).first()
        if review:
            # Editing a hidden review does not silently undo a moderation decision.
            review.rating, review.comment, review.edited_at = rating, comment, timezone.now()
            review.save()
        else:
            review = Review.objects.create(
                customer=target.customer,
                rating=rating,
                comment=comment,
                status="PUBLISHED",
                **query,
            )
        audit(actor, "review.saved", review, after={"rating": rating})
        return review


def moderate_review(actor, review, hide, reason):
    require_role(actor, OPS)
    if not reason.strip():
        raise BusinessError(
            "Alasan moderasi wajib dicatat. Rating negatif yang sah tetap ditampilkan."
        )
    with commerce_transaction():
        review = Review.objects.select_for_update().get(pk=review.pk)
        review.status = "HIDDEN" if hide else "PUBLISHED"
        review.save()
        ReviewModeration.objects.create(
            review=review, moderator=actor, action="HIDE" if hide else "PUBLISH", reason=reason
        )
        audit(actor, "review.moderated", review, reason=reason)


def sync_booking_reminders(booking):
    Reminder.objects.filter(booking=booking, status="PENDING").update(status="CANCELED")
    if booking.status not in {"CONFIRMED", "IN_SERVICE"}:
        return
    kind = "BOARDING_CHECKOUT" if booking.kind_snapshot == "BOARDING" else "BOOKING"
    at = (
        booking.ends_at - timedelta(hours=4)
        if kind == "BOARDING_CHECKOUT"
        else booking.starts_at - timedelta(hours=24)
    )
    Reminder.objects.get_or_create(
        dedupe_key=f"booking:{booking.pk}:v{booking.version}:{kind}",
        defaults={
            "customer": booking.customer,
            "booking": booking,
            "kind": kind,
            "source_version": booking.version,
            "scheduled_at": max(at, timezone.now()),
            "status": "PENDING",
        },
    )


def sync_medical_reminder(record):
    Reminder.objects.filter(record_version__visit=record.visit, status="PENDING").update(
        status="CANCELED"
    )
    if record.followup_at:
        Reminder.objects.get_or_create(
            dedupe_key=f"medical:{record.visit_id}:v{record.version_no}",
            defaults={
                "customer": record.visit.booking.customer,
                "record_version": record,
                "kind": "FOLLOWUP",
                "source_version": record.version_no,
                "scheduled_at": max(timezone.now(), record.followup_at - timedelta(days=1)),
                "status": "PENDING",
            },
        )


def queue_due_reminders():
    with commerce_transaction():
        for reminder in (
            # Nullable source joins must not be included in PostgreSQL row locks.
            Reminder.objects.select_for_update(of=("self",))
            .filter(status="PENDING", scheduled_at__lte=timezone.now())
            .select_related("booking", "record_version", "customer")[:100]
        ):
            if (
                reminder.booking_id
                and (
                    reminder.booking.version != reminder.source_version
                    or reminder.booking.status not in {"CONFIRMED", "IN_SERVICE"}
                )
            ) or (reminder.record_version_id and not reminder.record_version.is_current):
                reminder.status = "CANCELED"
            elif not reminder.customer.user_id:
                reminder.status = "SKIPPED"
            else:
                emit(
                    "reminder.email",
                    reminder,
                    {"user_id": str(reminder.customer.user_id), "reminder_id": str(reminder.pk)},
                )
                reminder.status = "QUEUED"
            reminder.save()
