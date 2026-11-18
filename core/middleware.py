import uuid
from urllib.parse import urlsplit
from django.conf import settings
from .request_context import request_id


class ResponseSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4()
        token = request_id.set(request.request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id.reset(token)
        response["X-Request-ID"] = str(request.request_id)
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
        tile_origin = "https://" + urlsplit(settings.MAP_TILE_URL).netloc
        policy = (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            f"font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: {tile_origin}; "
            f"connect-src 'self' {tile_origin}; "
            "frame-src https://www.google.com; object-src 'none'; base-uri 'self'; "
            "form-action 'self' https://accounts.google.com https://app.sandbox.midtrans.com https://app.midtrans.com; frame-ancestors 'none'"
        )
        if not response.has_header("Content-Security-Policy"):
            response["Content-Security-Policy"] = policy
        if getattr(
            getattr(request, "user", None), "is_authenticated", False
        ) or request.path.startswith(
            (
                "/login",
                "/register",
                "/otp",
                "/forgot",
                "/reset",
                "/berkas",
                "/undangan",
                "/auth/",
                "/keamanan/",
            )
        ):
            response["Cache-Control"] = "no-store, private"
        return response

    def process_exception(self, request, exception):
        from django.core.exceptions import ValidationError
        from django.http import HttpResponseBadRequest

        if isinstance(exception, ValidationError):
            return HttpResponseBadRequest(
                "Data permintaan tidak valid. Periksa isian dan muat ulang formulir."
            )
