from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from accounts.permissions import require_role, OPS
from core.services import BusinessError, commerce_transaction, code, audit, emit
from .models import Invoice, InvoiceLine, PaymentAttempt, PaymentEvent, PaymentTransaction, Refund
from . import providers


def issue_invoice(target, customer, amount, description, expires_at, parent=None):
    field = {"Order": "order", "Booking": "booking", "ExtensionRequest": "extension"}[
        target.__class__.__name__
    ]
    stage = "EXTENSION" if parent else "INITIAL"
    invoice, created = Invoice.objects.get_or_create(
        business_key=f"{field}:{target.pk}:{stage}",
        defaults={
            field: target,
            "customer": customer,
            "code": code("INV"),
            "stage": stage,
            "status": "UNPAID",
            "currency": "IDR",
            "total_rp": amount,
            "expires_at": expires_at,
            "parent_invoice": parent,
        },
    )
    if created:
        InvoiceLine.objects.create(
            invoice=invoice,
            description=description,
            quantity=1,
            unit_amount_rp=amount,
            line_total_rp=amount,
        )
    return invoice


def begin_payment(actor, invoice, request_key):
    require_role(actor, {"CUSTOMER"})
    if settings.PAYMENT_MODE == "disabled":
        raise BusinessError("Pembayaran online belum diaktifkan.")
    if invoice.customer.user_id != actor.pk:
        require_role(actor, OPS)
    with commerce_transaction():
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if (
            invoice.status != "UNPAID"
            or not invoice.expires_at
            or invoice.expires_at <= timezone.now()
        ):
            raise BusinessError("Tagihan sudah dibayar atau melewati batas waktu.")
        # Mock has no real funds. It can be retired safely when enabling a gateway.
        if settings.PAYMENT_MODE != "mock":
            PaymentAttempt.objects.filter(
                invoice=invoice, provider="MOCK", status__in={"CREATING", "PENDING", "UNKNOWN"}
            ).update(status="FAILED")
        prior = (
            PaymentAttempt.objects.filter(
                invoice=invoice, status__in={"CREATING", "PENDING", "UNKNOWN"}
            )
            .order_by("-created_at")
            .first()
        )
        if prior:
            if prior.provider == "MIDTRANS" and prior.environment != settings.PAYMENT_MODE:
                raise BusinessError(
                    "Tagihan memiliki sesi di lingkungan pembayaran lain atau versi lama. Rekonsiliasi admin diperlukan; jangan mengulang pembayaran."
                )
            return prior
        attempt = PaymentAttempt.objects.create(
            invoice=invoice,
            provider="MOCK" if settings.PAYMENT_MODE == "mock" else "MIDTRANS",
            environment=settings.PAYMENT_MODE,
            provider_order_id=code("PAY"),
            method="SNAP",
            status="CREATING",
            expected_amount_rp=invoice.total_rp,
            expires_at=invoice.expires_at,
            request_key=request_key,
        )
    if attempt.provider == "MOCK":
        if not settings.LOCAL_MODE:
            raise BusinessError("Simulasi pembayaran tidak tersedia.")
        attempt.status = "PENDING"
        attempt.save(update_fields=["status", "updated_at"])
        return attempt
    try:
        result = providers.create_snap(attempt)
        PaymentAttempt.objects.filter(pk=attempt.pk, status="CREATING").update(
            status="PENDING", session_url=result["redirect_url"]
        )
    except providers.SessionRejected:
        PaymentAttempt.objects.filter(pk=attempt.pk, status="CREATING").update(status="FAILED")
        raise BusinessError(
            "Sesi pembayaran ditolak. Hubungi pengelola bila berulang, lalu coba kembali setelah konfigurasi diperbaiki."
        )
    except Exception:
        PaymentAttempt.objects.filter(pk=attempt.pk, status="CREATING").update(status="UNKNOWN")
        raise BusinessError(
            "Sesi pembayaran belum terkonfirmasi. Cek status dahulu sebelum mencoba kembali."
        )
    attempt.refresh_from_db()
    return attempt


def apply_settled_payment(attempt, transaction_id, amount, currency="IDR", cashier=None):
    """Only called after authenticated provider verification or an authorized cash receipt."""
    with commerce_transaction():
        invoice = Invoice.objects.select_for_update().get(pk=attempt.invoice_id)
        attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
        if amount != attempt.expected_amount_rp or amount != invoice.total_rp or currency != "IDR":
            raise BusinessError(
                "Nominal atau mata uang tidak sesuai tagihan. Perlu rekonsiliasi admin."
            )
        previous = PaymentTransaction.objects.filter(
            provider=attempt.provider, provider_transaction_id=transaction_id
        ).first()
        if previous:
            if previous.invoice_id != invoice.pk or previous.amount_rp != amount:
                raise BusinessError("Identitas transaksi penyedia tidak sesuai.")
            return previous
        applies = not PaymentTransaction.objects.filter(invoice=invoice, is_applied=True).exists()
        payment = PaymentTransaction.objects.create(
            attempt=attempt,
            invoice=invoice,
            provider=attempt.provider,
            provider_transaction_id=transaction_id,
            amount_rp=amount,
            currency=currency,
            settled_at=timezone.now(),
            is_applied=applies,
            handling_status="APPLIED" if applies else "DUPLICATE_FUNDS",
            cashier=cashier,
        )
        attempt.status = "SETTLED"
        attempt.save(update_fields=["status", "updated_at"])
        if applies:
            invoice.status, invoice.paid_at = "PAID", timezone.now()
            invoice.save()
            fulfilled = activate_target(invoice)
            if not fulfilled:
                payment.handling_status = "NEEDS_ATTENTION"
                payment.save(update_fields=["handling_status", "updated_at"])
            emit(
                "invoice.paid",
                invoice,
                {"customer_id": str(invoice.customer_id), "code": invoice.code},
            )
        audit(
            cashier,
            "billing.payment_received",
            payment,
            after={"amount_rp": amount, "is_applied": applies},
        )
        return payment


def activate_target(invoice):
    from scheduling.models import Booking, ResourceReservation
    from engagement.services import sync_booking_reminders

    if invoice.extension_id:
        from boarding.services import activate_extension

        return activate_extension(invoice.extension)
    if invoice.booking_id:
        booking = Booking.objects.select_for_update().get(pk=invoice.booking_id)
        reservations = ResourceReservation.objects.filter(
            booking=booking, extension__isnull=True, status="HELD"
        )
        valid = (
            booking.status == "AWAITING_PAYMENT"
            and booking.expires_at > timezone.now()
            and reservations.exists()
            and not reservations.filter(expires_at__lte=timezone.now()).exists()
        )
        if valid:
            reservations.update(status="CONFIRMED", expires_at=None)
            booking.status, booking.expires_at = "CONFIRMED", None
        else:
            ResourceReservation.objects.filter(booking=booking, status="HELD").update(
                status="RELEASED"
            )
            booking.status = "NEEDS_ATTENTION"
        booking.save()
        sync_booking_reminders(booking)
        return valid
    from orders.models import Order
    from inventory.services import consume_order, release_order
    from delivery.models import DeliveryReservation

    order = Order.objects.select_for_update().get(pk=invoice.order_id)
    valid = order.status == "AWAITING_PAYMENT" and consume_order(order)
    if valid:
        order.status = "PAID"
        DeliveryReservation.objects.filter(order=order, status="HELD").update(
            status="CONFIRMED", expires_at=None
        )
    else:
        release_order(order)
        DeliveryReservation.objects.filter(order=order, status="HELD").update(status="RELEASED")
        order.status = "NEEDS_ATTENTION"
    order.save()
    return valid


def reconcile_attempt(attempt, payload=None):
    if attempt.provider != "MIDTRANS":
        raise BusinessError("Rekonsiliasi ini khusus Midtrans.")
    if attempt.environment != settings.PAYMENT_MODE:
        raise BusinessError(
            "Lingkungan sesi pembayaran berbeda atau belum diketahui. Rekonsiliasi dengan konfigurasi asal diperlukan."
        )
    verified = providers.get_status(
        attempt.provider_order_id
    )  # HTTP happens outside all database locks.
    if verified.get("order_id") != attempt.provider_order_id:
        raise BusinessError("Referensi pembayaran tidak sesuai.")
    if providers.settled(verified):
        txid = verified.get("transaction_id")
        if not txid:
            raise BusinessError("ID dana penyedia belum tersedia.")
        return apply_settled_payment(
            attempt,
            txid,
            providers.rupiah(verified.get("gross_amount")),
            verified.get("currency", "IDR"),
        )
    state = verified.get("transaction_status")
    if state in {"deny", "cancel", "expire", "failure"}:
        PaymentAttempt.objects.filter(pk=attempt.pk).exclude(status="SETTLED").update(
            status="FAILED"
        )
    return None


def record_cash(actor, invoice, key):
    require_role(actor, OPS)
    with commerce_transaction():
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != "UNPAID" or invoice.expires_at <= timezone.now():
            raise BusinessError("Tagihan sudah dibayar atau melewati batas waktu.")
        attempt, _ = PaymentAttempt.objects.get_or_create(
            request_key=key,
            defaults={
                "invoice": invoice,
                "provider": "CASH",
                "provider_order_id": code("CASH"),
                "method": "CASH",
                "status": "PENDING",
                "expected_amount_rp": invoice.total_rp,
                "expires_at": invoice.expires_at,
            },
        )
        if attempt.invoice_id != invoice.pk:
            raise BusinessError("Kunci penerimaan sudah digunakan.")
        return apply_settled_payment(
            attempt, attempt.provider_order_id, invoice.total_rp, cashier=actor
        )


def request_refund(actor, payment, amount, reason, key):
    require_role(actor, OPS)
    if amount <= 0 or not reason.strip():
        raise BusinessError("Nominal positif dan alasan refund wajib diisi.")
    with commerce_transaction():
        payment = PaymentTransaction.objects.select_for_update().get(pk=payment.pk)
        previous = Refund.objects.filter(request_key=key).first()
        if previous:
            if previous.payment_id != payment.pk or previous.amount_rp != amount:
                raise BusinessError("Kunci refund sudah digunakan.")
            return previous
        used = sum(
            Refund.objects.filter(payment=payment)
            .exclude(status="REJECTED")
            .values_list("amount_rp", flat=True)
        )
        if used + amount > payment.amount_rp:
            raise BusinessError("Total refund melampaui dana yang diterima.")
        refund = Refund.objects.create(
            payment=payment,
            requested_by=actor,
            amount_rp=amount,
            reason=reason,
            status="REQUESTED",
            request_key=key,
        )
        audit(actor, "billing.refund_requested", refund, after={"amount_rp": amount}, reason=reason)
        return refund


def process_refund(actor, refund, action, reference=""):
    require_role(actor, {"SUPER_ADMIN"})
    with commerce_transaction():
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        if action == "reject" and refund.status == "REQUESTED":
            refund.status = "REJECTED"
        elif action == "approve" and refund.status == "REQUESTED":
            refund.status, refund.approved_by = "APPROVED", actor
        elif action == "complete" and refund.status == "APPROVED" and reference.strip():
            # Actual bank/provider refund occurs externally, with an auditable reconciliation reference.
            refund.status, refund.completed_at, refund.provider_refund_id = (
                "COMPLETED",
                timezone.now(),
                reference,
            )
        else:
            raise BusinessError("Tahap refund tidak sesuai atau referensi bukti belum diisi.")
        refund.save()
        if action == "complete":
            from django.db.models import Sum

            payment = PaymentTransaction.objects.select_for_update().get(pk=refund.payment_id)
            returned = (
                Refund.objects.filter(payment=payment, status="COMPLETED").aggregate(
                    value=Sum("amount_rp")
                )["value"]
                or 0
            )
            payment.handling_status = (
                "REFUNDED" if returned == payment.amount_rp else "PARTIALLY_REFUNDED"
            )
            payment.save(update_fields=["handling_status", "updated_at"])
        audit(actor, "billing.refund_" + action, refund, after={"status": refund.status})


def fully_refunded(invoice):
    from django.db.models import Sum

    amount = (
        Refund.objects.filter(
            payment__invoice=invoice, payment__is_applied=True, status="COMPLETED"
        ).aggregate(value=Sum("amount_rp"))["value"]
        or 0
    )
    return invoice.status == "PAID" and amount >= invoice.total_rp


def expire_unpaid():
    from orders.models import Order
    from inventory.services import release_order
    from delivery.models import DeliveryReservation
    from scheduling.services import expire_capacity_holds
    from scheduling.models import ResourceReservation
    from boarding.models import ExtensionRequest

    with commerce_transaction():
        now = timezone.now()
        expire_capacity_holds()
        for order in Order.objects.select_for_update().filter(
            status="AWAITING_PAYMENT", expires_at__lte=now
        ):
            release_order(order)
            order.status = "EXPIRED"
            order.save()
            DeliveryReservation.objects.filter(order=order, status="HELD").update(status="EXPIRED")
        for ext in ExtensionRequest.objects.select_for_update().filter(
            status="APPROVED_AWAITING_PAYMENT", payment_expires_at__lte=now
        ):
            ResourceReservation.objects.filter(extension=ext, status="HELD").update(
                status="EXPIRED"
            )
            ext.status = "EXPIRED"
            ext.save()
        Invoice.objects.filter(status="UNPAID", expires_at__lte=now).update(status="EXPIRED")
        for rr in ResourceReservation.objects.filter(
            status="IN_USE", booking__status="COMPLETED", period__endswith__lte=now
        ):
            rr.status = "RELEASED"
            rr.save()
