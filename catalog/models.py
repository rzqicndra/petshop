"""Domain models. Mutations are orchestrated by the module services."""

from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower
from django.utils import timezone
from core.base import TimestampedModel
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.contrib.postgres.constraints import ExclusionConstraint


class Species(TimestampedModel):
    """Kode seperti CAT dan DOG berasal dari katalog master; bukan nama hewan."""

    code = models.CharField(max_length=30, default="", blank=True, unique=True)
    name = models.CharField(max_length=60, default="", blank=True)
    is_active = models.BooleanField(default=True)
    image_file = models.ForeignKey(
        "core.PrivateFile", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )


class Category(TimestampedModel):
    """Tidak boleh menjadi induk dirinya; siklus hirarki dicegah layanan katalog."""

    parent = models.ForeignKey(
        "catalog.Category", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    code = models.CharField(max_length=50, default="", blank=True, unique=True)
    name = models.CharField(max_length=100, default="", blank=True)
    is_active = models.BooleanField(default=True)
    image_file = models.ForeignKey(
        "core.PrivateFile", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~Q(id=F("parent_id")), name="category_not_self"),
        ]


class Product(TimestampedModel):
    """Kategori utama per produk pada baseline; produk dipensiunkan, tidak menghapus riwayat item."""

    category = models.ForeignKey("catalog.Category", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=180, default="", blank=True)
    description = models.TextField(default="", blank=True)
    is_active = models.BooleanField(default=True)


class ProductSpecies(TimestampedModel):
    """UQ(product_id, species_id)."""

    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    species = models.ForeignKey("catalog.Species", on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "species"], name="product_species_unique"),
        ]


class ProductVariant(TimestampedModel):
    """Harga positif pada baseline; berat dan dimensi positif untuk produk kiriman. Stok tidak digandakan pada tabel ini."""

    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    sku = models.CharField(max_length=80, default="", blank=True, unique=True)
    label = models.CharField(max_length=120, default="", blank=True)
    price_rp = models.BigIntegerField(default=0)
    weight_g = models.IntegerField(default=0)
    length_cm = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    width_cm = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    height_cm = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    tracks_expiry = models.BooleanField(default=False)
    image_path = models.TextField(default="", blank=True, null=True)
    image_file = models.ForeignKey(
        "core.PrivateFile", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    price_rp__gt=0, weight_g__gt=0, length_cm__gt=0, width_cm__gt=0, height_cm__gt=0
                ),
                name="sku_positive_values",
            ),
        ]
