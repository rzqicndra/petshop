"""Openrouteservice routing via HeiGIT: server key, shared quota guard and short cache."""

from datetime import timedelta
import hashlib
import json
import math
import requests
from django.conf import settings
from django.utils import timezone
from accounts.services import rate_limit
from core.services import BusinessError
from .models import RouteEstimate


def ors_route_distance(origin, destination, travel_mode):
    if not settings.ORS_API_KEY:
        raise BusinessError(
            "Key perhitungan rute belum diisi. Pilih ambil di toko atau kurir instan."
        )
    profile = {"DRIVE": "driving-car", "WALK": "foot-walking", "BICYCLE": "cycling-regular"}.get(
        travel_mode
    )
    if not profile:
        raise BusinessError("Moda rute belum didukung. Admin perlu memeriksa kebijakan pengiriman.")
    try:
        points = [[float(p[1]), float(p[0])] for p in (origin, destination)]
        if any(not math.isfinite(v) for p in points for v in p) or any(
            not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90) for p in points
        ):
            raise ValueError
    except (TypeError, ValueError, IndexError):
        raise BusinessError("Koordinat rute tidak valid.") from None
    cache_key = hashlib.sha256(
        json.dumps([settings.ORS_BASE_URL, profile, points], separators=(",", ":")).encode()
    ).hexdigest()
    now = timezone.now()
    cached = RouteEstimate.objects.filter(cache_key=cache_key, expires_at__gt=now).first()
    if cached:
        return cached.distance_m
    # Shared across this deployment's processes, unlike a per-worker memory counter.
    identity = hashlib.sha256(settings.ORS_API_KEY.encode()).hexdigest()
    rate_limit("ors-minute", identity, settings.ORS_REQUESTS_PER_MINUTE, 60)
    rate_limit("ors-day", identity, settings.ORS_REQUESTS_PER_DAY, 86400)
    try:
        response = requests.post(
            settings.ORS_BASE_URL + f"/v2/directions/{profile}/json",
            headers={"Authorization": settings.ORS_API_KEY, "Accept": "application/json"},
            json={
                "coordinates": points,
                "units": "m",
                "instructions": False,
                "geometry": False,
                "radiuses": [200, 200],
            },
            timeout=(5, 15),
            allow_redirects=False,
        )
        if response.status_code == 429:
            raise BusinessError("Kuota rute sedang penuh. Pilih ambil di toko atau kurir instan.")
        if response.status_code in {401, 403}:
            raise BusinessError("Key layanan rute ditolak. Admin perlu memeriksa konfigurasi.")
        if response.status_code != 200:
            raise BusinessError("Rute jalan belum tersedia untuk titik ini.")
        value = response.json()["routes"][0]["summary"]["distance"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            or value > 10000000
        ):
            raise ValueError
        # Never round down across a delivery limit (e.g. 5000.1 m must exceed 5 km).
        distance = math.ceil(value)
    except BusinessError:
        raise
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        raise BusinessError(
            "Layanan rute belum dapat memverifikasi jarak. Coba lagi atau pilih metode lain."
        ) from None
    if settings.ORS_CACHE_SECONDS:
        RouteEstimate.objects.update_or_create(
            cache_key=cache_key,
            defaults={
                "distance_m": distance,
                "expires_at": now + timedelta(seconds=settings.ORS_CACHE_SECONDS),
            },
        )
    RouteEstimate.objects.filter(expires_at__lte=now).delete()
    return distance
