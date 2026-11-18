import uuid
from datetime import timedelta
from unittest.mock import patch
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from billing.models import Invoice, PaymentTransaction, Refund, PaymentAttempt
from billing.services import apply_settled_payment, request_refund, process_refund, expire_unpaid
from scheduling.models import Booking, ResourceReservation
from scheduling.services import create_booking, reschedule_booking
from orders.services import draft_order, checkout, pack_order, handover_pickup
from orders.models import Order
from inventory.models import InventoryBatch, StockHold, StockMovement
from core.services import BusinessError
from .factories import fixture, booking, pay


@override_settings(PAYMENT_MODE="mock")
class CommerceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def test_checkout_holds_stock_payment_consumes_once_handover_completes(self):
        order = draft_order(self.user, {str(self.variant.pk): 2}, "PICKUP")
        order = checkout(self.user, order, str(uuid.uuid4()))
        self.batch.refresh_from_db()
        self.assertEqual((self.batch.on_hand, self.batch.reserved), (10, 2))
        payment = pay(Invoice.objects.get(order=order))
        self.batch.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual((self.batch.on_hand, self.batch.reserved), (8, 0))
        self.assertEqual(order.status, "PAID")
        apply_settled_payment(payment.attempt, payment.provider_transaction_id, payment.amount_rp)
        self.assertEqual(StockMovement.objects.filter(kind="SALE").count(), 1)
        pack_order(self.admin, order)
        order.refresh_from_db()
        handover_pickup(self.admin, order, "Ayu")
        order.refresh_from_db()
        self.assertEqual(order.status, "COMPLETED")
        self.assertIsNotNone(order.completed_at)

    def test_last_item_and_db_balance_protection(self):
        self.batch.on_hand = 1
        self.batch.save()
        first = draft_order(self.user, {str(self.variant.pk): 1}, "PICKUP")
        checkout(self.user, first, "first")
        other = draft_order(self.other, {str(self.variant.pk): 1}, "PICKUP")
        with self.assertRaises(BusinessError):
            checkout(self.other, other, "second")
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.reserved, 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            InventoryBatch.objects.filter(pk=self.batch.pk).update(on_hand=-1)

    def test_expired_stock_released_and_expired_batches_not_sold(self):
        order = draft_order(self.user, {str(self.variant.pk): 1}, "PICKUP")
        order = checkout(self.user, order, "expiry")
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        expire_unpaid()
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.reserved, 0)
        self.batch.expires_on = timezone.localdate()
        self.batch.save()
        fresh = draft_order(self.user, {str(self.variant.pk): 1}, "PICKUP")
        with self.assertRaises(BusinessError):
            checkout(self.user, fresh, "expired-batch")

    def test_fefo_uses_earliest_batch(self):
        early = InventoryBatch.objects.create(
            variant=self.variant,
            batch_code="EARLY",
            on_hand=1,
            expires_on=timezone.localdate() + timedelta(days=1),
        )
        order = draft_order(self.user, {str(self.variant.pk): 1}, "PICKUP")
        checkout(self.user, order, "fefo")
        self.assertEqual(StockHold.objects.get(order_item__order=order).batch_id, early.pk)

    def test_cart_or_price_change_requires_new_checkout(self):
        cart = {str(self.variant.pk): 1}
        order = draft_order(self.user, cart, "PICKUP")
        with self.assertRaises(BusinessError):
            checkout(self.user, order, "cart-change", cart={str(self.variant.pk): 2})
        self.variant.price_rp += 1000
        self.variant.save()
        with self.assertRaises(BusinessError):
            checkout(self.user, order, "price-change")

    def test_booking_payment_and_capacity_collision(self):
        bk = booking(self)
        payment = pay(Invoice.objects.get(booking=bk))
        bk.refresh_from_db()
        self.assertEqual(bk.status, "CONFIRMED")
        self.assertEqual(ResourceReservation.objects.get(booking=bk).status, "CONFIRMED")
        with self.assertRaises(BusinessError):
            booking(self, pet=self.pet2, actor=self.other)
        self.assertEqual(Booking.objects.count(), 1)

    def test_pet_cannot_have_overlapping_vet_and_grooming(self):
        booking(self, "VET")
        with self.assertRaises(BusinessError):
            booking(self, "GROOMING")

    def test_booking_idempotency_and_wrong_customer(self):
        key = str(uuid.uuid4())
        one = create_booking(self.user, self.pet, self.packages["VET"], self.start, key=key)
        two = create_booking(self.user, self.pet, self.packages["VET"], self.start, key=key)
        self.assertEqual(one.pk, two.pk)
        with self.assertRaises(BusinessError):
            create_booking(self.user, self.pet2, self.packages["VET"], self.start, key="wrong-pet")

    def test_reschedule_reallocates_and_old_version_cannot_repeat(self):
        bk = booking(self)
        pay(Invoice.objects.get(booking=bk))
        bk.refresh_from_db()
        reschedule_booking(self.user, bk, self.start + timedelta(hours=2), 1)
        bk.refresh_from_db()
        self.assertEqual(bk.version, 2)
        self.assertEqual(bk.starts_at, self.start + timedelta(hours=2))
        with self.assertRaises(BusinessError):
            reschedule_booking(self.user, bk, self.start + timedelta(hours=3), 1)

    def test_late_payment_keeps_money_without_stealing_slot(self):
        old = booking(self)
        invoice = Invoice.objects.get(booking=old)
        Booking.objects.filter(pk=old.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        ResourceReservation.objects.filter(booking=old).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        expire_unpaid()
        new = booking(self, pet=self.pet2, actor=self.other)
        payment = pay(invoice)
        old.refresh_from_db()
        new.refresh_from_db()
        self.assertEqual(old.status, "NEEDS_ATTENTION")
        self.assertEqual(payment.handling_status, "NEEDS_ATTENTION")
        self.assertTrue(ResourceReservation.objects.filter(booking=new, status="HELD").exists())
        self.assertEqual(PaymentTransaction.objects.count(), 1)

    def test_duplicate_distinct_funds_are_recorded_unapplied(self):
        bk = booking(self)
        invoice = Invoice.objects.get(booking=bk)
        first = pay(invoice)
        second = pay(invoice)
        self.assertTrue(first.is_applied)
        self.assertFalse(second.is_applied)
        self.assertEqual(second.handling_status, "DUPLICATE_FUNDS")
        self.assertEqual(PaymentTransaction.objects.count(), 2)

    def test_wrong_payment_amount_rejected(self):
        bk = booking(self)
        invoice = Invoice.objects.get(booking=bk)
        attempt = PaymentAttempt.objects.create(
            invoice=invoice,
            provider="MOCK",
            provider_order_id="wrong",
            expected_amount_rp=invoice.total_rp,
            request_key="wrong",
        )
        with self.assertRaises(BusinessError):
            apply_settled_payment(attempt, "tx", 1)
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_refunds_bounded_by_received_funds_and_no_automatic_stock_return(self):
        order = draft_order(self.user, {str(self.variant.pk): 1}, "PICKUP")
        checkout(self.user, order, "ref")
        payment = pay(Invoice.objects.get(order=order))
        refund = request_refund(self.admin, payment, 50000, "Retur diterima", "ref1")
        with self.assertRaises(BusinessError):
            request_refund(self.admin, payment, 50000, "Second", "ref2")
        process_refund(self.users["SUPER_ADMIN"], refund, "approve")
        process_refund(self.users["SUPER_ADMIN"], refund, "complete", "BANK-REF-001")
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.on_hand, 9)

    def test_owner_service_mutation_denied(self):
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            draft_order(
                self.users["OWNER"], {str(self.variant.pk): 1}, "PICKUP", customer=self.customer
            )

    def refund_all(self, payment):
        refund = request_refund(
            self.admin, payment, payment.amount_rp, "Pembatalan disepakati", str(uuid.uuid4())
        )
        process_refund(self.users["SUPER_ADMIN"], refund, "approve")
        process_refund(self.users["SUPER_ADMIN"], refund, "complete", "BANK-REF-FULL")

    def test_paid_booking_can_be_closed_after_full_refund(self):
        from scheduling.services import cancel_booking

        bk = booking(self)
        payment = pay(Invoice.objects.get(booking=bk))
        with self.assertRaises(BusinessError):
            cancel_booking(self.admin, bk, "Belum refund")
        self.refund_all(payment)
        cancel_booking(self.admin, bk, "Refund penuh selesai")
        bk.refresh_from_db()
        self.assertEqual(bk.status, "CANCELED")
        self.assertFalse(
            ResourceReservation.objects.filter(booking=bk, status="CONFIRMED").exists()
        )

    def test_refunded_order_closes_without_automatic_stock_return(self):
        from orders.services import cancel_order

        order = draft_order(self.user, {str(self.variant.pk): 1}, "PICKUP")
        checkout(self.user, order, "refund-close")
        payment = pay(Invoice.objects.get(order=order))
        self.refund_all(payment)
        cancel_order(self.admin, order, "Dana telah dikembalikan")
        order.refresh_from_db()
        self.batch.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(order.status, "CANCELED")
        self.assertEqual(self.batch.on_hand, 9)
        self.assertEqual(payment.handling_status, "REFUNDED")
