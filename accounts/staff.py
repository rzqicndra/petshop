from django import forms
from django.contrib import messages
from django.core import signing
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from core.services import BusinessError, commerce_transaction, audit
from .models import User, OTPChallenge
from .permissions import roles_required, ROLES
from .services import issue_otp
from django.contrib.auth.models import Group
from django.db.models import Q
from django.core.paginator import Paginator


class StaffForm(forms.Form):
    email = forms.EmailField(label="Email akun")
    full_name = forms.CharField(label="Nama lengkap", max_length=150)
    roles = forms.MultipleChoiceField(
        label="Peran",
        choices=[(r, v[0]) for r, v in ROLES.items()],
        widget=forms.CheckboxSelectMultiple,
    )
    can_deliver = forms.BooleanField(label="Izin tambahan pengantaran", required=False)
    is_active = forms.BooleanField(label="Akun aktif", required=False, initial=True)


def provision_staff(actor, data):
    from .permissions import require_role

    require_role(actor, {"SUPER_ADMIN"})
    roles = set(data["roles"])
    if not roles or not roles <= set(ROLES):
        raise BusinessError("Pilih peran yang tersedia.")
    with commerce_transaction():
        user = User.objects.select_for_update().filter(email__iexact=data["email"].strip()).first()
        if (
            user
            and user.groups.filter(name="SUPER_ADMIN").exists()
            and ("SUPER_ADMIN" not in roles or not data["is_active"])
        ):
            if (
                User.objects.filter(groups__name="SUPER_ADMIN", is_active=True)
                .exclude(pk=user.pk)
                .count()
                == 0
            ):
                raise BusinessError(
                    "Super Admin aktif terakhir tidak boleh dinonaktifkan atau dihapus perannya."
                )
        if not user:
            user = User.objects.create_user(email=data["email"], full_name=data["full_name"])
        before = list(user.groups.values_list("name", flat=True))
        user.full_name, user.is_active, user.can_deliver = (
            data["full_name"],
            data["is_active"],
            data["can_deliver"],
        )
        user.is_staff = bool(roles & {"SUPER_ADMIN", "ADMIN", "OWNER"})
        user.auth_version += 1
        user.save()
        groups = [Group.objects.get_or_create(name=r)[0] for r in roles]
        user.groups.set(groups)
        if "CUSTOMER" in roles:
            from customers.models import Customer

            Customer.objects.get_or_create(
                user=user,
                defaults={
                    "name": user.full_name,
                    "contact_email": user.email,
                    "origin": "STAFF_PROVISION",
                    "linked_at": timezone.now(),
                },
            )
        audit(
            actor,
            "account.roles_updated",
            user,
            before={"roles": before},
            after={
                "roles": sorted(roles),
                "active": user.is_active,
                "can_deliver": user.can_deliver,
            },
        )
        if not user.email_verified_at and user.is_active:
            issue_otp(user, "INVITE")
        return user


@roles_required("SUPER_ADMIN")
def staff_accounts(request):
    edit = (
        User.objects.filter(pk=request.GET.get("edit")).first() if request.GET.get("edit") else None
    )
    initial = (
        {
            "email": edit.email,
            "full_name": edit.full_name,
            "roles": list(edit.groups.values_list("name", flat=True)),
            "can_deliver": edit.can_deliver,
            "is_active": edit.is_active,
        }
        if edit
        else {}
    )
    form = StaffForm(request.POST or None, initial=initial)
    if edit:
        form.fields["email"].disabled = True
    if request.method == "POST":
        try:
            if request.POST.get("action") == "resend_invite":
                user = get_object_or_404(
                    User,
                    pk=request.POST.get("user"),
                    email_verified_at__isnull=True,
                    is_active=True,
                )
                issue_otp(user, "INVITE")
                messages.success(request, "Undangan dikirim jika jeda pengiriman telah terpenuhi.")
                return redirect("staff_accounts")
            if form.is_valid():
                provision_staff(request.user, form.cleaned_data)
                messages.success(
                    request,
                    "Akun dan peran disimpan. Akun baru menerima undangan OTP email untuk mengatur password.",
                )
                return redirect("staff_accounts")
        except BusinessError as exc:
            form.add_error(None, exc)
    search = request.GET.get("q", "")[:100]
    users = (
        User.objects.prefetch_related("groups")
        .filter(Q(full_name__icontains=search) | Q(email__icontains=search))
        .order_by("full_name", "email")
    )
    page = Paginator(users, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/staff.html",
        {
            "form": form,
            "staff_users": page,
            "page": page,
            "editing": edit,
        },
    )


def invite_start(request):
    try:
        token = request.GET.get("token", "")
        data = signing.loads(token, salt="staff-invite", max_age=300)
        challenge = OTPChallenge.objects.select_related("user").get(
            pk=data["challenge"],
            user_id=data["user"],
            purpose="INVITE",
            consumed_at__isnull=True,
            invalidated_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        if challenge.user.auth_version != data["version"] or not challenge.user.is_active:
            raise BusinessError("Undangan tidak lagi berlaku.")
        request.session["otp_user"], request.session["otp_purpose"] = (
            str(challenge.user_id),
            "INVITE",
        )
        return redirect("verify_otp")
    except Exception:
        messages.error(
            request,
            "Masa berlaku undangan sudah habis atau sudah digunakan. Minta Super Admin mengirim undangan baru.",
        )
        return redirect("login")
