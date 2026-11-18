import uuid
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.utils import timezone
from core.services import BusinessError, commerce_transaction
from delivery.models import ShippingQuote, DeliveryReservation, Shipment
from delivery.services import quote_order, request_shipment, apply_shipment_status, assign_internal
from orders.services import draft_order, checkout, pack_order
from billing.models import Invoice
from .factories import fixture, pay


@override_settings(ROUTES_MODE="mock", SHIPPING_MODE="mock", MOCK_ROUTE_DISTANCE_M=3200)
class DeliveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def draft(self):
        return draft_order(self.user, {str(self.variant.pk): 1}, "DELIVERY", self.address)

    def test_nearby_offers_internal_and_instant(self):
        quotes, _ = quote_order(self.draft())
        self.assertEqual({q.method for q in quotes}, {"INTERNAL", "INSTANT"})

    @override_settings(MOCK_ROUTE_DISTANCE_M=5001)
    def test_outside_radius_does_not_offer_internal(self):
        quotes, _ = quote_order(self.draft())
        self.assertEqual({q.method for q in quotes}, {"INSTANT"})

    def test_route_api_failure_fails_closed_for_internal(self):
        with patch("delivery.providers.route_distance", side_effect=TimeoutError):
            quotes, notes = quote_order(self.draft())
        self.assertEqual({q.method for q in quotes}, {"INSTANT"})
        self.assertTrue(notes)

    def test_quote_changed_address_and_expired_quote_rejected(self):
        draft = self.draft()
        quotes, _ = quote_order(draft)
        from orders.models import OrderAddressSnapshot

        OrderAddressSnapshot.objects.filter(order=draft).update(full_address="Changed")
        with self.assertRaises(BusinessError):
            checkout(self.user, draft, "changed-address", quotes[0])
        fresh = self.draft()
        quotes, _ = quote_order(fresh)
        ShippingQuote.objects.filter(pk=quotes[0].pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(BusinessError):
            checkout(self.user, fresh, "expired-quote", quotes[0])

    def test_window_quota_includes_fulfilled(self):
        first = self.draft()
        quotes, _ = quote_order(first)
        internal = next(q for q in quotes if q.method == "INTERNAL")
        checkout(self.user, first, "first", internal)
        DeliveryReservation.objects.filter(order=first).update(status="FULFILLED")
        second = self.draft()
        newquotes, _ = quote_order(second)
        self.assertNotIn("INTERNAL", {q.method for q in newquotes})

    def test_different_quote_cannot_be_used_for_another_order(self):
        first = self.draft()
        quotes, _ = quote_order(first)
        second = self.draft()
        with self.assertRaises(BusinessError):
            checkout(self.user, second, "different", quotes[0])

    def paid_packed(self):
        draft = self.draft()
        quotes, _ = quote_order(draft)
        quote = next(q for q in quotes if q.method == "INSTANT")
        checkout(self.user, draft, str(uuid.uuid4()), quote)
        pay(Invoice.objects.get(order=draft))
        draft.refresh_from_db()
        pack_order(self.admin, draft)
        draft.refresh_from_db()
        return draft

    def test_shipment_is_idempotent_and_delivered_completes_order(self):
        order = self.paid_packed()
        one = request_shipment(self.admin, order)
        two = request_shipment(self.admin, order)
        self.assertEqual(one.pk, two.pk)
        self.assertEqual(Shipment.objects.count(), 1)
        with commerce_transaction():
            apply_shipment_status(
                one, {"reference_id": one.request_key, "status": "delivered"}, "delivered"
            )
        order.refresh_from_db()
        self.assertEqual(order.status, "COMPLETED")
        one.refresh_from_db()
        with commerce_transaction():
            apply_shipment_status(
                one, {"reference_id": one.request_key, "status": "in_transit"}, "old"
            )
        one.refresh_from_db()
        self.assertEqual(one.status, "DELIVERED")

    def test_dispatch_timeout_stays_unknown_no_second_shipment(self):
        order = self.paid_packed()
        with patch("delivery.providers.create_external_shipment", side_effect=TimeoutError):
            with self.assertRaises(BusinessError):
                request_shipment(self.admin, order)
        shipment = Shipment.objects.get()
        self.assertEqual(shipment.status, "UNKNOWN")
        self.assertEqual(request_shipment(self.admin, order).pk, shipment.pk)
        self.assertEqual(Shipment.objects.count(), 1)

    def test_shipping_webhook_rejects_forged_payload(self):
        self.assertEqual(
            self.client.post(
                "/webhooks/biteship/", data="{}", content_type="application/json"
            ).status_code,
            403,
        )
