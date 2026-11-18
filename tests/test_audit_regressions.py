"""Acceptance tests for QA-01 and QA-03 through QA-08; never use provider credentials."""
from io import StringIO
import os
import subprocess
import sys
from pathlib import Path
from django.conf import settings
from unittest.mock import patch, Mock
from decimal import Decimal
from django.test import TestCase, SimpleTestCase, RequestFactory, override_settings
from django.core.management import call_command, CommandError
from django.core.exceptions import ValidationError
from django.urls import reverse
from core.models import StoreSettings, OutboxEvent
from core.admin import management_site
from core.services import BusinessError, emit
from config.debug_policy import debug_allowed
from billing.models import Invoice, PaymentAttempt
from billing.services import begin_payment, reconcile_attempt
from billing.providers import SessionRejected, create_snap
from orders.services import draft_order, checkout, pack_order
from delivery.services import quote_order, request_shipment
from .factories import fixture, login_as, pay

class DebugPolicyTests(SimpleTestCase):
    def test_public_hosts_and_webhook_disable_debug(self):
        for hosts, webhook in [(['localhost','shop.example'],''),(['*'],''),(['.example.com'],''),(['localhost'],'https://tunnel.example')]:
            self.assertFalse(debug_allowed(True, True, hosts, webhook))
        self.assertFalse(debug_allowed(True, False, ['localhost'], ''))
        self.assertTrue(debug_allowed(True, True, ['localhost','127.0.0.1','[::1]'], ''))
        self.assertFalse(debug_allowed(False, True, ['localhost'], ''))

    def test_settings_ignore_debug_true_for_public_tunnel(self):
        env = os.environ.copy()
        env.update(DEBUG="true", DEPLOYMENT_MODE="local", ALLOWED_HOSTS="localhost,shop.example", PUBLIC_WEBHOOK_BASE_URL="https://shop.example")
        result = subprocess.run([sys.executable,"-c","import config.settings as s; print(s.DEBUG)"], cwd=settings.BASE_DIR, env=env, check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(),"False")


@override_settings(ROUTES_MODE='mock', SHIPPING_MODE='mock', MOCK_ROUTE_DISTANCE_M=3200, PAYMENT_MODE='mock')
class AuditRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls): fixture(cls)

    def invoice(self):
        order = draft_order(self.user, {str(self.variant.pk): 1}, 'PICKUP')
        checkout(self.user, order, 'audit-checkout')
        return Invoice.objects.get(order=order)

    def test_mock_replaced_by_gateway_attempt(self):
        invoice = self.invoice(); old = begin_payment(self.user, invoice, 'audit-pay-1')
        with override_settings(PAYMENT_MODE='midtrans_sandbox'):
            with patch('billing.providers.create_snap', return_value={'redirect_url':'https://app.sandbox.midtrans.com/snap/test'}) as provider:
                current = begin_payment(self.user, invoice, 'audit-pay-2')
        old.refresh_from_db()
        self.assertEqual(old.status,'FAILED'); self.assertNotEqual(current.pk, old.pk)
        self.assertEqual(current.environment,'midtrans_sandbox'); provider.assert_called_once()

    @override_settings(PAYMENT_MODE='midtrans_sandbox', MIDTRANS_LIVE=False, MIDTRANS_SERVER_KEY='test-key')
    def test_401_can_retry_and_ambiguous_timeout_cannot(self):
        invoice = self.invoice()
        response = Mock(status_code=401)
        with patch('billing.providers.requests.post', return_value=response):
            with self.assertRaises(BusinessError): begin_payment(self.user, invoice, 'audit-pay-1')
        self.assertEqual(PaymentAttempt.objects.get(invoice=invoice).status,'FAILED')
        with patch('billing.providers.create_snap', side_effect=TimeoutError):
            with self.assertRaises(BusinessError): begin_payment(self.user, invoice, 'audit-pay-2')
        unknown=PaymentAttempt.objects.get(invoice=invoice,status='UNKNOWN')
        with patch('billing.providers.create_snap') as provider:
            reused=begin_payment(self.user, invoice, 'audit-pay-3')
        self.assertEqual(reused.pk,unknown.pk); provider.assert_not_called()

    @override_settings(PAYMENT_MODE='midtrans_sandbox', MIDTRANS_LIVE=False, MIDTRANS_SERVER_KEY='test-key')
    def test_duplicate_400_stays_ambiguous(self):
        response=Mock(status_code=400); response.json.return_value={'error_messages':['transaction_details.order_id has been paid and utilized']}
        response.raise_for_status.side_effect=RuntimeError('provider error')
        with patch('billing.providers.requests.post',return_value=response):
            with self.assertRaises(BusinessError):begin_payment(self.user,self.invoice(),'duplicate')
        self.assertEqual(PaymentAttempt.objects.get().status,'UNKNOWN')

    def test_real_attempt_never_reused_or_reconciled_in_other_environment(self):
        invoice=self.invoice()
        old=PaymentAttempt.objects.create(invoice=invoice,provider='MIDTRANS',environment='midtrans_sandbox',provider_order_id='test-cross-mode',request_key='mode',status='PENDING',expected_amount_rp=invoice.total_rp,expires_at=invoice.expires_at)
        with override_settings(PAYMENT_MODE='midtrans_live'):
            with patch('billing.providers.create_snap') as create,patch('billing.providers.get_status') as status:
                with self.assertRaises(BusinessError):begin_payment(self.user,invoice,'live')
                with self.assertRaises(BusinessError):reconcile_attempt(old)
            create.assert_not_called();status.assert_not_called()
        old.refresh_from_db();self.assertEqual(old.status,'PENDING')

    def test_changed_origin_rejects_internal_and_instant_checkout(self):
        for method in ['INTERNAL','INSTANT']:
            order=draft_order(self.user,{str(self.variant.pk):1},'DELIVERY',self.address)
            quote=next(q for q in quote_order(order)[0] if q.method==method)
            store=StoreSettings.objects.get(pk=1);store.longitude+=Decimal('1');store.save()
            with self.assertRaisesMessage(BusinessError,'asal/tujuan berubah'):checkout(self.user,order,'origin-'+method,quote)
            order.refresh_from_db();self.assertEqual(order.status,'DRAFT')

    def test_origin_change_after_payment_blocks_shipment(self):
        order=draft_order(self.user,{str(self.variant.pk):1},'DELIVERY',self.address)
        quote=next(q for q in quote_order(order)[0] if q.method=='INTERNAL')
        checkout(self.user,order,'dispatch-origin',quote);pay(Invoice.objects.get(order=order));order.refresh_from_db();pack_order(self.admin,order);order.refresh_from_db()
        StoreSettings.objects.filter(pk=1).update(address='Changed origin')
        with self.assertRaisesMessage(BusinessError,'Lokasi/kontak asal berubah'):request_shipment(self.admin,order)
        from delivery.models import Shipment
        self.assertFalse(Shipment.objects.filter(order=order).exists())

    def test_legacy_quote_requires_requote(self):
        order=draft_order(self.user,{str(self.variant.pk):1},'DELIVERY',self.address)
        quote=quote_order(order)[0][0];quote.origin_fingerprint='';quote.save()
        with self.assertRaises(BusinessError):checkout(self.user,order,'legacy',quote)

    def test_readonly_admin_never_renders_hidden_payload(self):
        event=emit('audit.fixture',self.pet,{'hidden':'AUDIT_PAYLOAD_MARKER'},secret='AUDIT_SECRET_MARKER')
        for role in ['OWNER','ADMIN','SUPER_ADMIN']:
            request=RequestFactory().get('/management/');request.user=self.users[role];request.user.workspace_role=role
            admin=management_site._registry[OutboxEvent]
            self.assertNotIn('sensitive_ciphertext',admin.get_fields(request,event));self.assertNotIn('payload',admin.get_fields(request,event))
            login_as(self.client,self.users[role])
            response=self.client.get(reverse('management:core_outboxevent_change',args=[event.pk]))
            self.assertEqual(response.status_code,200)
            self.assertNotContains(response,'AUDIT_PAYLOAD_MARKER');self.assertNotContains(response,event.sensitive_ciphertext)

    def test_approved_store_rejects_missing_origin_and_bad_contact(self):
        store=StoreSettings.objects.get(pk=1);store.public_contact_ready=True;store.cs_whatsapp='abc';store.address='';store.latitude=None
        with self.assertRaises(ValidationError) as error:store.full_clean()
        self.assertTrue({'cs_whatsapp','address','latitude'}.issubset(error.exception.message_dict))
        StoreSettings.objects.filter(pk=1).update(public_contact_ready=True,cs_whatsapp='abc',address='',latitude=None)
        with patch('core.management.commands.check_integrations.readiness_issues',return_value=[]):
            with self.assertRaises(CommandError):call_command('check_integrations',strict=True,stdout=StringIO())

    def test_valid_official_store_and_readiness(self):
        store=StoreSettings.objects.get(pk=1);store.cs_whatsapp='628123456789';store.public_contact_ready=True;store.full_clean();store.save()
        with patch('core.management.commands.check_integrations.readiness_issues',return_value=[]):call_command('check_integrations',strict=True,stdout=StringIO())

    def test_bad_timezone_hours_and_coordinates_rejected(self):
        store=StoreSettings.objects.get(pk=1);store.cs_whatsapp='628123456789';store.public_contact_ready=True
        store.latitude=91;store.timezone='Invalid/Zone';store.opening_hours={'0':['19:00','08:00']}
        with self.assertRaises(ValidationError) as error:store.full_clean()
        self.assertTrue({'latitude','timezone','opening_hours'}.issubset(error.exception.message_dict))
