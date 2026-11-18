"""Verify an existing database upgrades without guessing legacy payment environments."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from billing.models import Invoice
from orders.services import draft_order, checkout
from .factories import fixture


class AuditMigrationTests(TransactionTestCase):
    def test_upgrade_labels_known_gateway_urls_and_preserves_old_quote_for_review(self):
        fixture(self)
        order=draft_order(self.user,{str(self.variant.pk):1},'PICKUP')
        checkout(self.user,order,'migration')
        invoice=Invoice.objects.get(order=order)
        executor=MigrationExecutor(connection)
        latest=executor.loader.graph.leaf_nodes()
        old=[('billing','0003_initial'),('delivery','0004_routeestimate')]
        try:
            executor.migrate(old)
            apps=executor.loader.project_state(old).apps
            Attempt=apps.get_model('billing','PaymentAttempt')
            Quote=apps.get_model('delivery','ShippingQuote')
            ids=[]
            for i,(provider,url) in enumerate([('MIDTRANS','https://app.sandbox.midtrans.com/snap/test'),('MIDTRANS','https://app.midtrans.com/snap/test'),('MIDTRANS',''),('MOCK','')]):
                ids.append(Attempt.objects.create(invoice_id=invoice.pk,provider=provider,provider_order_id=f'legacy-{i}',request_key=f'legacy-{i}',status='PENDING',session_url=url).pk)
            quote=Quote.objects.create(order_id=order.pk)
            executor=MigrationExecutor(connection);executor.migrate(latest)
            apps=executor.loader.project_state(latest).apps
            Attempt=apps.get_model('billing','PaymentAttempt');Quote=apps.get_model('delivery','ShippingQuote')
            self.assertEqual([Attempt.objects.get(pk=pk).environment for pk in ids],['midtrans_sandbox','midtrans_live','','mock'])
            self.assertEqual(Quote.objects.get(pk=quote.pk).origin_fingerprint,'')
            self.assertEqual(Invoice.objects.get(pk=invoice.pk).status,'UNPAID')
        finally:
            MigrationExecutor(connection).migrate(latest)
