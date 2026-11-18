"""Workspace-native master data screens; operational records remain service-managed."""

from django import forms
from django.apps import apps
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from accounts.permissions import roles_required, active_role, OPS, READ_ALL
from .admin import management_site
from .models import StoreSettings
from .admin import ProductForm
from .files import upload_transaction
from .services import BusinessError
from catalog.editor import CatalogProductForm

MASTERS = {
    "konten": (
        "core.SiteContent",
        "Konten website",
        "Teks, foto, dan tautan halaman publik",
        "file",
    ),
    "toko": (
        "core.StoreSettings",
        "Profil toko",
        "Alamat, kontak CS, dan jam operasional",
        "store",
    ),
    "jenis-hewan": ("catalog.Species", "Jenis hewan", "Jenis hewan yang dilayani", "paw"),
    "kategori": ("catalog.Category", "Kategori produk", "Kelompok kebutuhan dan perawatan", "grid"),
    "produk": ("catalog.Product", "Produk", "Produk, varian, foto, harga, dan stok awal", "box"),
    "varian": (
        "catalog.ProductVariant",
        "Varian & harga",
        "Harga, foto, ukuran, dan berat paket",
        "tag",
    ),
    "produk-hewan": (
        "catalog.ProductSpecies",
        "Kesesuaian produk",
        "Hubungkan produk dengan jenis hewan",
        "paw",
    ),
    "layanan": ("scheduling.Service", "Layanan", "Dokter hewan, grooming, dan penitipan", "heart"),
    "paket": (
        "scheduling.ServicePackage",
        "Paket layanan",
        "Harga, durasi, dan jeda layanan",
        "calendar",
    ),
    "paket-hewan": (
        "scheduling.PackageSpecies",
        "Kesesuaian layanan",
        "Jenis hewan untuk setiap paket",
        "paw",
    ),
    "fasilitas": (
        "scheduling.Resource",
        "Tim & fasilitas",
        "Petugas, ruang, dan fasilitas toko",
        "users",
    ),
    "alokasi": (
        "scheduling.PackageResource",
        "Alokasi fasilitas",
        "Kebutuhan fasilitas per layanan",
        "grid",
    ),
    "shift": (
        "scheduling.StaffShift",
        "Jadwal kerja",
        "Ketersediaan tim untuk booking",
        "calendar",
    ),
    "unit": (
        "boarding.BoardingUnit",
        "Unit penitipan",
        "Tipe unit, tarif, dan waktu persiapan",
        "home",
    ),
    "pengiriman": (
        "delivery.DeliveryPolicy",
        "Aturan pengiriman",
        "Jangkauan dan tarif Kurir Toko",
        "truck",
    ),
    "slot": ("delivery.DeliveryWindow", "Slot pengantaran", "Jadwal dan kuota pengiriman", "clock"),
    "batch": (
        "inventory.InventoryBatch",
        "Batch persediaan",
        "Identitas batch dan batas penggunaan",
        "box",
    ),
}
LABELS = {
    "code": "Kode",
    "name": "Nama",
    "is_active": "Aktif",
    "business_name": "Nama usaha",
    "address": "Alamat toko",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "cs_whatsapp": "WhatsApp CS",
    "timezone": "Zona waktu",
    "public_contact_ready": "Data toko sudah diperiksa dan siap ditampilkan",
    "price_rp": "Harga (Rp)",
    "duration_minutes": "Durasi (menit)",
    "buffer_minutes": "Jeda antar layanan (menit)",
    "kind": "Jenis",
    "service": "Layanan",
    "product": "Produk",
    "category": "Kategori",
    "parent": "Kategori induk",
    "species": "Jenis hewan",
    "label": "Nama varian",
    "weight_g": "Berat (gram)",
    "length_cm": "Panjang (cm)",
    "width_cm": "Lebar (cm)",
    "height_cm": "Tinggi (cm)",
    "image_path": "Gambar bawaan",
    "staff_user": "Akun petugas",
    "resource": "Tim / fasilitas",
    "package": "Paket layanan",
    "pool": "Kelompok alokasi",
    "quantity": "Jumlah",
    "starts_at": "Mulai",
    "ends_at": "Selesai",
    "is_available": "Tersedia",
    "nightly_rate_rp": "Tarif per malam (Rp)",
    "cleaning_minutes": "Waktu persiapan (menit)",
    "internal_enabled": "Aktifkan Kurir Toko",
    "max_route_m": "Batas jarak rute (meter)",
    "base_fee_rp": "Biaya dasar (Rp)",
    "per_km_fee_rp": "Biaya per km (Rp)",
    "max_weight_g": "Batas berat (gram)",
    "travel_mode": "Moda transportasi",
    "max_orders": "Kuota pesanan",
    "packaging_weight_g": "Berat kemasan (gram)",
    "max_length_cm": "Batas panjang (cm)",
    "max_width_cm": "Batas lebar (cm)",
    "max_height_cm": "Batas tinggi (cm)",
    "variant": "Varian",
    "batch_code": "Kode batch",
    "expires_on": "Baik digunakan sebelum",
    "received_at": "Tanggal diterima",
    "photo_upload": "Unggah gambar",
    "description": "Deskripsi",
    "tagline": "Tagline",
    "footer_text": "Teks footer",
    "cs_label": "Teks tombol WhatsApp",
    "key": "Bagian halaman",
    "overline": "Label pembuka",
    "heading": "Judul",
    "body": "Isi konten",
    "image_alt": "Deskripsi gambar",
    "fallback_image": "Gambar bawaan",
    "button_label": "Teks tombol",
    "link_route": "Tujuan tombol",
}


class ImageMasterForm(ProductForm):
    remove_image = forms.BooleanField(label="Hapus gambar saat ini", required=False)


class StoreForm(ImageMasterForm):
    opening_hours = forms.JSONField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = StoreSettings
        fields = [
            "business_name",
            "tagline",
            "footer_text",
            "cs_label",
            "cs_whatsapp",
            "address",
            "latitude",
            "longitude",
            "timezone",
            "public_contact_ready",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.label = LABELS.get(name, field.label)
        self.fields["cs_whatsapp"].help_text = (
            "Contoh: 6281234567890, tanpa spasi atau tanda tambah."
        )
        self.fields["timezone"].initial = "Asia/Jakarta"
        for day, label in enumerate(
            ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
        ):
            hours = (self.instance.opening_hours or {}).get(str(day), [])
            self.fields[f"open_{day}"] = forms.TimeField(
                label=label + " · buka",
                required=False,
                widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
                initial=hours[0] if hours else None,
            )
            self.fields[f"close_{day}"] = forms.TimeField(
                label=label + " · tutup",
                required=False,
                widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
                initial=hours[1] if hours else None,
            )

    def clean(self):
        data = super().clean()
        hours = {}
        for day in range(7):
            opening, closing = data.get(f"open_{day}"), data.get(f"close_{day}")
            if bool(opening) != bool(closing) or (opening and closing and opening >= closing):
                self.add_error(
                    f"close_{day}",
                    "Isi jam buka dan tutup yang berurutan, atau kosongkan keduanya untuk hari libur.",
                )
            elif opening:
                hours[str(day)] = [opening.strftime("%H:%M"), closing.strftime("%H:%M")]
        self.instance.opening_hours = hours
        data["opening_hours"] = hours
        return data


@roles_required(*READ_ALL)
def master_center(request, section=None, pk=None):
    entries = [
        {"key": key, "title": value[1], "description": value[2], "icon": value[3]}
        for key, value in MASTERS.items()
    ]
    if section is None:
        return render(request, "management/index.html", {"entries": entries})
    if section not in MASTERS:
        from django.http import Http404

        raise Http404
    model_label, title, description, icon = MASTERS[section]
    model = apps.get_model(model_label)
    admin = management_site._registry[model]
    queryset = model.objects.all().order_by("-updated_at")
    search_fields = [
        f.name for f in model._meta.fields if f.get_internal_type() in {"CharField", "TextField"}
    ]
    if request.GET.get("q") and search_fields:
        query = Q()
        for field in search_fields:
            query |= Q(**{field + "__icontains": request.GET["q"][:100]})
        if section == "varian":
            query |= Q(product__name__icontains=request.GET["q"][:100])
        queryset = queryset.filter(query)
    obj = get_object_or_404(model, pk=pk) if pk else None
    if section in {"toko", "pengiriman"}:
        obj = model.objects.filter(pk=1).first() or model(pk=1)
    if section == "produk":
        form_class = CatalogProductForm
    elif section == "toko":
        form_class = StoreForm
    else:
        from .admin import MasterForm, ProductForm, HIDDEN_FIELDS

        excluded = set(HIDDEN_FIELDS) | {
            "created_at",
            "updated_at",
            "on_hand",
            "reserved",
            "version",
            "image_file",
            "logo_file",
            "image_path",
        }
        form_class = forms.modelform_factory(
            model,
            form=(
                ImageMasterForm
                if section in {"konten", "layanan", "jenis-hewan", "kategori", "varian"}
                else MasterForm
            ),
            exclude=list(excluded),
        )
    form = form_class(request.POST or None, request.FILES or None, instance=obj)
    for name, field in form.fields.items():
        field.label = LABELS.get(name, field.label) if section != "produk" else field.label
        if isinstance(field, (forms.ModelChoiceField, forms.ModelMultipleChoiceField)):
            field.label_from_instance = lambda item: getattr(item, "name", "") or str(item)
        if isinstance(field, forms.DateTimeField):
            field.widget = forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}
            )
        elif isinstance(field, forms.DateField):
            field.widget = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})
        elif isinstance(field, forms.CharField) and isinstance(field.widget, forms.Textarea):
            field.widget.attrs["rows"] = 3
    readonly = active_role(request.user) not in OPS
    if readonly:
        for field in form.fields.values():
            field.disabled = True
    if request.method == "POST":
        if readonly:
            raise PermissionDenied
        if form.is_valid():
            try:
                if section == "produk":
                    form.save_catalog(request.user)
                else:
                    image_section = section in {
                        "toko",
                        "konten",
                        "layanan",
                        "jenis-hewan",
                        "kategori",
                        "varian",
                    }
                    upload = form.cleaned_data.get("photo_upload") if image_section else None
                    with upload_transaction(
                        request.user,
                        upload,
                        "SITE_PUBLIC" if section != "varian" else "PRODUCT_PUBLIC",
                    ) as photo:
                        item = form.save(commit=False)
                        if image_section:
                            image_field = "logo_file" if section == "toko" else "image_file"
                            if photo:
                                setattr(item, image_field, photo)
                                if section == "varian":
                                    item.image_path = ""
                            elif form.cleaned_data.get("remove_image"):
                                setattr(item, image_field, None)
                                if section == "varian":
                                    item.image_path = ""
                        # Upload already validated and saved inside the rollback-aware context.
                        form.cleaned_data.pop("photo_upload", None)
                        admin.save_model(request, item, form, bool(obj and not obj._state.adding))
                        form.save_m2m()
                messages.success(request, title + " berhasil disimpan.")
                return redirect("master_section", section=section)
            except (ValidationError, IntegrityError, BusinessError):
                form.add_error(
                    None,
                    "Data belum dapat disimpan. Periksa kode yang sama, hubungan data, dan isian wajib.",
                )
    page = Paginator(queryset, 12).get_page(request.GET.get("page"))
    if section == "produk":
        from catalog.models import ProductVariant

        for product in page:
            product.catalog_ready = (
                product.is_active
                and product.category.is_active
                and ProductVariant.objects.filter(product=product, is_active=True).exists()
            )
    image = None
    if obj:
        if section == "toko":
            image = obj.logo_file
        elif section == "produk" and form.variant:
            image = form.variant.image_file
        else:
            image = getattr(obj, "image_file", None)
    return render(
        request,
        "management/section.html",
        {
            "entries": entries,
            "section": section,
            "title": title,
            "description": description,
            "form": form,
            "editing": obj,
            "readonly": readonly,
            "singleton": section in {"toko", "pengiriman"},
            "page": page,
            "current_image": image,
            "primary_variant": getattr(form, "variant", None),
        },
    )
