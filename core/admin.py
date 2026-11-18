"""Django management is for master data. Operational state changes use audited services."""

from django import forms
from django.apps import apps
from django.contrib.admin import AdminSite, ModelAdmin
from django.shortcuts import redirect
from accounts.permissions import active_role, OPS, READ_ALL
from core.files import store_upload


class ManagementSite(AdminSite):
    site_header = "Sinau Satwa · Pengaturan"
    site_title = "Pengaturan Sinau Satwa"
    index_title = "Data master dan referensi"
    site_url = "/dashboard/"

    def has_permission(self, request):
        return (
            request.user.is_active
            and request.user.email_verified_at
            and request.user.is_staff
            and active_role(request.user) in READ_ALL
        )

    def login(self, request, extra_context=None):
        if self.has_permission(request):
            return redirect("management:index")
        return redirect("/login/?next=/management/")


management_site = ManagementSite(name="management")
EDITABLE = {
    "StoreSettings",
    "SiteContent",
    "Species",
    "Category",
    "Product",
    "ProductSpecies",
    "ProductVariant",
    "InventoryBatch",
    "Service",
    "ServicePackage",
    "PackageSpecies",
    "PackageResource",
    "Resource",
    "StaffShift",
    "BoardingUnit",
    "DeliveryPolicy",
    "DeliveryWindow",
}
SENSITIVE = {
    "Refund",
    "OTPChallenge",
    "ExternalIdentity",
    "RateLimitBucket",
    "AccountSecurity",
    "IdempotencyRecord",
    "ClinicalInternalNote",
}


class MasterForm(forms.ModelForm):
    def clean(self):
        data = super().clean()
        for name in ("code", "name", "sku", "business_name"):
            if name in self.fields and not str(data.get(name, "")).strip():
                self.add_error(name, "Wajib diisi.")
        if self._meta.model.__name__ == "Category":
            parent = data.get("parent")
            visited = {self.instance.pk}
            while parent:
                if parent.pk in visited:
                    self.add_error("parent", "Hierarki kategori tidak boleh membentuk siklus.")
                    break
                visited.add(parent.pk)
                parent = parent.parent
        if self._meta.model.__name__ == "ServicePackage" and data.get("service"):
            if data["service"].kind != "BOARDING" and (
                not data.get("price_rp") or not data.get("duration_minutes")
            ):
                raise forms.ValidationError(
                    "Paket dokter/grooming memerlukan harga serta durasi positif."
                )
        if self._meta.model.__name__ == "ProductVariant":
            value = data.get("image_path", "") or ""
            if value and (not value.startswith("images/") or ".." in value):
                self.add_error(
                    "image_path", "Gunakan path aset lokal di images/ atau unggah gambar produk."
                )
        return data


class ProductForm(MasterForm):
    photo_upload = forms.FileField(
        label="Unggah gambar produk",
        required=False,
        help_text="JPG/PNG/WebP, maksimal 5 MB; metadata foto dihapus.",
    )

    def clean_photo_upload(self):
        upload = self.cleaned_data.get("photo_upload")
        if upload:
            from PIL import Image

            try:
                if upload.size > 5 * 1024 * 1024:
                    raise ValueError
                image = Image.open(upload)
                if (
                    image.format not in {"JPEG", "PNG", "WEBP"}
                    or image.width * image.height > 12_000_000
                ):
                    raise ValueError
                image.verify()
                upload.seek(0)
            except Exception:
                raise forms.ValidationError("Gunakan foto JPG/PNG/WebP valid maksimal 5 MB.")
        return upload


HIDDEN_FIELDS = frozenset(
    {"password", "sensitive_ciphertext", "request_payload", "code_digest", "storage_key", "payload"}
)


class ManagedModelAdmin(ModelAdmin):
    form = MasterForm
    list_per_page = 30
    actions = None

    def has_module_permission(self, request):
        return active_role(request.user) in READ_ALL

    def has_view_permission(self, request, obj=None):
        return active_role(request.user) in READ_ALL

    def has_change_permission(self, request, obj=None):
        return self.model.__name__ in EDITABLE and active_role(request.user) in OPS

    def has_add_permission(self, request):
        return self.has_change_permission(request) and not (
            self.model.__name__ in {"StoreSettings", "DeliveryPolicy"}
            and self.model.objects.exists()
        )

    def has_delete_permission(self, request, obj=None):
        return False  # Retire master records; preserve historical references.

    def get_readonly_fields(self, request, obj=None):
        if self.model.__name__ not in EDITABLE or active_role(request.user) == "OWNER":
            return [f.name for f in self.model._meta.fields if f.name not in HIDDEN_FIELDS] + [
                f.name for f in self.model._meta.many_to_many
            ]
        fields = ["created_at", "updated_at"]
        if self.model.__name__ == "InventoryBatch":
            fields += ["on_hand", "reserved"]
        if self.model.__name__ == "DeliveryPolicy" and obj:
            fields += ["version"]
        if self.model.__name__ == "ProductVariant":
            fields += ["image_file"]
        return fields

    def get_exclude(self, request, obj=None):
        return [f.name for f in self.model._meta.fields if f.name in HIDDEN_FIELDS]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if self.model.__name__ == "MedicalRecordVersion":
            return qs.filter(published_at__isnull=False)
        return qs

    def save_model(self, request, obj, form, change):
        from core.services import audit

        if obj.__class__.__name__ == "DeliveryPolicy" and change:
            obj.version += 1
        if obj.__class__.__name__ == "ProductVariant" and form.cleaned_data.get("photo_upload"):
            file = store_upload(request.user, form.cleaned_data["photo_upload"], "PRODUCT_PUBLIC")
            if file.mime_type != "image/jpeg":
                from django.core.exceptions import ValidationError

                raise ValidationError("Gambar produk harus berupa foto JPG/PNG.")
            obj.image_file = file
        super().save_model(request, obj, form, change)
        audit(request.user, "master.updated" if change else "master.created", obj)


for app_name in (
    "accounts",
    "core",
    "customers",
    "catalog",
    "inventory",
    "orders",
    "scheduling",
    "care",
    "boarding",
    "billing",
    "delivery",
    "engagement",
):
    for model in apps.get_app_config(app_name).get_models():
        if model.__name__ not in SENSITIVE:
            admin_class = (
                type("ProductAdmin", (ManagedModelAdmin,), {"form": ProductForm})
                if model.__name__ == "ProductVariant"
                else ManagedModelAdmin
            )
            management_site.register(model, admin_class)
