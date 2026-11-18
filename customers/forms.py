import re
from django import forms
from django.utils import timezone
from catalog.models import Species
from .models import Pet, Address, Customer, EmergencyContact


def phone(value):
    normalized = re.sub(r"[\s()+-]", "", value)
    if normalized.startswith("0"):
        normalized = "62" + normalized[1:]
    if not re.fullmatch(r"[1-9]\d{8,14}", normalized):
        raise forms.ValidationError(
            "Gunakan nomor telepon yang valid, misalnya 0812… atau +62812…."
        )
    return normalized


class PetForm(forms.ModelForm):
    photo = forms.FileField(label="Foto hewan", required=False, help_text="JPG/PNG, maksimal 5 MB.")

    class Meta:
        model = Pet
        fields = [
            "name",
            "species",
            "breed",
            "sex",
            "birth_date",
            "estimated_birth_date",
            "weight_kg",
            "allergies",
            "handling_notes",
        ]
        labels = {
            "name": "Nama hewan",
            "species": "Jenis hewan",
            "breed": "Ras",
            "sex": "Jenis kelamin",
            "birth_date": "Tanggal lahir",
            "estimated_birth_date": "Tanggal lahir perkiraan",
            "weight_kg": "Berat (kg)",
            "allergies": "Alergi",
            "handling_notes": "Catatan penanganan",
        }
        widgets = {
            "birth_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "allergies": forms.Textarea(attrs={"rows": 3}),
            "handling_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = True
        self.fields["species"].queryset = Species.objects.filter(is_active=True)
        self.fields["species"].label_from_instance = lambda obj: obj.name

    def clean_photo(self):
        upload = self.cleaned_data.get("photo")
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
                raise forms.ValidationError(
                    "Gunakan foto JPG, PNG, atau WebP valid, maksimal 5 MB."
                )
        return upload

    def clean_birth_date(self):
        value = self.cleaned_data.get("birth_date")
        if value and value > timezone.localdate():
            raise forms.ValidationError("Tanggal lahir tidak boleh di masa depan.")
        return value


class AddressForm(forms.ModelForm):
    pin_confirmed = forms.BooleanField(
        label="Saya sudah memastikan titik ini adalah tujuan pengiriman."
    )

    class Meta:
        model = Address
        fields = [
            "label",
            "recipient_name",
            "recipient_phone",
            "address_line",
            "province",
            "city",
            "district",
            "village",
            "postal_code",
            "latitude",
            "longitude",
            "delivery_note",
            "is_default",
        ]
        labels = {
            "label": "Label alamat",
            "recipient_name": "Nama penerima",
            "recipient_phone": "Nomor WhatsApp / telepon penerima",
            "address_line": "Jalan, nomor rumah, blok, dan unit",
            "province": "Provinsi",
            "city": "Kota / kabupaten",
            "district": "Kecamatan",
            "village": "Kelurahan",
            "postal_code": "Kode pos",
            "latitude": "Latitude titik tujuan",
            "longitude": "Longitude titik tujuan",
            "delivery_note": "Patokan / catatan kurir",
            "is_default": "Jadikan alamat utama",
        }
        widgets = {
            "address_line": forms.Textarea(attrs={"rows": 3}),
            "delivery_note": forms.Textarea(attrs={"rows": 2}),
            "latitude": forms.NumberInput(attrs={"step": "0.000001", "min": -90, "max": 90}),
            "longitude": forms.NumberInput(attrs={"step": "0.000001", "min": -180, "max": 180}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance._state.adding and not self.is_bound:
            self.initial.update(latitude=None, longitude=None)
        for field in (
            "label",
            "recipient_name",
            "recipient_phone",
            "address_line",
            "province",
            "city",
            "district",
            "postal_code",
        ):
            self.fields[field].required = True

    def clean_recipient_phone(self):
        return phone(self.cleaned_data["recipient_phone"])


class ProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = True

    class Meta:
        model = Customer
        fields = ["name", "phone"]
        labels = {"name": "Nama lengkap", "phone": "Nomor WhatsApp / telepon"}

    def clean_phone(self):
        return phone(self.cleaned_data["phone"]) if self.cleaned_data.get("phone") else ""


class EmergencyForm(forms.ModelForm):
    class Meta:
        model = EmergencyContact
        fields = ["name", "relationship", "phone", "contact_consent"]
        labels = {
            "name": "Nama kontak darurat",
            "relationship": "Hubungan",
            "phone": "Nomor telepon",
            "contact_consent": "Kontak bersedia dihubungi untuk kondisi darurat hewan.",
        }

    def clean_phone(self):
        return phone(self.cleaned_data["phone"])
