"""Shared validation for official store approval and integration readiness."""
import re
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.core.exceptions import ValidationError


def store_errors(store):
    errors = {}
    for field in ("business_name", "address"):
        if not str(getattr(store, field) or "").strip():
            errors[field] = "Wajib diisi sebelum data toko disahkan."
    if not re.fullmatch(r"62[1-9][0-9]{7,12}", str(store.cs_whatsapp or "")):
        errors["cs_whatsapp"] = "Gunakan nomor WhatsApp format 62, tanpa spasi atau tanda tambah."
    for field, limit in (("latitude", 90), ("longitude", 180)):
        try:
            value = Decimal(str(getattr(store, field)))
            if not value.is_finite() or not -limit <= value <= limit:
                raise ValueError
        except (InvalidOperation, ValueError, TypeError):
            errors[field] = "Koordinat wajib diisi dan berada dalam rentang yang valid."
    try:
        ZoneInfo(store.timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        errors["timezone"] = "Pilih zona waktu IANA valid, misalnya Asia/Jakarta."
    hours = store.opening_hours
    valid_time = lambda s: isinstance(s, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", s)
    if not isinstance(hours, dict) or not hours or any(
        day not in {str(x) for x in range(7)} or not isinstance(span, list) or len(span) != 2
        or not all(valid_time(t) for t in span) or span[0] >= span[1]
        for day, span in (hours.items() if isinstance(hours, dict) else [])
    ):
        errors["opening_hours"] = "Isi hari 0-6 dengan pasangan jam buka/tutup HH:MM yang berurutan."
    return errors


def validate_official_store(store):
    errors = store_errors(store)
    if errors:
        raise ValidationError(errors)
