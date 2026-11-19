from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from config.integration_checks import readiness_issues, validate_modes_and_urls
from core.services import BusinessError
from delivery.models import RouteEstimate
from delivery.providers import route_distance
from .factories import fixture, login_as


@override_settings(
    ROUTES_MODE="openrouteservice", ORS_API_KEY="PRIVATE-ORS-KEY", ORS_CACHE_SECONDS=3600
)
class FreeRoutingTests(TestCase):
    @patch("delivery.routing.requests.post")
    def test_ors_coordinate_order_meters_header_and_conservative_rounding(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"routes": [{"summary": {"distance": 5000.1}}]}
        self.assertEqual(route_distance((-6.2, 106.8), (-6.3, 106.9), "DRIVE"), 5001)
        self.assertEqual(
            post.call_args.args[0], "https://api.heigit.org/openrouteservice/v2/directions/driving-car/json"
        )
        payload = post.call_args.kwargs
        self.assertEqual(payload["json"]["coordinates"], [[106.8, -6.2], [106.9, -6.3]])
        self.assertEqual(payload["json"]["units"], "m")
        self.assertEqual(payload["headers"]["Authorization"], "PRIVATE-ORS-KEY")
        self.assertFalse(payload["allow_redirects"])
        self.assertEqual(route_distance((-6.2, 106.8), (-6.3, 106.9), "DRIVE"), 5001)
        self.assertEqual(post.call_count, 1)
        self.assertNotIn("PRIVATE-ORS-KEY", RouteEstimate.objects.get().cache_key)

    @patch("delivery.routing.requests.post")
    def test_expired_estimate_requires_new_provider_verification(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"routes": [{"summary": {"distance": 4900}}]}
        route_distance((-6.2, 106.8), (-6.3, 106.9), "DRIVE")
        RouteEstimate.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        post.return_value.json.return_value = {"routes": [{"summary": {"distance": 5100}}]}
        self.assertEqual(route_distance((-6.2, 106.8), (-6.3, 106.9), "DRIVE"), 5100)
        self.assertEqual(post.call_count, 2)

    @override_settings(ORS_REQUESTS_PER_MINUTE=1, ORS_CACHE_SECONDS=0)
    @patch("delivery.routing.requests.post")
    def test_shared_local_quota_stops_request_before_api_call(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"routes": [{"summary": {"distance": 3200}}]}
        route_distance((-6.2, 106.8), (-6.3, 106.9), "DRIVE")
        with self.assertRaises(BusinessError):
            route_distance((-6.2, 106.8), (-6.4, 106.9), "DRIVE")
        self.assertEqual(post.call_count, 1)

    @patch("delivery.routing.requests.post")
    def test_provider_quota_failure_never_creates_fake_or_cached_distance(self, post):
        post.return_value.status_code = 429
        with self.assertRaises(BusinessError):
            route_distance((-6.2, 106.8), (-6.3, 106.9), "DRIVE")
        self.assertFalse(RouteEstimate.objects.exists())
        self.assertEqual(post.call_count, 1)

    @patch("delivery.routing.requests.post")
    def test_malformed_nonfinite_and_negative_distances_are_rejected(self, post):
        post.return_value.status_code = 200
        for value in [float("nan"), -1, True, "500", None]:
            post.return_value.json.return_value = {"routes": [{"summary": {"distance": value}}]}
            with self.assertRaises(BusinessError):
                route_distance((-6.2, 106.8), (-6.3, 106.9), "DRIVE")
        self.assertFalse(RouteEstimate.objects.exists())

    @override_settings(ORS_API_KEY="")
    @patch("delivery.routing.requests.post")
    def test_missing_key_does_not_call_provider(self, post):
        with self.assertRaises(BusinessError):
            route_distance((-6.2, 106.8), (-6.3, 106.9), "DRIVE")
        post.assert_not_called()

    @patch("delivery.routing.requests.post")
    def test_invalid_coordinate_and_unsupported_mode_do_not_call_provider(self, post):
        for origin, mode in [
            ((float("nan"), 106), "DRIVE"),
            ((100, 106), "DRIVE"),
            ((-6, 106), "TWO_WHEELER"),
        ]:
            with self.assertRaises(BusinessError):
                route_distance(origin, (-6.3, 106.9), mode)
        post.assert_not_called()


class FreeMapPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def test_address_page_has_local_leaflet_and_attribution_without_google_maps_scripts(self):
        login_as(self.client, self.user)
        response = self.client.get("/alamat/?baru=1")
        self.assertContains(response, "vendor/leaflet/leaflet.js")
        self.assertContains(response, "tile.openstreetmap.org")
        self.assertContains(response, "OpenStreetMap contributors")
        self.assertNotContains(response, "maps.googleapis.com")
        self.assertNotContains(response, "PRIVATE-ORS-KEY")
        self.assertIn("https://tile.openstreetmap.org", response["Content-Security-Policy"])
        self.assertEqual(response["Referrer-Policy"], "strict-origin-when-cross-origin")


class FreeMapConfigTests(SimpleTestCase):
    @override_settings(
        ROUTES_MODE="openrouteservice",
        ORS_API_KEY="test",
        GOOGLE_CLIENT_ID="id",
        GOOGLE_CLIENT_SECRET="secret",
    )
    def test_readiness_does_not_require_any_google_maps_key(self):
        self.assertFalse(any("MAPS_" in issue for issue in readiness_issues()))
        self.assertFalse(any("ORS_API_KEY" in issue for issue in readiness_issues()))
        validate_modes_and_urls()

    @override_settings(MAP_TILE_URL="http://tile.openstreetmap.org/{z}/{x}/{y}.png")
    def test_insecure_tiles_are_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            validate_modes_and_urls()
