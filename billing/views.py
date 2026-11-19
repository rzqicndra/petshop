import json
import uuid
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET
from accounts.permissions import verified_login, active_role, READ_ALL, OPS, require_role
from core.services import BusinessError, fingerprint
from .models import Invoice, InvoiceLine, PaymentAttempt, PaymentEvent, PaymentTransaction, Refund
from . import services, providers


@verified_login
@require_GET
def payment_return(request):
    """Provider query strings are navigation hints, never proof of payment."""
    attempts = PaymentAttempt.objects.filter(
        provider="MIDTRANS", provider_order_id=request.GET.get("order_id", "")[:100]
    )
    if active_role(request.user) not in READ_ALL:
        attempts = attempts.filter(invoice__customer__user=request.user)
    attempt = get_object_or_404(attempts)
    # Settlement is applied only by authenticated provider GET / webhook processing.
    # Returning here performs no state change on GET. The invoice offers POST status check.
    messages.info(
        request, "Periksa status tagihan. Parameter kembali dari pembayaran bukan bukti lunas."
    )
    return redirect("invoice", pk=attempt.invoice_id)


def _visible_invoice(request, pk):
    qs = (
        Invoice.objects.all()
        if active_role(request.user) in READ_ALL
        else Invoice.objects.filter(customer__user=request.user)
    )
    invoice = get_object_or_404(qs.select_related("customer"), pk=pk)
    if active_role(request.user) == "CUSTOMER":
        from django.http import Http404
        from django.utils import timezone

        inactive_target = (
            invoice.order_id and invoice.order.status in {"CANCELED", "EXPIRED"}
        ) or (invoice.booking_id and invoice.booking.status in {"CANCELED", "EXPIRED", "REJECTED"})
        if (
            invoice.status in {"VOID", "EXPIRED"}
            or inactive_target
            or (
                invoice.status == "UNPAID"
                and invoice.expires_at
                and invoice.expires_at <= timezone.now()
            )
        ):
            raise Http404
    return invoice


@verified_login
@require_GET
def invoice_pdf(request, pk):
    from django.http import FileResponse
    from core.services import audit
    from .documents import invoice_document

    invoice = _visible_invoice(request, pk)
    output = invoice_document(invoice)
    audit(request.user, "invoice.pdf_downloaded", invoice)
    return FileResponse(
        output, as_attachment=True, filename=f"{invoice.code}.pdf", content_type="application/pdf"
    )


@verified_login
def invoice_view(request, pk):
    invoice = _visible_invoice(request, pk)
    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "pay":
                attempt = services.begin_payment(
                    request.user, invoice, request.POST.get("key", str(uuid.uuid4()))
                )
                if attempt.session_url and attempt.status == "PENDING":
                    return redirect(attempt.session_url)
                messages.info(
                    request,
                    (
                        "Sesi pembayaran tersedia di bawah."
                        if attempt.provider == "MOCK"
                        else "Status sesi perlu diperiksa sebelum pembayaran dilanjutkan."
                    ),
                )
            elif action == "simulate":
                if (
                    active_role(request.user) != "CUSTOMER"
                    or not settings.LOCAL_MODE
                    or settings.PAYMENT_MODE != "mock"
                ):
                    raise PermissionDenied
                attempt = get_object_or_404(
                    PaymentAttempt, pk=request.POST.get("attempt"), invoice=invoice, provider="MOCK"
                )
                services.apply_settled_payment(
                    attempt, "mock-" + str(attempt.pk), attempt.expected_amount_rp
                )
                messages.success(
                    request, "Pembayaran simulasi dicatat. Tidak ada dana nyata yang dipindahkan."
                )
            elif action == "cash":
                services.record_cash(request.user, invoice, request.POST.get("key", ""))
                messages.success(request, "Penerimaan tunai dicatat.")
            else:
                raise BusinessError("Tindakan tidak tersedia.")
        except BusinessError as exc:
            messages.error(request, exc.messages[0])
        except Exception as exc:
            if isinstance(exc, PermissionDenied):
                raise
            messages.error(
                request,
                "Penyedia belum dapat dihubungi. Coba pemeriksaan status lagi; jangan mengulang pembayaran yang sudah berhasil.",
            )
        return redirect("invoice", pk=pk)
    return render(
        request,
        "billing/invoice.html",
        {
            "invoice": invoice,
            "lines": InvoiceLine.objects.filter(invoice=invoice).order_by("created_at", "pk"),
            "target": invoice.booking or invoice.order or invoice.extension.stay.booking,
            "attempts": PaymentAttempt.objects.filter(invoice=invoice).order_by("-created_at"),
            "payments": PaymentTransaction.objects.filter(invoice=invoice),
            "can_operate": active_role(request.user) in OPS,
            "payment_mode": settings.PAYMENT_MODE,
            "key": str(uuid.uuid4()),
        },
    )


@csrf_exempt
@require_POST
def midtrans_webhook(request):
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or not providers.verify_notification(payload):
            return JsonResponse({"error": "unauthorized"}, status=403)
        attempt = PaymentAttempt.objects.filter(
            provider_order_id=payload["order_id"], provider="MIDTRANS"
        ).first()
        if not attempt:
            return JsonResponse({"error": "unknown reference"}, status=404)
        key = fingerprint(
            {
                k: payload.get(k)
                for k in (
                    "order_id",
                    "transaction_id",
                    "transaction_status",
                    "status_code",
                    "gross_amount",
                )
            }
        )
        event, _ = PaymentEvent.objects.get_or_create(
            provider="MIDTRANS",
            event_key=key,
            defaults={
                "attempt": attempt,
                "payload_redacted": {
                    "order_id": payload["order_id"],
                    "transaction_status": payload.get("transaction_status"),
                },
                "authentic": True,
                "received_at": timezone.now(),
                "processing_status": "RECEIVED",
            },
        )
        if event.processed_at:
            return JsonResponse({"ok": True})
        services.reconcile_attempt(attempt, payload)
        PaymentEvent.objects.filter(pk=event.pk).update(
            processed_at=timezone.now(), processing_status="DONE"
        )
        return JsonResponse({"ok": True})
    except (ValueError, BusinessError, KeyError):
        return JsonResponse({"error": "invalid notification"}, status=400)
    except Exception:
        return JsonResponse({"error": "temporary verification failure"}, status=503)


@verified_login
def invoice_status(request, pk):
    """Read database state only; provider reconciliation is done by background workers."""
    from django.views.decorators.http import require_GET
    from django.http import HttpResponseNotAllowed
    from accounts.permissions import require_role
    from django.urls import reverse
    from core.templatetags.sinau import invoice_available

    require_role(request.user, {"CUSTOMER"})
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    invoice = get_object_or_404(
        Invoice.objects.select_related("order", "booking", "extension__stay__booking"),
        pk=pk,
        customer__user=request.user,
    )
    if invoice.order_id:
        return_url = reverse("order_detail", kwargs={"pk": invoice.order_id})
    else:
        booking_id = invoice.booking_id or invoice.extension.stay.booking_id
        return_url = reverse("booking_detail", kwargs={"pk": booking_id})
    return JsonResponse(
        {
            "status": invoice.status,
            "closed": not invoice_available(invoice),
            "return_url": return_url,
        }
    )
