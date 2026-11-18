from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

ROLES = {
    "SUPER_ADMIN": ("Super Admin", "super-admin"),
    "OWNER": ("Owner Usaha", "owner"),
    "ADMIN": ("Admin Operasional", "admin"),
    "DOCTOR": ("Dokter Hewan", "dokter"),
    "GROOMER": ("Groomer", "grooming"),
    "CARETAKER": ("Petugas Penitipan", "penitipan"),
    "CUSTOMER": ("Pelanggan", "pelanggan"),
}
OPS = {"SUPER_ADMIN", "ADMIN"}
READ_ALL = OPS | {"OWNER"}


def user_roles(user):
    return set(user.groups.values_list("name", flat=True)) if user.is_authenticated else set()


def active_role(user):
    assigned = user_roles(user)
    workspace = getattr(user, "workspace_role", None)
    if workspace in assigned:
        return workspace
    return next((role for role in ROLES if role in assigned), None)


def require_role(user, allowed):
    if (
        not user.is_authenticated
        or not user.is_active
        or not user.email_verified_at
        or active_role(user) not in allowed
    ):
        raise PermissionDenied("Akses untuk peran ini tidak tersedia.")


def workspace_url(role):
    return "/dashboard/" if role == "CUSTOMER" else f"/staf/{ROLES[role][1]}/"


def verified_login(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.email_verified_at:
            request.session["otp_user"] = str(request.user.pk)
            request.session["otp_purpose"] = "REGISTER"
            return redirect("verify_otp")
        return view(request, *args, **kwargs)

    return wrapped


def roles_required(*roles):
    def decorator(view):
        @verified_login
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            require_role(request.user, set(roles))
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
