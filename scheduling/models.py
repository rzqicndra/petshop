"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class Service(TimestampedModel):
    """Kind VET, GROOMING atau BOARDING."""

    code = models.CharField(max_length=40, default="", blank=True, unique=True)
    name = models.CharField(max_length=100, default="", blank=True)
    kind = models.CharField(
        max_length=20,
        default="",
        blank=True,
        choices=[("VET", "Dokter hewan"), ("GROOMING", "Grooming"), ("BOARDING", "Penitipan")],
    )
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    image_file = models.ForeignKey(
        "core.PrivateFile", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )


class ServicePackage(TimestampedModel):
    """Harga dan durasi wajib untuk VET/GROOMING. BOARDING menghitung harga dari tarif unit yang dipilih; price_rp paket kosong."""

    service = models.ForeignKey("scheduling.Service", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=120, default="", blank=True)
    price_rp = models.BigIntegerField(default=0, null=True, blank=True)
    duration_minutes = models.IntegerField(default=0, null=True, blank=True)
    buffer_minutes = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        from .availability import MAX_MINUTES

        if self.service_id and self.service.kind in MAX_MINUTES:
            limit = MAX_MINUTES[self.service.kind]
            if not 0 < (self.duration_minutes or 0) <= limit:
                raise ValidationError(
                    {"duration_minutes": f"Isi durasi sesi antara 1 dan {limit} menit."}
                )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(price_rp__isnull=True) | Q(price_rp__gt=0),
                name="package_positive_price",
            ),
            models.CheckConstraint(
                condition=Q(duration_minutes__isnull=True) | Q(duration_minutes__gt=0),
                name="package_positive_duration",
            ),
            models.CheckConstraint(
                condition=Q(buffer_minutes__gte=0), name="package_nonnegative_buffer"
            ),
        ]


class PackageSpecies(TimestampedModel):
    """UQ(package_id,species_id)."""

    package = models.ForeignKey(
        "scheduling.ServicePackage", on_delete=models.PROTECT, related_name="+"
    )
    species = models.ForeignKey("catalog.Species", on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["package", "species"], name="package_species_unique"),
        ]


class Resource(TimestampedModel):
    """Jenis STAFF, STATION atau BOARDING_UNIT. Resource STAFF terhubung satu User; tugas medis/grooming mengikuti izin akun."""

    code = models.CharField(max_length=50, default="", blank=True, unique=True)
    kind = models.CharField(
        max_length=25,
        default="",
        blank=True,
        choices=[("STAFF", "Staf"), ("STATION", "Fasilitas"), ("BOARDING_UNIT", "Unit penitipan")],
    )
    staff_user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    name = models.CharField(max_length=120, default="", blank=True)
    is_active = models.BooleanField(default=True)


class StaffShift(TimestampedModel):
    """Mulai<akhir; hanya resource staf. Jadwal efektif berdasarkan shift, libur dan reservasi blok."""

    resource = models.ForeignKey("scheduling.Resource", on_delete=models.PROTECT, related_name="+")
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(default=timezone.now)
    is_available = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(starts_at__lt=F("ends_at")), name="shift_time_order"
            ),
        ]


class Booking(TimestampedModel):
    """Mulai<akhir; kind_snapshot cocok paket. Cegah overlap hewan pada VET/GROOMING aktif dan pada BOARDING aktif secara terpisah. Customer sah saat dibuat. Customer transaksi tetap sebagai audience historis. Setiap perubahan jadwal mengubah version."""

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    pet = models.ForeignKey("customers.Pet", on_delete=models.PROTECT, related_name="+")
    package = models.ForeignKey(
        "scheduling.ServicePackage", on_delete=models.PROTECT, related_name="+"
    )
    code = models.CharField(max_length=40, default="", blank=True, unique=True)
    origin = models.CharField(max_length=20, default="", blank=True)
    kind_snapshot = models.CharField(max_length=20, default="", blank=True)
    status = models.CharField(
        max_length=30,
        default="",
        blank=True,
        choices=[
            ("SUBMITTED", "Menunggu tinjauan"),
            ("AWAITING_PAYMENT", "Menunggu pembayaran"),
            ("CONFIRMED", "Terjadwal"),
            ("IN_SERVICE", "Sedang dilayani"),
            ("READY_PICKUP", "Siap dijemput"),
            ("COMPLETED", "Selesai"),
            ("CANCELED", "Dibatalkan"),
            ("EXPIRED", "Kedaluwarsa"),
            ("NEEDS_ATTENTION", "Perlu penanganan"),
        ],
    )
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(default=timezone.now)
    price_snapshot_rp = models.BigIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    policy_snapshot = models.JSONField(default=dict, blank=True)
    version = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(starts_at__lt=F("ends_at"), price_snapshot_rp__gte=0),
                name="booking_time_price",
            ),
            ExclusionConstraint(
                name="pet_service_no_overlap",
                expressions=[
                    ("pet", RangeOperators.EQUAL),
                    (
                        models.Func(
                            F("starts_at"),
                            F("ends_at"),
                            models.Value("[)"),
                            function="TSTZRANGE",
                            output_field=DateTimeRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=Q(
                    kind_snapshot__in=["VET", "GROOMING"],
                    status__in=[
                        "HELD",
                        "AWAITING_PAYMENT",
                        "CONFIRMED",
                        "IN_SERVICE",
                        "READY_PICKUP",
                    ],
                ),
            ),
            ExclusionConstraint(
                name="pet_boarding_no_overlap",
                expressions=[
                    ("pet", RangeOperators.EQUAL),
                    (
                        models.Func(
                            F("starts_at"),
                            F("ends_at"),
                            models.Value("[)"),
                            function="TSTZRANGE",
                            output_field=DateTimeRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=Q(
                    kind_snapshot="BOARDING",
                    status__in=["HELD", "AWAITING_PAYMENT", "CONFIRMED", "IN_SERVICE"],
                ),
            ),
        ]


class ResourceReservation(TimestampedModel):
    """EXCLUDE overlap per resource untuk HELD/CONFIRMED/IN_USE/BLOCKED. Rentang [awal,akhir). BLOCK memerlukan alasan; extension harus milik booking yang sama."""

    resource = models.ForeignKey("scheduling.Resource", on_delete=models.PROTECT, related_name="+")
    booking = models.ForeignKey(
        "scheduling.Booking", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    extension = models.ForeignKey(
        "boarding.ExtensionRequest",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    period = DateTimeRangeField()
    kind = models.CharField(max_length=25, default="", blank=True)
    status = models.CharField(max_length=20, default="", blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(default="", blank=True, null=True)

    class Meta:
        constraints = [
            ExclusionConstraint(
                name="resource_period_no_overlap",
                expressions=[
                    ("resource", RangeOperators.EQUAL),
                    ("period", RangeOperators.OVERLAPS),
                ],
                condition=Q(status__in=["HELD", "CONFIRMED", "IN_USE", "BLOCKED"]),
            ),
            models.CheckConstraint(
                condition=Q(period__isempty=False), name="reservation_not_empty"
            ),
        ]


class PackageResource(TimestampedModel):
    """One resource from each pool is required; several entries in a pool are alternatives."""

    package = models.ForeignKey(ServicePackage, on_delete=models.PROTECT, related_name="+")
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="+")
    pool = models.CharField(max_length=30, default="STAFF")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["package", "resource"], name="package_resource_unique")
        ]
