import hashlib
import secrets
from datetime import timedelta

import pyotp
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.services import BusinessError, cipher, emit, audit
from customers.models import Customer
from .models import User, OTPChallenge, RateLimitBucket, AccountSecurity


def rate_limit(scope, identifier, limit, seconds):
    """DB-backed, shared by all web processes. Never trust client-supplied forwarding headers."""
    now = timezone.now()
    digest = hashlib.sha256(f"{scope}:{identifier}".encode()).hexdigest()
    with transaction.atomic():
        RateLimitBucket.objects.get_or_create(key=digest, defaults={"window_start": now})
        row = RateLimitBucket.objects.select_for_update().get(pk=digest)
        if row.window_start <= now - timedelta(seconds=seconds):
            row.window_start, row.count = now, 0
        row.count += 1
        row.save(update_fields=["window_start", "count"])
        blocked = row.count > limit
    if blocked:
        raise BusinessError("Terlalu banyak percobaan. Coba lagi beberapa saat lagi.")


def issue_otp(user, purpose):
    if purpose not in {"REGISTER", "RESET", "INVITE"}:
        raise BusinessError("Tujuan verifikasi tidak valid.")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        previous = (
            OTPChallenge.objects.filter(user=user, purpose=purpose).order_by("-created_at").first()
        )
        now = timezone.now()
        if previous and previous.created_at > now - timedelta(seconds=settings.OTP_RESEND_SECONDS):
            return None  # Same generic UI response; the previous challenge remains valid.
        OTPChallenge.objects.filter(
            user=user, purpose=purpose, consumed_at__isnull=True, invalidated_at__isnull=True
        ).update(invalidated_at=now)
        raw = f"{secrets.randbelow(1000000):06d}"
        challenge = OTPChallenge.objects.create(
            user=user,
            purpose=purpose,
            target_email=user.email,
            code_digest=make_password(f"{purpose}:{user.email}:{raw}"),
            expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
            generation=(previous.generation + 1 if previous else 1),
        )
        emit(
            "auth.otp",
            challenge,
            {"user_id": str(user.pk), "email": user.email, "purpose": purpose},
            secret=raw,
            expires_at=challenge.expires_at,
        )
        return challenge


def verify_otp(user_id, purpose, raw):
    success, result = False, None
    with transaction.atomic():
        user = (
            User.objects.select_for_update().filter(pk=user_id, is_active=True).first()
            if user_id
            else None
        )
        challenge = (
            OTPChallenge.objects.select_for_update()
            .filter(
                user=user, purpose=purpose, consumed_at__isnull=True, invalidated_at__isnull=True
            )
            .first()
            if user
            else None
        )
        now = timezone.now()
        if challenge:
            challenge.attempt_count += 1
            valid = (
                challenge.expires_at > now
                and challenge.target_email == user.email
                and challenge.attempt_count <= settings.OTP_MAX_ATTEMPTS
            )
            success = valid and check_password(
                f"{purpose}:{user.email}:{raw}", challenge.code_digest
            )
            if success:
                challenge.consumed_at = now
                result = user
            elif not valid or challenge.attempt_count >= settings.OTP_MAX_ATTEMPTS:
                challenge.invalidated_at = now
            challenge.save(
                update_fields=["attempt_count", "consumed_at", "invalidated_at", "updated_at"]
            )
    # Raise outside the transaction so failed-attempt counters cannot roll back.
    if not success:
        raise BusinessError(
            "Kode tidak valid atau sudah melewati batas waktu. Periksa email atau kirim ulang."
        )
    return result


@transaction.atomic
def create_customer_user(email, full_name, password=None):
    user = User.objects.create_user(email=email, full_name=full_name, password=password)
    group, _ = Group.objects.get_or_create(name="CUSTOMER")
    user.groups.add(group)
    Customer.objects.create(
        user=user,
        name=full_name,
        contact_email=user.email,
        origin="ONLINE",
        is_active=True,
        linked_at=timezone.now(),
    )
    return user


def verify_totp(user, code):
    accepted = False
    with transaction.atomic():
        sec = (
            AccountSecurity.objects.select_for_update()
            .filter(user=user, enabled_at__isnull=False)
            .first()
        )
        if not sec:
            return False
        totp = pyotp.TOTP(cipher().decrypt(sec.totp_ciphertext.encode()).decode())
        counter = int(timezone.now().timestamp()) // 30
        for step in (counter - 1, counter, counter + 1):
            if step > sec.last_counter and secrets.compare_digest(totp.at(step * 30), str(code)):
                sec.last_counter = step
                accepted = True
                break
        if not accepted:
            for i, digest in enumerate(sec.recovery_digests):
                if check_password(str(code), digest):
                    sec.recovery_digests.pop(i)
                    accepted = True
                    break
        if accepted:
            sec.save(update_fields=["last_counter", "recovery_digests", "updated_at"])
    return accepted
