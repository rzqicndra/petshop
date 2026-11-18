import hashlib
from types import SimpleNamespace
from unittest.mock import Mock, patch
from django.test import SimpleTestCase, override_settings
from billing.providers import verify_notification, rupiah, settled, create_snap
from delivery.providers import route_distance, create_external_shipment
from core.services import BusinessError


class ProviderContractTests(SimpleTestCase):
    @override_settings(MIDTRANS_SERVER_KEY="server-test-key")
    def test_midtrans_signature_uses_original_amount_string(self):
        payload = {"order_id": "SS-PAY-1", "status_code": "200", "gross_amount": "95000.00"}
        payload["signature_key"] = hashlib.sha512(b"SS-PAY-120095000.00server-test-key").hexdigest()
        self.assertTrue(verify_notification(payload))
        payload["gross_amount"] = "95000"
        self.assertFalse(verify_notification(payload))
        self.assertFalse(verify_notification({}))

    def test_money_is_integer_rupiah_and_fraud_not_accepted(self):
        self.assertEqual(rupiah("95000.00"), 95000)
        for value in ["NaN", "1.50", "-1", "infinity"]:
            with self.assertRaises(BusinessError):
                rupiah(value)
        self.assertFalse(settled({"transaction_status": "capture", "fraud_status": "challenge"}))
        self.assertTrue(settled({"transaction_status": "settlement", "fraud_status": "accept"}))

    @override_settings(ROUTES_MODE="disabled")
    def test_disabled_routing_never_uses_an_external_provider(self):
        with self.assertRaises(BusinessError):
            route_distance((0, 0), (1, 1), "DRIVE")

    @override_settings(LOCAL_MODE=False, ROUTES_MODE="mock")
    def test_mock_routes_forbidden_outside_local(self):
        with self.assertRaises(BusinessError):
            route_distance((0, 0), (1, 1), "DRIVE")

    @patch("delivery.providers.get_external_shipment")
    @patch("delivery.providers.biteship_request")
    def test_biteship_duplicate_reference_is_reconciled(self, request, get):
        request.return_value.json.return_value = {
            "code": 40002060,
            "details": {"order_id": "biteship-known-id"},
        }
        get.return_value = {
            "id": "biteship-known-id",
            "reference_id": "same-reference",
            "status": "confirmed",
        }
        shipment = SimpleNamespace(provider="BITESHIP", request_key="same-reference")
        result = create_external_shipment(shipment, {"reference_id": "same-reference"})
        self.assertEqual(result["id"], "biteship-known-id")
        get.assert_called_once_with("biteship-known-id")

    @override_settings(MIDTRANS_SERVER_KEY="server-key", MIDTRANS_LIVE=False)
    @patch("billing.providers.requests.post")
    def test_snap_redirect_must_belong_to_configured_gateway(self, post):
        from django.utils import timezone
        from datetime import timedelta

        attempt = SimpleNamespace(
            provider_order_id="SS-PAY-1",
            expected_amount_rp=95000,
            created_at=timezone.now(),
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        post.return_value.json.return_value = {"redirect_url": "https://evil.example/pay"}
        with self.assertRaises(BusinessError):
            create_snap(attempt)
