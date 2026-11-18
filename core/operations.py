"""Reception, cashier and resource blocking share the same domain services as online flows."""

import uuid
from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.forms import formset_factory
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from psycopg.types.range import Range
from accounts.permissions import roles_required
from customers.forms import PetForm, phone
from customers.models import Customer, Pet
from catalog.models import ProductVariant
from orders.services import draft_order, checkout
from scheduling.forms import BookingForm
from scheduling.services import create_booking, expire_capacity_holds
from scheduling.models import Resource, ResourceReservation
from core.models import IdempotencyRecord
from .services import BusinessError, commerce_transaction, audit


class WalkinCustomerForm(forms.Form):
    name = forms.CharField(label="Nama pelanggan", max_length=150)
    phone = forms.CharField(label="Nomor WhatsApp / telepon", max_length=32)
    contact_email = forms.EmailField(label="Email kontak (opsional)", required=False)

    def clean_phone(self):
        return phone(self.cleaned_data["phone"])


@roles_required("SUPER_ADMIN", "ADMIN", "OWNER")
def walkin_view(request):
    customer_id = request.POST.get("customer") or request.GET.get("customer")
    customer = get_object_or_404(Customer, pk=customer_id, is_active=True) if customer_id else None
    customer_form = WalkinCustomerForm(
        request.POST if request.POST.get("action") == "customer" else None
    )
    pet_form = PetForm(
        request.POST if request.POST.get("action") == "pet" else None, request.FILES or None
    )
    booking_form = (
        BookingForm(
            request.POST if request.POST.get("action") == "booking" else None,
            request.FILES or None,
            customer=customer,
            initial={"key": str(uuid.uuid4())},
        )
        if customer
        else None
    )
    if request.method == "POST":
        from accounts.permissions import require_role, OPS

        require_role(request.user, OPS)
        action = request.POST.get("action")
        try:
            if action == "customer" and customer_form.is_valid():
                customer = Customer.objects.create(**customer_form.cleaned_data, origin="WALK_IN")
                audit(request.user, "customer.walkin_created", customer)
                return redirect(f"/operasional/pelanggan/?customer={customer.pk}")
            if action == "pet" and customer and pet_form.is_valid():
                pet = pet_form.save(commit=False)
                pet.customer = customer
                if pet_form.cleaned_data.get("photo"):
                    from .files import store_upload

                    pet.photo_file = store_upload(
                        request.user, pet_form.cleaned_data["photo"], "PET_PHOTO"
                    )
                pet.save()
                audit(request.user, "pet.walkin_created", pet)
                return redirect(f"/operasional/pelanggan/?customer={customer.pk}")
            if action == "booking" and booking_form and booking_form.is_valid():
                data = booking_form.cleaned_data
                contact = data["emergency_contact"]
                emergency = (
                    {
                        "name": contact.name,
                        "phone": contact.phone,
                        "consent": contact.contact_consent,
                    }
                    if contact
                    else None
                )
                booking = create_booking(
                    request.user,
                    data["pet"],
                    data["package"],
                    data["starts_at"],
                    data["checkout_at"],
                    data["key"],
                    customer,
                    data["notes"],
                    emergency,
                )
                if data.get("document") and booking.kind_snapshot == "BOARDING":
                    from .files import store_upload
                    from boarding.models import BoardingStay, BoardingIntakeFile

                    file = store_upload(request.user, data["document"], "BOARDING_INTAKE")
                    BoardingIntakeFile.objects.create(
                        stay=BoardingStay.objects.get(booking=booking),
                        file=file,
                        document_type="HEALTH",
                    )
                messages.success(
                    request,
                    "Booking datang langsung dibuat menggunakan kapasitas yang sama dengan online.",
                )
                return redirect("booking_detail", pk=booking.pk)
        except BusinessError as exc:
            messages.error(request, exc.messages[0])
    customers = Customer.objects.filter(is_active=True).order_by("name")
    if request.GET.get("q"):
        customers = customers.filter(name__icontains=request.GET["q"][:100])
    return render(
        request,
        "core/walkin.html",
        {
            "selected_customer": customer,
            "customers": customers[:100],
            "customer_form": customer_form,
            "pet_form": pet_form,
            "booking_form": booking_form,
            "pets": Pet.objects.filter(customer=customer, is_active=True) if customer else [],
        },
    )


class CashierForm(forms.Form):
    customer = forms.ModelChoiceField(
        label="Pelanggan", queryset=Customer.objects.filter(is_active=True)
    )
    key = forms.CharField(widget=forms.HiddenInput)


class CashierItem(forms.Form):
    variant = forms.ModelChoiceField(
        label="Produk / SKU",
        queryset=ProductVariant.objects.filter(is_active=True, product__is_active=True),
        required=False,
    )
    quantity = forms.IntegerField(label="Jumlah", min_value=1, max_value=99, required=False)

    def clean(self):
        data = super().clean()
        if bool(data.get("variant")) != bool(data.get("quantity")):
            raise forms.ValidationError("Pilih produk dan jumlah pada baris yang digunakan.")
        return data


@roles_required("SUPER_ADMIN", "ADMIN")
def cashier_view(request):
    form = CashierForm(request.POST or None, initial={"key": str(uuid.uuid4())})
    ItemFormSet = formset_factory(
        CashierItem, extra=4, max_num=30, validate_max=True, absolute_max=30
    )
    items = ItemFormSet(request.POST or None)
    if request.method == "POST" and form.is_valid() and items.is_valid():
        try:
            cart = {}
            for row in items.cleaned_data:
                if row.get("variant"):
                    key = str(row["variant"].pk)
                    cart[key] = cart.get(key, 0) + row["quantity"]
            if not cart or any(q > 99 for q in cart.values()):
                raise BusinessError("Isi minimal satu produk, maksimal 99 per SKU.")
            with commerce_transaction():
                idem = IdempotencyRecord.objects.filter(
                    scope="cashier", key=form.cleaned_data["key"]
                ).first()
                from .services import idempotent

                idem, fresh = idempotent(
                    "cashier",
                    form.cleaned_data["key"],
                    request.user,
                    {"customer": form.cleaned_data["customer"].pk, "cart": cart},
                )
                if not fresh and idem.result_reference:
                    return redirect("order_detail", pk=idem.result_reference["id"])
                order = draft_order(
                    request.user, cart, "PICKUP", customer=form.cleaned_data["customer"]
                )
                order = checkout(request.user, order, "checkout:" + form.cleaned_data["key"])
                idem.status, idem.result_reference = "DONE", {"id": str(order.pk)}
                idem.save()
            messages.success(
                request,
                "Penjualan dibuat. Catat penerimaan tunai atau bayar melalui tagihan, lalu lakukan serah terima.",
            )
            return redirect("order_detail", pk=order.pk)
        except BusinessError as exc:
            form.add_error(None, exc)
    return render(request, "core/cashier.html", {"form": form, "items": items})


class CapacityForm(forms.Form):
    resource = forms.ModelChoiceField(
        label="Staf / fasilitas / unit", queryset=Resource.objects.filter(is_active=True)
    )
    starts_at = forms.DateTimeField(
        label="Mulai blok",
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    ends_at = forms.DateTimeField(
        label="Selesai blok",
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    reason = forms.CharField(
        label="Alasan penutupan / libur",
        min_length=3,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


@roles_required("SUPER_ADMIN", "ADMIN", "OWNER")
def capacity_view(request):
    form = CapacityForm(request.POST or None)
    if request.method == "POST":
        from accounts.permissions import require_role, OPS

        require_role(request.user, OPS)
        try:
            with commerce_transaction():
                expire_capacity_holds()
                if request.POST.get("action") == "release":
                    reservation = get_object_or_404(
                        ResourceReservation.objects.select_for_update(),
                        pk=request.POST.get("reservation"),
                        status="BLOCKED",
                        kind="BLOCK",
                    )
                    reservation.status = "RELEASED"
                    reservation.save()
                    audit(
                        request.user,
                        "capacity.block_released",
                        reservation,
                        reason="Dibuka kembali oleh operasional",
                    )
                    return redirect("capacity")
                if form.is_valid():
                    data = form.cleaned_data
                    if data["ends_at"] <= data["starts_at"]:
                        raise BusinessError("Waktu selesai harus setelah mulai.")
                    Resource.objects.select_for_update().get(pk=data["resource"].pk)
                    rr = ResourceReservation.objects.create(
                        resource=data["resource"],
                        period=Range(data["starts_at"], data["ends_at"], "[)"),
                        kind="BLOCK",
                        status="BLOCKED",
                        reason=data["reason"],
                    )
                    audit(request.user, "capacity.blocked", rr, reason=data["reason"])
                    return redirect("capacity")
        except IntegrityError:
            form.add_error(
                None,
                "Periode bentrok dengan reservasi aktif. Tinjau Booking yang sudah ada sebelum menutup jadwal.",
            )
        except BusinessError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "core/capacity.html",
        {
            "form": form,
            "reservations": ResourceReservation.objects.select_related("resource", "booking")
            .filter(status__in={"HELD", "CONFIRMED", "IN_USE", "BLOCKED"})
            .order_by("period")[:200],
        },
    )
