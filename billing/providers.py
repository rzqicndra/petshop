"""Midtrans HTTP boundary. A browser callback never settles an invoice."""

import hashlib
import hmac
from decimal import Decimal, InvalidOperation
import requests
from django.urls import reverse
from urllib.parse import urlencode
from django.conf import settings
from core.services import BusinessError


def _host(service):
    if service == "snap":
        return (
            "https://app.midtrans.com"
            if settings.MIDTRANS_LIVE
            else "https://app.sandbox.midtrans.com"
        )
    return (
        "https://api.midtrans.com" if settings.MIDTRANS_LIVE else "https://api.sandbox.midtrans.com"
    )


class SessionRejected(BusinessError):
    """Provider definitively rejected creation; safe to create a new attempt."""


def create_snap(attempt):
    if not settings.MIDTRANS_SERVER_KEY:
        raise SessionRejected("Kunci Midtrans belum dikonfigurasi.")
    return_url = (
        settings.APP_URL
        + reverse("payment_return")
        + "?"
        + urlencode({"order_id": attempt.provider_order_id})
    )
    headers = {"Accept": "application/json"}
    if settings.PUBLIC_WEBHOOK_BASE_URL:
        headers["X-Override-Notification"] = settings.PUBLIC_WEBHOOK_BASE_URL + reverse(
            "midtrans_webhook"
        )
    response = requests.post(
        _host("snap") + "/snap/v1/transactions",
        auth=(settings.MIDTRANS_SERVER_KEY, ""),
        json={
            "transaction_details": {
                "order_id": attempt.provider_order_id,
                "gross_amount": attempt.expected_amount_rp,
            },
            "callbacks": {"finish": return_url, "error": return_url},
            "expiry": {
                "unit": "minutes",
                "duration": max(
                    1, int((attempt.expires_at - attempt.created_at).total_seconds() // 60)
                ),
            },
        },
        headers=headers,
        timeout=(5, 20),
    )
    # Conflict, throttling and timeout remain ambiguous; never blindly recreate.
    rejected = response.status_code in {401, 403, 404, 422}
    if response.status_code == 400:
        try:
            errors = response.json().get("error_messages", [])
            # Snap can use HTTP 400 for an already-utilized order ID.
            rejected = bool(errors) and isinstance(errors, list) and all(
                isinstance(message, str) and "order_id" not in message.lower()
                and "already" not in message.lower() and "sudah" not in message.lower()
                for message in errors
            )
        except (ValueError, AttributeError):
            rejected = False
    if rejected:
        raise SessionRejected("Sesi pembayaran ditolak penyedia. Periksa konfigurasi pembayaran.")
    response.raise_for_status()
    data = response.json()
    url = data.get("redirect_url", "")
    if not url.startswith(_host("snap") + "/"):
        raise BusinessError("Sesi pembayaran tidak valid.")
    return {"redirect_url": url, "token": data.get("token", "")}


def verify_notification(payload):
    if not settings.MIDTRANS_SERVER_KEY:
        return False
    fields = ("order_id", "status_code", "gross_amount", "signature_key")
    if any(not isinstance(payload.get(k), str) for k in fields):
        return False
    raw = (
        payload["order_id"]
        + payload["status_code"]
        + payload["gross_amount"]
        + settings.MIDTRANS_SERVER_KEY
    )
    expected = hashlib.sha512(raw.encode()).hexdigest()
    return hmac.compare_digest(expected, payload["signature_key"])


def get_status(provider_order_id):
    response = requests.get(
        _host("core") + f"/v2/{provider_order_id}/status",
        auth=(settings.MIDTRANS_SERVER_KEY, ""),
        timeout=(5, 15),
    )
    if response.status_code == 404:
        return {"transaction_status": "not_found", "order_id": provider_order_id}
    response.raise_for_status()
    return response.json()


def settled(payload):
    return (
        payload.get("transaction_status") in {"settlement", "capture"}
        and payload.get("fraud_status", "accept") == "accept"
    )


def rupiah(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
            raise ValueError
        return int(amount)
    except (InvalidOperation, ValueError):
        raise BusinessError("Nominal pembayaran tidak valid.")
