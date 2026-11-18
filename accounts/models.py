"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class ExternalIdentity(TimestampedModel):
    """UQ(provider, subject). Google sub menjadi identitas; linking membutuhkan pembuktian kontrol akun."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    provider = models.CharField(max_length=20, default="", blank=True)
    subject = models.CharField(max_length=255, default="", blank=True)
    linked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "subject"], name="identity_provider_subject"
            ),
        ]


class OTPChallenge(TimestampedModel):
    """Satu tantangan terbuka per user dan purpose. Habis waktu diinvalidasi secara transaksional sebelum penerbitan ulang. Tidak menyimpan OTP plaintext. Target email diikat ke challenge; perubahan email menginvalidasi kode lama."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    purpose = models.CharField(max_length=30, default="", blank=True)
    target_email = models.CharField(max_length=254, default="", blank=True)
    code_digest = models.CharField(max_length=255, default="", blank=True)
    expires_at = models.DateTimeField(default=timezone.now)
    attempt_count = models.IntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    generation = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "purpose"],
                name="otp_one_open",
                condition=Q(consumed_at__isnull=True, invalidated_at__isnull=True),
            ),
        ]


from .users import User


class RateLimitBucket(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    window_start = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)


class AccountSecurity(TimestampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="security")
    totp_ciphertext = models.TextField(blank=True)
    enabled_at = models.DateTimeField(null=True, blank=True)
    last_counter = models.BigIntegerField(default=-1)
    recovery_digests = models.JSONField(default=list, blank=True)
