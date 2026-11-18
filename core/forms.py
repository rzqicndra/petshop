from django import forms
from accounts.models import User
from boarding.models import BoardingUnit


class OperationForm(forms.Form):
    action = forms.CharField(max_length=50, widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Alasan / catatan",
        max_length=2000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    recipient_name = forms.CharField(label="Nama penerima", max_length=150, required=False)
    file = forms.FileField(label="Foto / PDF pendukung", required=False)
    unit = forms.ModelChoiceField(
        label="Unit penitipan", queryset=BoardingUnit.objects.filter(is_active=True), required=False
    )
    staff = forms.ModelChoiceField(
        label="Petugas", queryset=User.objects.filter(is_active=True), required=False
    )
    valid_until = forms.DateField(
        label="Dokumen berlaku sampai",
        required=False,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    amount = forms.IntegerField(label="Nominal (Rp)", min_value=1, required=False)
    key = forms.CharField(max_length=180, required=False, widget=forms.HiddenInput)


class ReviewForm(forms.Form):
    rating = forms.TypedChoiceField(
        label="Rating",
        choices=[
            (5, "5 · Sangat baik"),
            (4, "4 · Baik"),
            (3, "3 · Cukup"),
            (2, "2 · Kurang"),
            (1, "1 · Buruk"),
        ],
        coerce=int,
    )
    comment = forms.CharField(
        label="Pengalaman Anda",
        min_length=3,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )


class MedicalForm(forms.Form):
    complaint = forms.CharField(
        label="Keluhan", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    findings = forms.CharField(
        label="Temuan pemeriksaan", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    diagnosis = forms.CharField(
        label="Diagnosis dokter", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    treatment = forms.CharField(
        label="Tindakan / terapi", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    aftercare = forms.CharField(
        label="Panduan perawatan pemilik", required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    followup_at = forms.DateTimeField(
        label="Jadwal kontrol berikutnya",
        required=False,
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    revision_reason = forms.CharField(label="Alasan revisi", required=False, max_length=2000)
    internal_note = forms.CharField(
        label="Catatan internal dokter",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Disimpan terpisah dan tidak masuk PDF pelanggan.",
    )
    file = forms.FileField(label="Foto / PDF hasil pemeriksaan", required=False)


class CareLogForm(forms.Form):
    feeding = forms.CharField(
        label="Makan dan minum", max_length=2000, widget=forms.Textarea(attrs={"rows": 2})
    )
    condition = forms.CharField(
        label="Kondisi hewan", max_length=2000, widget=forms.Textarea(attrs={"rows": 2})
    )
    activity = forms.CharField(
        label="Aktivitas / catatan",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    file = forms.FileField(label="Foto / PDF kabar hewan", required=False)
