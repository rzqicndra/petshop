import secrets
import time
from datetime import timedelta

import pyotp
from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import make_password
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.services import BusinessError, audit, cipher
from .forms import LoginForm, RegisterForm, EmailForm, OTPForm, ResetForm
from .models import User, ExternalIdentity, AccountSecurity
from .permissions import active_role, user_roles, workspace_url, verified_login
from .services import rate_limit, create_customer_user, issue_otp, verify_otp, verify_totp


def client_ip(request):
    return request.META.get("REMOTE_ADDR", "unknown")


def finish_login(request, user, mfa=False):
    if not active_role(user):
        messages.error(request, "Peran akun belum dikonfigurasi. Hubungi pengelola.")
        return redirect("login")
    login(request, user)
    request.session["auth_version"] = user.auth_version
    request.session["workspace"] = active_role(user)
    request.session["mfa_verified"] = mfa
    request.session["authenticated_at"] = time.time()
    nxt = request.session.pop("next_url", "")
    if (
        active_role(user) == "CUSTOMER"
        and nxt
        and url_has_allowed_host_and_scheme(
            nxt, {request.get_host()}, require_https=request.is_secure()
        )
    ):
        return redirect(nxt)
    return redirect(workspace_url(active_role(user)))


def enter_authenticated(request, user):
    if AccountSecurity.objects.filter(user=user, enabled_at__isnull=False).exists():
        request.session.cycle_key()
        request.session["preauth"] = {
            "user": str(user.pk),
            "time": time.time(),
            "version": user.auth_version,
        }
        return redirect("mfa_login")
    return finish_login(request, user)


def login_view(request):
    if request.user.is_authenticated:
        return redirect(workspace_url(active_role(request.user)))
    if request.GET.get("next"):
        nxt = request.GET["next"]
        if url_has_allowed_host_and_scheme(
            nxt, {request.get_host()}, require_https=request.is_secure()
        ):
            request.session["next_url"] = nxt
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        try:
            rate_limit("login-ip", client_ip(request), 40, 900)
            rate_limit("login-email", email, 8, 900)
            user = authenticate(request, username=email, password=form.cleaned_data["password"])
            if not user:
                raise BusinessError("Email atau password tidak sesuai.")
            if not user.email_verified_at:
                issue_otp(user, "REGISTER")
                request.session["otp_user"], request.session["otp_purpose"] = (
                    str(user.pk),
                    "REGISTER",
                )
                return redirect("verify_otp")
            return enter_authenticated(request, user)
        except BusinessError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "accounts/auth.html",
        {"form": form, "title": "Selamat datang kembali.", "mode": "login", "button": "Login"},
    )


def register_view(request):
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            email = form.cleaned_data["email"]
            rate_limit("register-ip", client_ip(request), 10, 3600)
            rate_limit("register-email", email, 5, 3600)
            # Existing accounts are never overwritten or assigned a new role by public registration.
            user = User.objects.filter(email__iexact=email).first()
            if not user:
                try:
                    with transaction.atomic():
                        user = create_customer_user(
                            email, form.cleaned_data["full_name"], form.cleaned_data["password"]
                        )
                except IntegrityError:
                    user = User.objects.filter(email__iexact=email).first()
            target = user if user and not user.email_verified_at else None
            if target:
                issue_otp(target, "REGISTER")
            request.session["otp_user"] = str(target.pk) if target else None
            request.session["otp_purpose"] = "REGISTER"
            messages.info(
                request,
                "Jika pendaftaran dapat diproses, kode verifikasi dikirim ke email. Akun terdaftar dapat menggunakan Forgot password.",
            )
            return redirect("verify_otp")
        except BusinessError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "accounts/auth.html",
        {
            "form": form,
            "title": "Mulai merawat, lebih dekat.",
            "mode": "register",
            "button": "Register",
        },
    )


def forgot_view(request):
    form = EmailForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            email = form.cleaned_data["email"].strip().lower()
            rate_limit("reset-ip", client_ip(request), 15, 3600)
            rate_limit("reset-email", email, 5, 3600)
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user:
                issue_otp(user, "RESET")
            request.session["otp_user"] = str(user.pk) if user else None
            request.session["otp_purpose"] = "RESET"
            messages.info(
                request, "Jika email terdaftar, kode pemulihan dikirim. Kode berlaku 5 menit."
            )
            return redirect("verify_otp")
        except BusinessError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "accounts/auth.html",
        {"form": form, "title": "Lupa password?", "mode": "forgot", "button": "Kirim kode OTP"},
    )


def verify_view(request):
    purpose = request.session.get("otp_purpose")
    if purpose not in {"REGISTER", "RESET", "INVITE"}:
        return redirect("login")
    form = OTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            rate_limit("otp-ip", client_ip(request), 30, 900)
            user = verify_otp(request.session.get("otp_user"), purpose, form.cleaned_data["code"])
            if purpose in {"RESET", "INVITE"}:
                request.session["reset_grant"] = {
                    "user": str(user.pk),
                    "time": time.time(),
                    "version": user.auth_version,
                }
                return redirect("reset_password")
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at", "updated_at"])
            request.session.pop("otp_user", None)
            request.session.pop("otp_purpose", None)
            messages.success(request, "Email terverifikasi. Silakan Login untuk melanjutkan.")
            return redirect("login")
        except BusinessError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "accounts/auth.html",
        {"form": form, "title": "Periksa email Anda.", "mode": "otp", "button": "Verifikasi OTP"},
    )


@require_POST
def resend_view(request):
    try:
        rate_limit("resend-ip", client_ip(request), 10, 3600)
        user = User.objects.filter(pk=request.session.get("otp_user"), is_active=True).first()
        purpose = request.session.get("otp_purpose")
        if user and purpose in {"REGISTER", "RESET", "INVITE"}:
            rate_limit("resend-email", user.email, 8, 3600)
            issue_otp(user, purpose)
        messages.info(
            request,
            "Jika memenuhi syarat, kode dikirim ulang. Tunggu minimal 60 detik antar permintaan.",
        )
    except BusinessError as exc:
        messages.error(request, exc.messages[0])
    return redirect("verify_otp")


def reset_view(request):
    grant = request.session.get("reset_grant", {})
    user = (
        User.objects.filter(pk=grant.get("user"), is_active=True).first()
        if grant.get("user")
        else None
    )
    if (
        not user
        or time.time() - grant.get("time", 0) > 300
        or grant.get("version") != user.auth_version
    ):
        return redirect("forgot_password")
    form = ResetForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            locked = User.objects.select_for_update().get(pk=user.pk)
            if locked.auth_version != grant["version"]:
                raise PermissionDenied
            locked.set_password(form.cleaned_data["password"])
            locked.auth_version += 1
            locked.email_verified_at = locked.email_verified_at or timezone.now()
            locked.save(
                update_fields=["password", "auth_version", "email_verified_at", "updated_at"]
            )
            audit(locked, "auth.password_reset", locked)
        request.session.flush()
        messages.success(
            request, "Password diperbarui. Semua sesi sebelumnya dicabut. Silakan Login."
        )
        return redirect("login")
    return render(
        request,
        "accounts/auth.html",
        {
            "form": form,
            "title": "Buat password baru.",
            "mode": "reset",
            "button": "Simpan password",
        },
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("home")


@require_POST
@verified_login
def switch_workspace(request):
    role = request.POST.get("role")
    if role not in user_roles(request.user):
        raise PermissionDenied
    request.session["workspace"] = role
    return redirect(workspace_url(role))


def google_client():
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise BusinessError("Login Google belum dikonfigurasi oleh pengelola.")
    oauth = OAuth()
    return oauth.register(
        "google",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def google_start(request):
    try:
        rate_limit("google-ip", client_ip(request), 20, 900)
        request.session.pop("google_link", None)
        return google_client().authorize_redirect(
            request, settings.APP_URL + reverse("google_callback")
        )
    except BusinessError as exc:
        messages.error(request, exc.messages[0])
        return redirect("login")


@verified_login
@require_POST
def google_link(request):
    if not request.user.check_password(request.POST.get("password", "")):
        messages.error(request, "Masukkan password akun saat ini untuk menautkan Google.")
        return redirect("security")
    request.session["google_link"] = {
        "user": str(request.user.pk),
        "time": time.time(),
        "version": request.user.auth_version,
    }
    return google_client().authorize_redirect(
        request, settings.APP_URL + reverse("google_callback")
    )


def google_callback(request):
    try:
        token = google_client().authorize_access_token(
            request
        )  # Authlib validates OIDC state, nonce, issuer, signature, audience, expiry.
        info = token.get("userinfo", {})
        if not info.get("sub") or not info.get("email") or info.get("email_verified") is not True:
            raise BusinessError("Google belum memverifikasi email tersebut.")
        email = info["email"].strip().lower()
        identity = (
            ExternalIdentity.objects.select_related("user")
            .filter(provider="google", subject=info["sub"])
            .first()
        )
        link = request.session.pop("google_link", None)
        if link:
            if (
                not request.user.is_authenticated
                or link["user"] != str(request.user.pk)
                or link["version"] != request.user.auth_version
                or time.time() - link["time"] > 300
            ):
                raise BusinessError("Sesi penautan berakhir. Ulangi dari keamanan akun.")
            if identity and identity.user_id != request.user.pk:
                raise BusinessError("Akun Google sudah terhubung ke akun lain.")
            ExternalIdentity.objects.get_or_create(
                provider="google", subject=info["sub"], defaults={"user": request.user}
            )
            audit(request.user, "auth.google_link", request.user)
            messages.success(request, "Akun Google berhasil ditautkan.")
            return redirect("security")
        if identity:
            user = identity.user
            if not user.is_active:
                raise BusinessError("Akun tidak tersedia.")
        else:
            if User.objects.filter(email__iexact=email).exists():
                raise BusinessError(
                    "Email ini sudah terdaftar. Login dengan password lalu tautkan Google di Keamanan akun."
                )
            with transaction.atomic():
                user = create_customer_user(email, info.get("name", email)[:150])
                ExternalIdentity.objects.create(user=user, provider="google", subject=info["sub"])
        if not user.email_verified_at:
            issue_otp(user, "REGISTER")
            request.session["otp_user"], request.session["otp_purpose"] = str(user.pk), "REGISTER"
            return redirect("verify_otp")
        return enter_authenticated(request, user)
    except Exception:
        # Never expose OAuth tokens or upstream error bodies in a response/log.
        messages.error(
            request,
            "Login Google tidak selesai. Jika email sudah terdaftar, Login dengan password dan tautkan Google melalui Keamanan akun.",
        )
        return redirect("login")


def mfa_login(request):
    grant = request.session.get("preauth", {})
    user = (
        User.objects.filter(pk=grant.get("user"), is_active=True).first()
        if grant.get("user")
        else request.user if request.user.is_authenticated else None
    )
    if not user or (
        grant
        and (time.time() - grant.get("time", 0) > 300 or grant.get("version") != user.auth_version)
    ):
        return redirect("login")
    error = None
    if request.method == "POST":
        try:
            rate_limit("mfa", str(user.pk), 8, 900)
            if not verify_totp(user, request.POST.get("code", "")):
                raise BusinessError("Kode autentikator atau kode pemulihan tidak sesuai.")
            request.session.pop("preauth", None)
            return finish_login(request, user, mfa=True)
        except BusinessError as exc:
            error = exc.messages[0]
    return render(request, "accounts/mfa.html", {"error": error})


@verified_login
def security_view(request):
    sec, _ = AccountSecurity.objects.get_or_create(user=request.user)
    secret, recovery = None, None
    if request.method == "POST":
        try:
            rate_limit("security", str(request.user.pk), 10, 900)
            action = request.POST.get("action")
            if action == "begin":
                if sec.enabled_at:
                    raise BusinessError("Autentikator sudah aktif.")
                if not request.user.check_password(request.POST.get("password", "")):
                    raise BusinessError(
                        "Password tidak sesuai. Akun Google dapat mengatur password melalui Forgot password."
                    )
                secret = pyotp.random_base32()
                sec.totp_ciphertext = cipher().encrypt(secret.encode()).decode()
                sec.save(update_fields=["totp_ciphertext", "updated_at"])
                request.session["mfa_setup_at"] = time.time()
            elif action == "confirm":
                if (
                    sec.enabled_at
                    or time.time() - request.session.get("mfa_setup_at", 0) > 300
                    or not sec.totp_ciphertext
                ):
                    raise BusinessError("Sesi pengaturan berakhir.")
                secret = cipher().decrypt(sec.totp_ciphertext.encode()).decode()
                if not pyotp.TOTP(secret).verify(request.POST.get("code", ""), valid_window=0):
                    raise BusinessError("Kode autentikator tidak sesuai.")
                recovery = [secrets.token_hex(6) for _ in range(8)]
                sec.recovery_digests = [make_password(x) for x in recovery]
                sec.enabled_at = timezone.now()
                sec.last_counter = int(time.time()) // 30
                sec.save()
                secret = None
                request.session["mfa_verified"] = True
                audit(request.user, "auth.mfa_enabled", request.user)
                messages.success(
                    request,
                    "Autentikator aktif. Simpan kode pemulihan sekarang; kode tidak ditampilkan lagi.",
                )
            elif action == "disable":
                if settings.REQUIRE_STAFF_MFA and active_role(request.user) != "CUSTOMER":
                    raise BusinessError("MFA wajib untuk akun staf pada lingkungan ini.")
                if not request.user.check_password(
                    request.POST.get("password", "")
                ) or not verify_totp(request.user, request.POST.get("code", "")):
                    raise BusinessError("Password dan kode autentikator diperlukan.")
                sec.refresh_from_db()
                sec.enabled_at, sec.totp_ciphertext, sec.recovery_digests = None, "", []
                sec.save()
                audit(request.user, "auth.mfa_disabled", request.user)
        except BusinessError as exc:
            messages.error(request, exc.messages[0])
    return render(
        request,
        "accounts/security.html",
        {
            "security": sec,
            "totp_secret": secret,
            "recovery_codes": recovery,
            "totp_qr": authenticator_qr(secret, request.user.email) if secret else None,
            "google_linked": ExternalIdentity.objects.filter(
                user=request.user, provider="google"
            ).exists(),
        },
    )


def authenticator_qr(secret, email):
    from reportlab.graphics import renderSVG
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.barcode.qr import QrCodeWidget

    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="Sinau Satwa")
    qr = QrCodeWidget(uri)
    x1, y1, x2, y2 = qr.getBounds()
    drawing = Drawing(200, 200, transform=[200 / (x2 - x1), 0, 0, 200 / (y2 - y1), 0, 0])
    drawing.add(qr)
    return renderSVG.drawToString(drawing)
