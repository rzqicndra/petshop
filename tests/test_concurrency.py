import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import connections
from django.test import TransactionTestCase, override_settings
from accounts.models import User
from core.services import BusinessError
from inventory.models import InventoryBatch, StockHold
from orders.models import Order
from orders.services import draft_order, checkout
from scheduling.models import Booking, ServicePackage
from scheduling.services import create_booking
from customers.models import Pet
from .factories import fixture


@override_settings(ROUTES_MODE="mock", SHIPPING_MODE="mock", MOCK_ROUTE_DISTANCE_M=3200)
class ConcurrencyTests(TransactionTestCase):
    """Real independent PostgreSQL connections; no mocked locks or SQLite substitute."""

    def setUp(self):
        fixture(self)

    def test_two_checkouts_compete_for_last_item(self):
        InventoryBatch.objects.filter(pk=self.batch.pk).update(on_hand=1)
        a = draft_order(self.user, {str(self.variant.pk): 1}, "PICKUP")
        b = draft_order(self.other, {str(self.variant.pk): 1}, "PICKUP")
        barrier = Barrier(2)

        def contender(user_id, order_id):
            try:
                user = User.objects.get(pk=user_id)
                order = Order.objects.get(pk=order_id)
                barrier.wait(timeout=10)
                checkout(user, order, str(uuid.uuid4()))
                return "held"
            except BusinessError:
                return "sold-out"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(contender, self.user.pk, a.pk)
            two = pool.submit(contender, self.other.pk, b.pk)
            results = [one.result(timeout=20), two.result(timeout=20)]
        self.assertCountEqual(results, ["held", "sold-out"])
        self.batch.refresh_from_db()
        self.assertEqual((self.batch.on_hand, self.batch.reserved), (1, 1))
        self.assertEqual(StockHold.objects.filter(status="HELD").count(), 1)

    def test_two_bookings_compete_for_one_doctor(self):
        barrier = Barrier(2)

        def contender(user_id, pet_id):
            try:
                user = User.objects.get(pk=user_id)
                pet = Pet.objects.get(pk=pet_id)
                package = ServicePackage.objects.get(pk=self.packages["VET"].pk)
                barrier.wait(timeout=10)
                create_booking(user, pet, package, self.start, key=str(uuid.uuid4()))
                return "held"
            except BusinessError:
                return "full"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(contender, self.user.pk, self.pet.pk)
            two = pool.submit(contender, self.other.pk, self.pet2.pk)
            results = [one.result(timeout=20), two.result(timeout=20)]
        self.assertCountEqual(results, ["held", "full"])
        self.assertEqual(Booking.objects.count(), 1)

    def test_duplicate_payment_callbacks_apply_once_across_connections(self):
        from .factories import booking
        from billing.models import Invoice, PaymentAttempt, PaymentTransaction
        from billing.services import apply_settled_payment

        bk = booking(self)
        invoice = Invoice.objects.get(booking=bk)
        attempt = PaymentAttempt.objects.create(
            invoice=invoice,
            provider="MOCK",
            provider_order_id="CONCURRENT-PAY",
            expected_amount_rp=invoice.total_rp,
            request_key="CONCURRENT-PAY",
            expires_at=invoice.expires_at,
        )
        barrier = Barrier(2)

        def callback():
            try:
                local = PaymentAttempt.objects.get(pk=attempt.pk)
                barrier.wait(timeout=10)
                return apply_settled_payment(
                    local, "same-provider-transaction", local.expected_amount_rp
                ).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            one, two = pool.submit(callback), pool.submit(callback)
            self.assertEqual(one.result(timeout=20), two.result(timeout=20))
        self.assertEqual(PaymentTransaction.objects.count(), 1)

    def test_two_delivery_checkouts_compete_for_one_window(self):
        from delivery.services import quote_order
        from delivery.models import DeliveryReservation

        orders = [
            draft_order(self.user, {str(self.variant.pk): 1}, "DELIVERY", self.address)
            for _ in range(2)
        ]
        quotes = [
            next(q for q in quote_order(order)[0] if q.method == "INTERNAL") for order in orders
        ]
        barrier = Barrier(2)

        def contender(index):
            try:
                user = User.objects.get(pk=self.user.pk)
                local = Order.objects.get(pk=orders[index].pk)
                barrier.wait(timeout=10)
                checkout(user, local, str(uuid.uuid4()), quotes[index])
                return "held"
            except BusinessError:
                return "full"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            one, two = pool.submit(contender, 0), pool.submit(contender, 1)
            self.assertCountEqual(
                [one.result(timeout=20), two.result(timeout=20)], ["held", "full"]
            )
        self.assertEqual(DeliveryReservation.objects.filter(status="HELD").count(), 1)
