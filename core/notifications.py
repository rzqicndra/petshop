"""Durable outbox delivery. Ambiguous SMTP outcomes are not blindly retried."""

import smtplib
import socket
from datetime import timedelta
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.db import transaction
from django.utils import timezone
from accounts.models import User
from customers.models import Customer
from engagement.models import NotificationDelivery, Reminder
from .models import OutboxEvent, StoreSettings
from .services import cipher


def deliver_outbox(limit=50):
    processed = 0
    for _ in range(limit):
        with transaction.atomic():
            now = timezone.now()
            event = (
                OutboxEvent.objects.select_for_update(skip_locked=True)
                .filter(status__in={"PENDING", "RETRY"}, next_attempt_at__lte=now)
                .order_by("created_at")
                .first()
            )
            if not event:
                break
            if event.expires_at and event.expires_at <= now:
                event.status, event.sensitive_ciphertext = "EXPIRED", None
                event.save()
                continue
            user_id = event.payload.get("user_id")
            if not user_id and event.payload.get("customer_id"):
                user_id = (
                    Customer.objects.filter(pk=event.payload["customer_id"])
                    .values_list("user_id", flat=True)
                    .first()
                )
            user = User.objects.filter(pk=user_id, is_active=True).first() if user_id else None
            if not user:
                event.status, event.sensitive_ciphertext = "SKIPPED", None
                event.save()
                continue
            reminder = (
                Reminder.objects.filter(pk=event.payload.get("reminder_id")).first()
                if event.topic == "reminder.email"
                else None
            )
            if reminder and (
                (
                    reminder.booking_id
                    and (
                        reminder.booking.version != reminder.source_version
                        or reminder.booking.status not in {"CONFIRMED", "IN_SERVICE"}
                    )
                )
                or (reminder.record_version_id and not reminder.record_version.is_current)
            ):
                reminder.status = "CANCELED"
                reminder.save()
                event.status = "CANCELED"
                event.save()
                continue
            delivery, _ = NotificationDelivery.objects.get_or_create(
                dedupe_key=f"email:{event.pk}",
                defaults={
                    "user": user,
                    "outbox_event": event,
                    "reminder": reminder,
                    "otp_challenge_id": event.aggregate_id if event.topic == "auth.otp" else None,
                    "channel": "EMAIL",
                    "status": "PENDING",
                },
            )
            if delivery.status == "SENT":
                event.status, event.sensitive_ciphertext = "DONE", None
                event.save()
                continue
            if event.topic == "auth.otp":
                challenge = delivery.otp_challenge
                if (
                    challenge.target_email != user.email
                    or challenge.invalidated_at
                    or challenge.consumed_at
                    or challenge.expires_at <= now
                ):
                    event.status, event.sensitive_ciphertext = "CANCELED", None
                    event.save()
                    continue
                raw = cipher().decrypt(event.sensitive_ciphertext.encode()).decode()
                subject = "Kode verifikasi Sinau Satwa"
                purpose_label = {
                    "REGISTER": "verifikasi email",
                    "RESET": "pengaturan password",
                    "INVITE": "undangan akun",
                }.get(event.payload["purpose"], "verifikasi akun")
                body = f"Kode verifikasi Anda: {raw}\n\nBerlaku 5 menit untuk {purpose_label}. Jangan bagikan kode ini kepada siapa pun.\nAbaikan email jika Anda tidak meminta verifikasi."
                if event.payload["purpose"] == "INVITE":
                    from django.core import signing

                    token = signing.dumps(
                        {
                            "user": str(user.pk),
                            "version": user.auth_version,
                            "challenge": str(challenge.pk),
                        },
                        salt="staff-invite",
                    )
                    from urllib.parse import urlencode

                    body += f"\n\nBuka undangan lalu masukkan OTP dan atur password: {settings.APP_URL}/undangan/?{urlencode({'token': token})}"
            else:
                subject = "Informasi layanan Sinau Satwa"
                body = (
                    "Ada pembaruan transaksi atau pengingat perawatan Anda. Login untuk melihat informasi terkini: "
                    + settings.APP_URL
                    + "/dashboard/"
                )
            event.status = "PROCESSING"
            event.attempt_count += 1
            event.save()
            delivery.status = "SENDING"
            delivery.attempt_count += 1
            delivery.save()
        # SMTP outside locks. Stable Message-ID helps tracing; it is not a provider idempotency guarantee.
        try:
            mail = EmailMultiAlternatives(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                headers={"Message-ID": f"<{event.pk}@notifications.sinau-satwa>"},
            )
            if event.topic == "auth.otp":
                mail.attach_alternative(
                    render_to_string(
                        "emails/otp.html",
                        {
                            "otp": raw,
                            "brand": StoreSettings.objects.filter(pk=1).first(),
                            "purpose": event.payload["purpose"],
                            "invite_url": (
                                settings.APP_URL + "/undangan/?" + urlencode({"token": token})
                                if event.payload["purpose"] == "INVITE"
                                else None
                            ),
                        },
                    ),
                    "text/html",
                )
            if mail.send(fail_silently=False) != 1:
                raise smtplib.SMTPServerDisconnected("No delivery acknowledgement")
        except (ConnectionRefusedError, socket.gaierror):
            state = "RETRY" if event.attempt_count < 3 else "FAILED"
            OutboxEvent.objects.filter(pk=event.pk).update(
                status=state,
                next_attempt_at=timezone.now() + timedelta(seconds=30 * 2**event.attempt_count),
            )
            NotificationDelivery.objects.filter(pk=delivery.pk).update(status=state)
        except Exception:
            OutboxEvent.objects.filter(pk=event.pk).update(status="UNKNOWN")
            NotificationDelivery.objects.filter(pk=delivery.pk).update(status="UNKNOWN")
        else:
            with transaction.atomic():
                OutboxEvent.objects.filter(pk=event.pk).update(
                    status="DONE", processed_at=timezone.now(), sensitive_ciphertext=None
                )
                NotificationDelivery.objects.filter(pk=delivery.pk).update(
                    status="SENT", sent_at=timezone.now()
                )
                if reminder:
                    Reminder.objects.filter(pk=reminder.pk).update(status="SENT")
        processed += 1
    # A crashed worker leaves uncertainty, not permission to repeat an external side effect.
    stale = timezone.now() - timedelta(minutes=5)
    OutboxEvent.objects.filter(status="PROCESSING", updated_at__lt=stale).update(status="UNKNOWN")
    NotificationDelivery.objects.filter(status="SENDING", updated_at__lt=stale).update(
        status="UNKNOWN"
    )
    OutboxEvent.objects.filter(expires_at__lte=timezone.now()).exclude(
        sensitive_ciphertext__isnull=True
    ).update(sensitive_ciphertext=None)
    return processed
