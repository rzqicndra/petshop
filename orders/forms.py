from django import forms
from customers.models import Address


class CheckoutForm(forms.Form):
    fulfillment = forms.ChoiceField(
        label="Terima pesanan", choices=[("PICKUP", "Ambil di toko"), ("DELIVERY", "Pengiriman")]
    )
    address = forms.ModelChoiceField(
        label="Alamat pengiriman", queryset=Address.objects.none(), required=False
    )
    key = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["address"].queryset = Address.objects.filter(customer=customer, is_active=True)

    def clean(self):
        data = super().clean()
        if data.get("fulfillment") == "DELIVERY" and not data.get("address"):
            self.add_error(
                "address", "Alamat lengkap, kontak penerima, dan titik tujuan wajib dipilih."
            )
        return data
