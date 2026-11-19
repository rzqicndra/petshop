from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import User


class AccountProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name"]
        labels = {"full_name": "Nama lengkap"}
        widgets = {"full_name": forms.TextInput(attrs={"autocomplete": "name"})}

    def clean_full_name(self):
        value = self.cleaned_data["full_name"].strip()
        if not value:
            raise forms.ValidationError("Isi nama lengkap Anda.")
        return value


class LoginForm(forms.Form):
    email = forms.EmailField(
        label="Email", max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "username"})
    )
    password = forms.CharField(
        label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )


class RegisterForm(forms.Form):
    full_name = forms.CharField(label="Nama lengkap", max_length=150)
    email = forms.EmailField(label="Email", max_length=254)
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput,
        help_text="Minimal 12 karakter. Gunakan kata sandi yang unik.",
    )
    password_confirm = forms.CharField(label="Ulangi password", widget=forms.PasswordInput)
    consent = forms.BooleanField(
        label="Saya menyetujui penggunaan data untuk layanan dan komunikasi transaksi."
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        data = super().clean()
        if data.get("password") != data.get("password_confirm"):
            self.add_error("password_confirm", "Password belum sama.")
        if data.get("password"):
            validate_password(
                data["password"],
                User(email=data.get("email", ""), full_name=data.get("full_name", "")),
            )
        return data


class EmailForm(forms.Form):
    email = forms.EmailField(label="Email")


class OTPForm(forms.Form):
    code = forms.RegexField(
        r"^\d{6}$",
        label="Kode OTP",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}),
    )


class ResetForm(forms.Form):
    password = forms.CharField(label="Password baru", widget=forms.PasswordInput)
    password_confirm = forms.CharField(label="Ulangi password baru", widget=forms.PasswordInput)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        data = super().clean()
        if data.get("password") != data.get("password_confirm"):
            self.add_error("password_confirm", "Password belum sama.")
        if data.get("password"):
            validate_password(data["password"], self.user)
        return data
