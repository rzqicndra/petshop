from django.contrib import messages
from django.db import transaction
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from accounts.permissions import roles_required
from core.files import store_upload
from core.services import BusinessError, audit
from .forms import PetForm, AddressForm, ProfileForm, EmergencyForm
from .models import Customer, Pet, Address, EmergencyContact


@roles_required("CUSTOMER")
def pets_view(request, pk=None):
    customer = Customer.objects.get(user=request.user)
    pet = get_object_or_404(Pet, pk=pk, customer=customer, is_active=True) if pk else None
    form = PetForm(request.POST or None, request.FILES or None, instance=pet)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                if pet and not Pet.objects.select_for_update().get(pk=pet.pk).is_active:
                    raise BusinessError("Profil hewan sudah dihapus. Muat ulang daftar hewan Anda.")
                item = form.save(commit=False)
                item.customer = customer
                if form.cleaned_data["photo"]:
                    item.photo_file = store_upload(
                        request.user, form.cleaned_data["photo"], "PET_PHOTO"
                    )
                item.save()
                audit(request.user, "pet.saved", item)
            messages.success(request, "Profil hewan disimpan.")
            return redirect("pets")
        except BusinessError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "customers/pets.html",
        {
            "pets": Pet.objects.filter(customer=customer, is_active=True).select_related(
                "species", "photo_file"
            ),
            "form": form,
            "editing": pet,
        },
    )


@roles_required("CUSTOMER")
def addresses_view(request, pk=None):
    customer = Customer.objects.get(user=request.user)
    address = get_object_or_404(Address, pk=pk, customer=customer, is_active=True) if pk else None
    form = AddressForm(request.POST or None, instance=address)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            Customer.objects.select_for_update().get(pk=customer.pk)
            if address and not Address.objects.filter(pk=address.pk, is_active=True).exists():
                messages.error(request, "Alamat sudah dihapus. Silakan pilih alamat aktif.")
                return redirect("addresses")
            item = form.save(commit=False)
            item.customer = customer
            if (
                item.is_default
                or not Address.objects.filter(customer=customer, is_active=True, is_default=True)
                .exclude(pk=item.pk)
                .exists()
            ):
                item.is_default = True
                Address.objects.filter(customer=customer, is_default=True).exclude(
                    pk=item.pk
                ).update(is_default=False)
            item.save()
            audit(request.user, "address.saved", item)
        messages.success(request, "Alamat dan titik tujuan disimpan.")
        return redirect("addresses")
    return render(
        request,
        "customers/addresses.html",
        {
            "addresses": Address.objects.filter(customer=customer, is_active=True).order_by(
                "-is_default", "-created_at"
            ),
            "form": form,
            "editing": address,
        },
    )


@roles_required("CUSTOMER")
def profile_view(request):
    customer = Customer.objects.get(user=request.user)
    form = ProfileForm(
        request.POST or None if request.POST.get("action") != "emergency" else None,
        instance=customer,
    )
    emergency_form = EmergencyForm(
        request.POST if request.POST.get("action") == "emergency" else None
    )
    if request.method == "POST":
        if request.POST.get("action") == "emergency" and emergency_form.is_valid():
            contact = emergency_form.save(commit=False)
            contact.customer = customer
            contact.save()
            messages.success(request, "Kontak darurat ditambahkan.")
            return redirect("profile")
        if request.POST.get("action") != "emergency" and form.is_valid():
            form.save()
            request.user.full_name = form.cleaned_data["name"]
            request.user.save(update_fields=["full_name", "updated_at"])
            messages.success(request, "Profil disimpan.")
            return redirect("profile")
    return render(
        request,
        "customers/profile.html",
        {
            "form": form,
            "emergency_form": emergency_form,
            "contacts": EmergencyContact.objects.filter(customer=customer, is_active=True),
        },
    )


@require_POST
@roles_required("CUSTOMER")
def pet_delete(request, pk):
    with transaction.atomic():
        pet = get_object_or_404(
            Pet.objects.select_for_update(), pk=pk, customer__user=request.user, is_active=True
        )
        from scheduling.models import Booking

        if Booking.objects.filter(
            pet=pet,
            status__in={
                "SUBMITTED",
                "AWAITING_PAYMENT",
                "CONFIRMED",
                "IN_SERVICE",
                "READY_PICKUP",
                "NEEDS_ATTENTION",
            },
        ).exists():
            messages.error(
                request,
                "Hewan masih memiliki layanan aktif. Selesaikan atau batalkan layanan terlebih dahulu.",
            )
        else:
            pet.is_active = False
            pet.save(update_fields=["is_active", "updated_at"])
            audit(request.user, "pet.archived", pet)
            messages.success(
                request, "Hewan dihapus dari daftar. Riwayat perawatannya tetap tersimpan."
            )
    return redirect("pets")


@require_POST
@roles_required("CUSTOMER")
def address_delete(request, pk):
    with transaction.atomic():
        customer = Customer.objects.select_for_update().get(user=request.user)
        item = get_object_or_404(
            Address.objects.select_for_update(), pk=pk, customer=customer, is_active=True
        )
        was_default = item.is_default
        item.is_active, item.is_default = False, False
        item.save(update_fields=["is_active", "is_default", "updated_at"])
        if was_default:
            replacement = (
                Address.objects.filter(customer=customer, is_active=True)
                .order_by("-created_at")
                .first()
            )
            if replacement:
                replacement.is_default = True
                replacement.save(update_fields=["is_default", "updated_at"])
        audit(request.user, "address.archived", item)
    messages.success(request, "Alamat dihapus. Alamat pada pesanan sebelumnya tetap tersimpan.")
    return redirect("addresses")


@require_POST
@roles_required("CUSTOMER")
def emergency_delete(request, pk):
    with transaction.atomic():
        contact = get_object_or_404(
            EmergencyContact.objects.select_for_update(),
            pk=pk,
            customer__user=request.user,
            is_active=True,
        )
        contact.is_active = False
        contact.save(update_fields=["is_active", "updated_at"])
        audit(request.user, "emergency_contact.archived", contact)
    messages.success(
        request, "Kontak darurat dihapus. Kontak pada penitipan sebelumnya tetap tersimpan."
    )
    return redirect("profile")
