"""Provider requests use server-side credentials, bounded timeouts and immutable references."""

import secrets
import requests
from .routing import ors_route_distance
from django.conf import settings
from core.services import BusinessError


def route_distance(origin, destination, travel_mode):
    if settings.ROUTES_MODE == "mock":
        if not settings.LOCAL_MODE:
            raise BusinessError("Simulasi rute tidak tersedia.")
        # Explicit fixed fixture for local UX tests, never represented as a measured road route.
        return settings.MOCK_ROUTE_DISTANCE_M
    if settings.ROUTES_MODE == "openrouteservice":
        return ors_route_distance(origin, destination, travel_mode)
    raise BusinessError("Perhitungan rute belum aktif. Pilih ambil di toko atau kurir instan.")


def biteship_request(method, path, payload=None):
    if not settings.BITESHIP_API_KEY:
        raise BusinessError("Integrasi Biteship belum dikonfigurasi.")
    return requests.request(
        method,
        "https://api.biteship.com" + path,
        json=payload,
        headers={"Authorization": settings.BITESHIP_API_KEY, "Accept": "application/json"},
        timeout=(5, 20),
    )


def instant_rates(origin, destination, items):
    if settings.SHIPPING_MODE == "disabled":
        raise BusinessError("Kurir instan belum diaktifkan. Pilih ambil di toko atau Kurir Toko.")
    if settings.SHIPPING_MODE == "mock":
        if not settings.LOCAL_MODE:
            raise BusinessError("Simulasi kurir tidak tersedia.")
        return [
            {
                "courier_code": "mock",
                "courier_service_code": "instant",
                "price": settings.MOCK_INSTANT_FEE_RP,
                "courier_name": "Kurir instan — simulasi lokal",
            }
        ]
    response = biteship_request(
        "POST",
        "/v1/rates/couriers",
        {
            "origin_latitude": float(origin[0]),
            "origin_longitude": float(origin[1]),
            "destination_latitude": float(destination[0]),
            "destination_longitude": float(destination[1]),
            "couriers": "gojek,grab",
            "items": items,
        },
    )
    response.raise_for_status()
    return [
        p
        for p in response.json().get("pricing", [])
        if p.get("courier_service_code") == "instant" and p.get("available_for_instant", True)
    ]


def create_external_shipment(shipment, payload):
    if shipment.provider == "MOCK":
        if not settings.LOCAL_MODE:
            raise BusinessError("Simulasi kurir tidak tersedia.")
        return {
            "id": "mock-" + str(shipment.pk),
            "reference_id": shipment.request_key,
            "status": "confirmed",
        }
    response = biteship_request("POST", "/v1/orders", payload)
    data = response.json()
    if str(data.get("code")) == "40002060" and data.get("details", {}).get("order_id"):
        # Reuse the original reference after an ambiguous timeout; never create a new shipment reference.
        data = get_external_shipment(data["details"]["order_id"])
    else:
        response.raise_for_status()
    if data.get("reference_id") != shipment.request_key or not data.get("id"):
        raise BusinessError("Respons pengiriman perlu direkonsiliasi.")
    return data


def get_external_shipment(provider_id):
    response = biteship_request("GET", f"/v1/orders/{provider_id}")
    response.raise_for_status()
    return response.json()


def authenticated_webhook(request):
    key, secret = settings.BITESHIP_WEBHOOK_HEADER, settings.BITESHIP_WEBHOOK_SECRET
    return bool(secret and secrets.compare_digest(request.headers.get(key, ""), secret))
