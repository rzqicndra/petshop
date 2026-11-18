from celery import shared_task


@shared_task
def maintenance():
    from billing.services import expire_unpaid
    from engagement.services import queue_due_reminders
    from .notifications import deliver_outbox

    expire_unpaid()
    queue_due_reminders()
    deliver_outbox()
    from billing.models import PaymentAttempt
    from billing.services import reconcile_attempt
    from django.utils import timezone
    from datetime import timedelta

    for attempt in PaymentAttempt.objects.filter(
        provider="MIDTRANS",
        status__in={"PENDING", "UNKNOWN"},
        created_at__gt=timezone.now() - timedelta(days=2),
    ).order_by("updated_at")[:20]:
        try:
            reconcile_attempt(attempt)
        except Exception:
            continue  # Keep pending; no provider payload or secret is logged.
    from delivery.models import Shipment
    from delivery.providers import get_external_shipment
    from delivery.services import apply_shipment_status, TERMINAL
    from .services import commerce_transaction, fingerprint

    for shipment in (
        Shipment.objects.filter(provider="BITESHIP", provider_shipment_id__isnull=False)
        .exclude(status__in=TERMINAL)
        .order_by("updated_at")[:20]
    ):
        try:
            result = get_external_shipment(shipment.provider_shipment_id)
            with commerce_transaction():
                locked = Shipment.objects.select_for_update().get(pk=shipment.pk)
                apply_shipment_status(locked, result, fingerprint(result))
        except Exception:
            continue
