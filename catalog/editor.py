"""One product editor for identity, sellable variant, audience and initial inventory."""

import uuid
from django import forms
from django.utils import timezone
from core.admin import ProductForm
from core.files import upload_transaction
from core.services import audit, commerce_transaction
from inventory.models import InventoryBatch
from inventory.services import receive_stock
from .models import Product, ProductVariant, Species, ProductSpecies


class CatalogProductForm(ProductForm):
    species = forms.ModelMultipleChoiceField(
        queryset=Species.objects.none(),
        label="Untuk jenis hewan",
        required=False,
        help_text="Kosongkan untuk produk yang cocok bagi semua hewan.",
    )
    sku = forms.CharField(label="SKU / kode barang", max_length=80)
    variant_label = forms.CharField(label="Ukuran / nama varian", max_length=120)
    price_rp = forms.IntegerField(label="Harga (Rp)", min_value=1)
    weight_g = forms.IntegerField(label="Berat produk (gram)", min_value=1)
    length_cm = forms.DecimalField(
        label="Panjang paket (cm)", min_value=1, max_digits=7, decimal_places=2
    )
    width_cm = forms.DecimalField(
        label="Lebar paket (cm)", min_value=1, max_digits=7, decimal_places=2
    )
    height_cm = forms.DecimalField(
        label="Tinggi paket (cm)", min_value=1, max_digits=7, decimal_places=2
    )
    variant_active = forms.BooleanField(
        label="Tampilkan varian ini di katalog", required=False, initial=True
    )
    initial_stock = forms.IntegerField(
        label="Stok awal",
        min_value=0,
        max_value=100000,
        initial=0,
        help_text="Untuk produk baru. Penambahan stok berikutnya melalui Persediaan.",
    )
    tracks_expiry = forms.BooleanField(label="Produk memiliki batas penggunaan", required=False)
    expires_on = forms.DateField(
        label="Baik digunakan sebelum",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    remove_image = forms.BooleanField(label="Hapus foto varian", required=False)

    class Meta:
        model = Product
        fields = ["name", "category", "description", "is_active"]
        labels = {
            "name": "Nama produk",
            "category": "Kategori",
            "description": "Deskripsi produk",
            "is_active": "Publikasikan produk",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["species"].queryset = Species.objects.filter(is_active=True)
        self.fields["species"].label_from_instance = lambda obj: obj.name
        self.fields["category"].label_from_instance = lambda obj: obj.name
        self.variant = (
            ProductVariant.objects.filter(product=self.instance)
            .order_by("-is_active", "created_at")
            .first()
            if self.instance.pk and not self.instance._state.adding
            else None
        )
        if not self.instance._state.adding:
            self.initial["species"] = ProductSpecies.objects.filter(
                product=self.instance
            ).values_list("species_id", flat=True)
        if self.variant:
            self.initial.update(
                {
                    name: getattr(self.variant, name)
                    for name in (
                        "sku",
                        "price_rp",
                        "weight_g",
                        "length_cm",
                        "width_cm",
                        "height_cm",
                        "tracks_expiry",
                    )
                }
            )
            self.initial.update(
                variant_label=self.variant.label, variant_active=self.variant.is_active
            )
            self.fields["initial_stock"].disabled = True
            self.fields["expires_on"].disabled = True
        self.fields["photo_upload"].label = "Foto produk"

    def clean(self):
        data = super().clean()
        query = ProductVariant.objects.filter(sku=data.get("sku"))
        if self.variant:
            query = query.exclude(pk=self.variant.pk)
        if data.get("sku") and query.exists():
            self.add_error("sku", "SKU sudah digunakan oleh varian lain.")
        if data.get("is_active") and data.get("category") and not data["category"].is_active:
            self.add_error("category", "Aktifkan kategori sebelum memublikasikan produk.")
        if not self.variant and data.get("initial_stock"):
            if data.get("tracks_expiry") and not data.get("expires_on"):
                self.add_error("expires_on", "Isi batas penggunaan untuk stok awal produk ini.")
            if data.get("expires_on") and data["expires_on"] <= timezone.localdate():
                self.add_error("expires_on", "Tanggal harus setelah hari ini.")
        if data.get("photo_upload") and data.get("remove_image"):
            self.add_error("remove_image", "Pilih unggah foto baru atau hapus foto, salah satu.")
        return data

    def save_catalog(self, actor):
        data = self.cleaned_data
        with upload_transaction(actor, data.get("photo_upload"), "PRODUCT_PUBLIC") as photo:
            with commerce_transaction():
                if not self.instance._state.adding:
                    Product.objects.select_for_update().get(pk=self.instance.pk)
                product = self.save()
                variant = (
                    ProductVariant.objects.select_for_update().get(pk=self.variant.pk)
                    if self.variant
                    else ProductVariant(product=product)
                )
                for name in (
                    "sku",
                    "price_rp",
                    "weight_g",
                    "length_cm",
                    "width_cm",
                    "height_cm",
                    "tracks_expiry",
                ):
                    setattr(variant, name, data[name])
                variant.label, variant.is_active = data["variant_label"], data["variant_active"]
                if photo:
                    variant.image_file, variant.image_path = photo, ""
                elif data.get("remove_image"):
                    variant.image_file, variant.image_path = None, ""
                variant.full_clean()
                variant.save()
                selected = list(data["species"])
                ProductSpecies.objects.filter(product=product).exclude(
                    species__in=selected
                ).delete()
                for species in selected:
                    ProductSpecies.objects.get_or_create(product=product, species=species)
                if not self.variant and data.get("initial_stock"):
                    batch = InventoryBatch.objects.create(
                        variant=variant,
                        batch_code="AWAL-" + uuid.uuid4().hex[:12],
                        expires_on=data.get("expires_on"),
                    )
                    receive_stock(
                        actor,
                        batch,
                        data["initial_stock"],
                        "Penerimaan stok awal melalui editor produk",
                        "product-initial:" + str(variant.pk),
                    )
                audit(actor, "catalog.saved", product)
                audit(actor, "catalog.variant_saved", variant)
                return product
