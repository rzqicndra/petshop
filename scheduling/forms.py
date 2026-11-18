from django import forms
from customers.models import Pet, EmergencyContact
from .models import ServicePackage


class BookingForm(forms.Form):
    pet = forms.ModelChoiceField(label="Hewan", queryset=Pet.objects.none())
    package = forms.ModelChoiceField(label="Paket layanan", queryset=ServicePackage.objects.none())
    starts_at = forms.DateTimeField(
        label="Jadwal mulai / check-in",
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    checkout_at = forms.DateTimeField(
        label="Jadwal jemput penitipan",
        required=False,
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
        help_text="Diisi untuk penitipan.",
    )
    emergency_contact = forms.ModelChoiceField(
        label="Kontak darurat penitipan", queryset=EmergencyContact.objects.none(), required=False
    )
    notes = forms.CharField(
        label="Catatan kebutuhan hewan",
        max_length=2000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    document = forms.FileField(
        label="Dokumen kesehatan penitipan",
        required=False,
        help_text="Foto/PDF, maksimal 5 MB. Admin memeriksa dokumen sebelum menyetujui.",
    )
    key = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pet"].queryset = Pet.objects.filter(customer=customer, is_active=True)
        self.fields["package"].queryset = ServicePackage.objects.filter(
            is_active=True, service__is_active=True
        ).select_related("service")
        self.fields["emergency_contact"].queryset = EmergencyContact.objects.filter(
            customer=customer, contact_consent=True, is_active=True
        )


class ExtensionForm(forms.Form):
    requested_checkout_at = forms.DateTimeField(
        label="Waktu jemput baru",
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )


class RescheduleForm(forms.Form):
    starts_at = forms.DateTimeField(
        label="Jadwal baru",
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    version = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
