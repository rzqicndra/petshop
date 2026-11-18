from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from .permissions import user_roles, active_role
from .models import AccountSecurity


class AccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            if request.session.get("auth_version") != request.user.auth_version:
                logout(request)
                return redirect("login")
            assigned = user_roles(request.user)
            role = request.session.get("workspace")
            if role not in assigned:
                role = active_role(request.user)
                request.session["workspace"] = role
            request.user.workspace_role = role
            exempt = (
                "/keamanan/",
                "/logout/",
                "/workspace/",
                "/static/",
                "/login/",
                "/auth/google/tautkan/",
            )
            if (
                settings.REQUIRE_STAFF_MFA
                and role != "CUSTOMER"
                and not request.path.startswith(exempt)
            ):
                if not AccountSecurity.objects.filter(
                    user=request.user, enabled_at__isnull=False
                ).exists():
                    return redirect("security")
                if not request.session.get("mfa_verified"):
                    return redirect("mfa_login")
            # Owner is explicitly read-only, even if a crafted POST targets another module.
            if (
                role == "OWNER"
                and request.method not in {"GET", "HEAD", "OPTIONS"}
                and not request.path.startswith(exempt)
            ):
                return HttpResponseForbidden("Workspace Owner hanya dapat melihat data.")
        return self.get_response(request)
