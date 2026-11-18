"""Small shared primitives; business rules stay in their own domain modules."""

import hashlib
import json
import secrets
import uuid
from contextlib import contextmanager
from datetime import timedelta

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from .models import AuditLog, OutboxEvent, IdempotencyRecord


class BusinessError(ValidationError):
    """An expected user-facing domain rejection, without internal implementation details."""


def code(prefix):
    return f"SS-{prefix}-{timezone.localdate():%y%m%d}-{secrets.token_hex(4).upper()}"


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def cipher():
    return Fernet(settings.DATA_ENCRYPTION_KEY.encode())


def audit(actor, action, obj, before=None, after=None, reason=""):
    from .request_context import request_id

    # Callers pass allowlisted fields, never raw request bodies, passwords, or clinical text.
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        aggregate_type=obj.__class__.__name__,
        aggregate_id=obj.pk,
        before_redacted=before,
        after_redacted=after,
        reason=reason,
        request_id=request_id.get() or uuid.uuid4(),
        occurred_at=timezone.now(),
    )


def emit(topic, obj, payload=None, secret=None, expires_at=None):
    return OutboxEvent.objects.create(
        topic=topic,
        aggregate_type=obj.__class__.__name__,
        aggregate_id=obj.pk,
        payload=payload or {},
        sensitive_ciphertext=cipher().encrypt(secret.encode()).decode() if secret else None,
        expires_at=expires_at,
        status="PENDING",
        next_attempt_at=timezone.now(),
    )


@contextmanager
def commerce_transaction():
    """One store: serialize short commerce mutations, then lock their concrete rows.

    No provider HTTP call is permitted inside this transaction. The PostgreSQL advisory lock
    also coordinates expiry, payment callbacks and reservation allocation across workers.
    Exclusion/unique/check constraints remain the final database protection.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [742091031])
        yield


def idempotent(scope, key, actor, payload):
    if not key or len(key) > 180:
        raise BusinessError("Kunci permintaan tidak valid. Muat ulang formulir.")
    digest = fingerprint(payload)
    row, created = IdempotencyRecord.objects.get_or_create(
        scope=scope,
        key=key,
        defaults={
            "actor": actor,
            "request_fingerprint": digest,
            "status": "PENDING",
            "expires_at": timezone.now() + timedelta(days=7),
        },
    )
    if row.actor_id != getattr(actor, "pk", None) or row.request_fingerprint != digest:
        raise BusinessError("Permintaan yang sama memiliki isi berbeda. Muat ulang formulir.")
    return row, created
