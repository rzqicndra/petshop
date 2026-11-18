"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class DeliveryPolicy(TimestampedModel):
    """Singleton; tarif dan jangkauan perlu data client. Contoh 5.000 meter tidak ditetapkan sebagai nilai produksi."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    internal_enabled = models.BooleanField(default=False)
    max_route_m = models.IntegerField(default=0)
    base_fee_rp = models.BigIntegerField(default=0)
    per_km_fee_rp = models.BigIntegerField(default=0)
    max_weight_g = models.IntegerField(default=0)
    max_length_cm = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    max_width_cm = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    max_height_cm = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    packaging_weight_g = models.IntegerField(default=0)
    travel_mode = models.CharField(max_length=30, default="", blank=True)
    service_hours = models.JSONField(default=dict, blank=True)
    version = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(id=1, max_route_m__gt=0, max_weight_g__gt=0, version__gt=0),
                name="policy_singleton_positive",
            ),
        ]


class DeliveryWindow(TimestampedModel):
    """Mulai<akhir, max_orders>0. Ketersediaan dihitung dari reservasi aktif; kunci window saat mengisi kuota."""

    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(default=timezone.now)
    max_orders = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(starts_at__lt=F("ends_at"), max_orders__gt=0),
                name="delivery_window_time_quota",
            ),
        ]


class ShippingQuote(TimestampedModel):
    """Quote harus cocok order, alamat, isi paket, dan versi kebijakan. Requote bila habis atau isi berubah."""

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="+")
    provider = models.CharField(max_length=30, default="", blank=True)
    service_code = models.CharField(max_length=60, default="", blank=True)
    method = models.CharField(max_length=20, default="", blank=True)
    window = models.ForeignKey(
        "delivery.DeliveryWindow", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    route_distance_m = models.IntegerField(default=0)
    travel_mode = models.CharField(max_length=30, default="", blank=True)
    fee_rp = models.BigIntegerField(default=0)
    package_snapshot = models.JSONField(default=dict, blank=True)
    address_fingerprint = models.CharField(max_length=64, default="", blank=True)
    origin_fingerprint = models.CharField(max_length=64, default="", blank=True)
    origin_snapshot = models.JSONField(default=dict, blank=True)
    provider_reference = models.CharField(max_length=160, default="", blank=True, null=True)
    policy_version = models.IntegerField(default=0)
    expires_at = models.DateTimeField(default=timezone.now)


class DeliveryReservation(TimestampedModel):
    """Status HELD/CONFIRMED/FULFILLED/RELEASED/EXPIRED. Kuota window mengurangi slot dari HELD, CONFIRMED dan FULFILLED; hanya RELEASED/EXPIRED dapat dipakai ulang."""

    order = models.OneToOneField("orders.Order", on_delete=models.PROTECT, related_name="+")
    window = models.ForeignKey(
        "delivery.DeliveryWindow", on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(max_length=20, default="", blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)


class Shipment(TimestampedModel):
    """UQ(order_id,attempt_no) dan UQ(provider,provider_shipment_id) bila ID ada. Satu shipment aktif, termasuk REQUESTING dan UNKNOWN. Timeout harus direkonsiliasi sebelum retry."""

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="+")
    quote = models.ForeignKey("delivery.ShippingQuote", on_delete=models.PROTECT, related_name="+")
    attempt_no = models.IntegerField(default=0)
    method = models.CharField(max_length=20, default="", blank=True)
    provider = models.CharField(max_length=30, default="", blank=True)
    provider_shipment_id = models.CharField(max_length=160, default="", blank=True, null=True)
    status = models.CharField(
        max_length=30,
        default="",
        blank=True,
        choices=[
            ("REQUESTING", "Memesan kurir"),
            ("UNKNOWN", "Perlu rekonsiliasi"),
            ("READY", "Siap dikirim"),
            ("CONFIRMED", "Dipesan"),
            ("ALLOCATED", "Kurir ditugaskan"),
            ("IN_TRANSIT", "Dalam pengiriman"),
            ("ON_HOLD", "Tertunda"),
            ("RETURNING", "Dikembalikan"),
            ("RETURNED", "Telah kembali"),
            ("DELIVERED", "Terkirim"),
            ("CANCELED", "Dibatalkan"),
            ("REJECTED", "Ditolak"),
            ("DISPOSED", "Dimusnahkan"),
        ],
    )
    request_key = models.CharField(max_length=160, default="", blank=True, unique=True)
    tracking_code = models.CharField(max_length=160, default="", blank=True, null=True)
    handed_over_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    actual_fee_rp = models.BigIntegerField(null=True, blank=True)
    cost_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    cost_approval_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "attempt_no"], name="shipment_attempt_unique"),
            models.UniqueConstraint(
                fields=["provider", "provider_shipment_id"],
                name="provider_shipment_unique",
                condition=Q(provider_shipment_id__isnull=False) & ~Q(provider_shipment_id=""),
            ),
            models.UniqueConstraint(
                fields=["order"],
                name="one_active_shipment",
                condition=Q(
                    status__in=[
                        "REQUESTING",
                        "UNKNOWN",
                        "READY",
                        "CONFIRMED",
                        "ALLOCATED",
                        "IN_TRANSIT",
                        "ON_HOLD",
                        "RETURNING",
                    ]
                ),
            ),
        ]


class ShipmentEvent(TimestampedModel):
    """UQ(shipment_id,event_key). Status terminal tidak diturunkan oleh event lama."""

    shipment = models.ForeignKey("delivery.Shipment", on_delete=models.PROTECT, related_name="+")
    event_key = models.CharField(max_length=180, default="", blank=True)
    status = models.CharField(max_length=30, default="", blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    payload_redacted = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["shipment", "event_key"], name="shipment_event_unique"),
        ]


class RouteEstimate(models.Model):
    """Short-lived shared route cache: hashed coordinates, no user/address identifiers."""

    cache_key = models.CharField(max_length=64, primary_key=True)
    distance_m = models.PositiveIntegerField()
    expires_at = models.DateTimeField(db_index=True)


class DeliveryAssignment(TimestampedModel):
    """Hanya method INTERNAL; kurir harus memiliki izin dan hanya melihat tugasnya. Pergantian petugas dicatat audit."""

    shipment = models.OneToOneField("delivery.Shipment", on_delete=models.PROTECT, related_name="+")
    courier_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    recipient_name = models.CharField(max_length=150, default="", blank=True, null=True)
    proof_file = models.ForeignKey(
        "core.PrivateFile", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    completed_at = models.DateTimeField(null=True, blank=True)
