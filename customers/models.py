"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class Customer(TimestampedModel):
    """Satu User maksimal satu Customer. Nomor telepon dan nama bukan kunci penggabungan otomatis."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    name = models.CharField(max_length=150, default="", blank=True)
    contact_email = models.CharField(max_length=254, default="", blank=True, null=True)
    phone = models.CharField(max_length=32, default="", blank=True, null=True)
    origin = models.CharField(max_length=20, default="", blank=True)
    linked_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)


class Pet(TimestampedModel):
    """Berat positif bila diisi. Nama hewan tidak unik. Pergantian pemilik melalui proses terotorisasi; hak rekam lama tidak berpindah otomatis."""

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    species = models.ForeignKey("catalog.Species", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=100, default="", blank=True)
    breed = models.CharField(max_length=100, default="", blank=True, null=True)
    sex = models.CharField(
        max_length=20,
        default="",
        blank=True,
        choices=[("MALE", "Jantan"), ("FEMALE", "Betina"), ("UNKNOWN", "Belum diketahui")],
    )
    birth_date = models.DateField(null=True, blank=True)
    estimated_birth_date = models.BooleanField(default=False)
    weight_kg = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)
    allergies = models.TextField(default="", blank=True, null=True)
    handling_notes = models.TextField(default="", blank=True, null=True)
    photo_file = models.ForeignKey(
        "core.PrivateFile", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(weight_kg__isnull=True) | Q(weight_kg__gt=0), name="pet_weight_positive"
            ),
        ]


class Address(TimestampedModel):
    """CHECK rentang koordinat; maksimal satu alamat default per customer. Alamat ini tidak mengubah snapshot pesanan lama."""

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    label = models.CharField(max_length=60, default="", blank=True)
    recipient_name = models.CharField(max_length=150, default="", blank=True)
    recipient_phone = models.CharField(max_length=32, default="", blank=True)
    address_line = models.TextField(default="", blank=True)
    province = models.CharField(max_length=100, default="", blank=True)
    city = models.CharField(max_length=100, default="", blank=True)
    district = models.CharField(max_length=100, default="", blank=True)
    village = models.CharField(max_length=100, default="", blank=True, null=True)
    postal_code = models.CharField(max_length=12, default="", blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, default=0)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    delivery_note = models.TextField(default="", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["customer"], name="one_default_address", condition=Q(is_default=True)
            ),
            models.CheckConstraint(
                condition=Q(
                    latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180
                ),
                name="valid_address_coordinates",
            ),
        ]


class EmergencyContact(TimestampedModel):
    """Kontak penitipan dapat berbeda dari nomor akun dan penerima paket. Snapshot disimpan pada masa inap."""

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=150, default="", blank=True)
    relationship = models.CharField(max_length=60, default="", blank=True)
    phone = models.CharField(max_length=32, default="", blank=True)
    contact_consent = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
