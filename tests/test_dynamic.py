"""End-to-end regressions for managed content, catalog publishing and personal data."""

import io
import tempfile
from pathlib import Path
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from core.models import SiteContent, StoreSettings, PrivateFile
from core.files import store_upload
from catalog.models import Product, ProductVariant, ProductSpecies, Category
from customers.models import EmergencyContact
from scheduling.forms import BookingForm
from inventory.models import StockMovement
from inventory.services import available
from .factories import fixture, login_as


@override_settings(PAYMENT_MODE="mock", ROUTES_MODE="mock", SHIPPING_MODE="mock")
class DynamicTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def setUp(self):
        self.files = tempfile.TemporaryDirectory()
        self.storage = override_settings(PRIVATE_ROOT=Path(self.files.name))
        self.storage.enable()
        self.addCleanup(self.storage.disable)
        self.addCleanup(self.files.cleanup)

    def photo(self):
        out = io.BytesIO()
        Image.new("RGB", (40, 40), "orange").save(out, "PNG")
        return SimpleUploadedFile("photo.png", out.getvalue(), content_type="image/png")

    def product_data(self, **overrides):
        values = dict(
            name="Produk baru",
            category=self.product.category_id,
            description="Deskripsi produk asli",
            is_active="on",
            sku="SKU-BARU",
            variant_label="500 gram",
            price_rp=45000,
            weight_g=500,
            length_cm=12,
            width_cm=10,
            height_cm=7,
            variant_active="on",
            species=[str(self.cat.pk)],
            initial_stock=8,
        )
        values.update(overrides)
        return values

    def test_create_product_publishes_variant_photo_species_and_initial_stock(self):
        login_as(self.client, self.admin)
        result = self.client.post(
            "/pengaturan/produk/", self.product_data(photo_upload=self.photo())
        )
        self.assertEqual(result.status_code, 302)
        variant = ProductVariant.objects.get(sku="SKU-BARU")
        self.assertEqual(available(variant), 8)
        self.assertEqual(StockMovement.objects.get(batch__variant=variant).quantity_delta, 8)
        self.assertTrue(
            ProductSpecies.objects.filter(product=variant.product, species=self.cat).exists()
        )
        self.client.logout()
        response = self.client.get("/katalog/?species=CAT")
        self.assertContains(response, "Produk baru")
        self.assertContains(response, "Rp45.000")
        self.assertEqual(self.client.get(f"/produk/foto/{variant.pk}/").status_code, 200)
        self.assertContains(self.client.get(f"/produk/{variant.pk}/"), "Deskripsi produk asli")
        self.assertNotContains(self.client.get("/katalog/?species=DOG"), "Produk baru")

    def test_duplicate_sku_does_not_create_product_or_stock(self):
        login_as(self.client, self.admin)
        response = self.client.post("/pengaturan/produk/", self.product_data(sku=self.variant.sku))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SKU sudah digunakan")
        self.assertFalse(Product.objects.filter(name="Produk baru").exists())

    def test_edit_product_updates_existing_variant_without_recreating_stock(self):
        login_as(self.client, self.admin)
        self.client.post("/pengaturan/produk/", self.product_data())
        variant = ProductVariant.objects.get(sku="SKU-BARU")
        response = self.client.post(
            f"/pengaturan/produk/{variant.product_id}/",
            self.product_data(name="Nama baru", price_rp=55000, initial_stock=999),
        )
        self.assertEqual(response.status_code, 302)
        variant.refresh_from_db()
        self.assertEqual(variant.price_rp, 55000)
        self.assertEqual(available(variant), 8)
        self.assertEqual(ProductVariant.objects.filter(product=variant.product).count(), 1)
        self.assertContains(self.client.get("/katalog/"), "Nama baru")

    def test_inactive_product_and_inactive_category_not_published(self):
        login_as(self.client, self.admin)
        values = self.product_data()
        values.pop("is_active")
        self.client.post("/pengaturan/produk/", values)
        self.assertNotContains(self.client.get("/katalog/"), "Produk baru")
        category = self.product.category
        category.is_active = False
        category.save()
        self.assertNotContains(self.client.get("/katalog/"), self.product.name)
        self.assertEqual(self.client.get(f"/produk/{self.variant.pk}/").status_code, 404)

    def test_zero_stock_product_still_visible_but_cannot_add_from_card(self):
        login_as(self.client, self.admin)
        self.client.post("/pengaturan/produk/", self.product_data(initial_stock=0))
        self.assertContains(self.client.get("/katalog/"), "Produk baru")
        self.assertContains(self.client.get("/katalog/"), "Stok habis")

    def test_unrestricted_product_visible_under_every_active_species(self):
        ProductSpecies.objects.filter(product=self.product).delete()
        self.assertContains(self.client.get("/katalog/?species=DOG"), self.product.name)

    def test_catalog_sort_and_pagination_preserve_filters(self):
        for n in range(13):
            ProductVariant.objects.create(
                product=self.product,
                sku=f"MORE-{n}",
                label=str(n),
                price_rp=10000 + n,
                weight_g=100,
                length_cm=1,
                width_cm=1,
                height_cm=1,
            )
        response = self.client.get("/katalog/?species=CAT&sort=price_desc&q=Cat")
        self.assertEqual(response.context["page"][0].pk, self.variant.pk)
        self.assertContains(response, "sort=price_desc")
        self.assertContains(response, "species=CAT")

    def test_product_card_detail_and_customer_staff_shells_differ(self):
        login_as(self.client, self.user)
        self.assertContains(self.client.get("/dashboard/"), "customer-shell")
        self.assertContains(self.client.get("/katalog/"), f"/produk/{self.variant.pk}/")
        login_as(self.client, self.admin)
        response = self.client.get("/staf/admin/")
        self.assertContains(response, "staff-shell")
        self.assertContains(response, "ops-metrics")
        self.assertNotContains(response, "Tambah ke keranjang")

    def test_contact_archive_is_owned_post_only_and_not_bookable(self):
        contact = EmergencyContact.objects.create(
            customer=self.customer, name="Kontak", phone="628123456789", contact_consent=True
        )
        login_as(self.client, self.other)
        self.assertEqual(self.client.post(f"/profil/kontak/{contact.pk}/hapus/").status_code, 404)
        login_as(self.client, self.user)
        self.assertEqual(self.client.get(f"/profil/kontak/{contact.pk}/hapus/").status_code, 405)
        self.assertEqual(self.client.post(f"/profil/kontak/{contact.pk}/hapus/").status_code, 302)
        contact.refresh_from_db()
        self.assertFalse(contact.is_active)
        form = BookingForm(customer=self.customer)
        self.assertFalse(form.fields["emergency_contact"].queryset.filter(pk=contact.pk).exists())
        self.assertNotContains(self.client.get("/profil/"), f"/profil/kontak/{contact.pk}/hapus/")
        self.assertEqual(self.client.post(f"/profil/kontak/{contact.pk}/hapus/").status_code, 404)

    def content(self):
        content, _ = SiteContent.objects.get_or_create(key="shop", defaults={"heading": "Awal"})
        return content

    def test_cms_edit_escapes_html_and_is_immediately_visible(self):
        item = self.content()
        login_as(self.client, self.admin)
        response = self.client.post(
            f"/pengaturan/konten/{item.pk}/",
            dict(
                key="shop",
                heading="Judul katalog baru",
                body="<script>alert(1)</script>",
                overline="Pilihan toko",
                is_active="on",
                fallback_image="",
            ),
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/katalog/")
        self.assertContains(response, "Judul katalog baru")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_cms_image_public_only_while_referenced_and_active(self):
        item = self.content()
        login_as(self.client, self.admin)
        result = self.client.post(
            f"/pengaturan/konten/{item.pk}/",
            dict(
                key="shop",
                heading="Foto toko",
                body="",
                overline="",
                fallback_image="",
                is_active="on",
                photo_upload=self.photo(),
            ),
        )
        self.assertEqual(result.status_code, 302)
        item.refresh_from_db()
        self.assertIsNotNone(item.image_file)
        self.client.logout()
        self.assertEqual(self.client.get(f"/media/website/{item.image_file_id}/").status_code, 200)
        item.is_active = False
        item.save()
        self.assertEqual(self.client.get(f"/media/website/{item.image_file_id}/").status_code, 404)

    def test_cms_does_not_accept_external_or_script_cta_route(self):
        item = self.content()
        login_as(self.client, self.admin)
        response = self.client.post(
            f"/pengaturan/konten/{item.pk}/",
            dict(key="shop", heading="Attempt", link_route="javascript:alert(1)", is_active="on"),
        )
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertNotEqual(item.heading, "Attempt")

    def test_owner_read_only_and_customer_cannot_edit_content(self):
        item = self.content()
        for user in [self.user, self.users["OWNER"]]:
            login_as(self.client, user)
            self.assertEqual(
                self.client.post(
                    f"/pengaturan/konten/{item.pk}/", dict(key="shop", heading="Hacked")
                ).status_code,
                403,
            )
        item.refresh_from_db()
        self.assertNotEqual(item.heading, "Hacked")

    def test_brand_logo_and_copy_apply_to_header_footer_and_auth(self):
        logo = store_upload(self.admin, self.photo(), "SITE_PUBLIC")
        StoreSettings.objects.filter(pk=1).update(
            business_name="Toko Asli",
            tagline="Tagline baru",
            footer_text="Footer baru",
            logo_file=logo,
        )
        response = self.client.get("/")
        self.assertContains(response, "Toko Asli")
        self.assertContains(response, "Footer baru")
        self.assertContains(response, f"/media/website/{logo.pk}/")
        self.assertEqual(self.client.get(f"/media/website/{logo.pk}/").status_code, 200)
        self.assertContains(self.client.get("/login/"), "Toko Asli")

    def test_private_health_document_is_not_a_public_cms_asset(self):
        private = store_upload(self.admin, self.photo(), "BOARDING_INTAKE")
        self.assertEqual(self.client.get(f"/media/website/{private.pk}/").status_code, 404)

    def test_invalid_image_rejected_without_creating_product(self):
        login_as(self.client, self.admin)
        bad = SimpleUploadedFile(
            "logo.svg", b'<svg onload="alert(1)"></svg>', content_type="image/svg+xml"
        )
        self.assertEqual(
            self.client.post(
                "/pengaturan/produk/", self.product_data(photo_upload=bad)
            ).status_code,
            200,
        )
        self.assertFalse(Product.objects.filter(name="Produk baru").exists())

    def test_master_explains_incomplete_legacy_product(self):
        Product.objects.create(name="Produk tanpa varian", category=self.product.category)
        login_as(self.client, self.admin)
        response = self.client.get("/pengaturan/produk/")
        self.assertContains(response, "Lengkapi varian & harga")
        self.assertContains(response, "Tayang di katalog")

    def test_disabled_auth_art_has_no_empty_image_request(self):
        SiteContent.objects.filter(key="auth").update(is_active=False)
        response = self.client.get("/login/")
        self.assertContains(response, "auth-plain")
        self.assertNotContains(response, 'src=""')

    def test_cms_button_requires_label_and_destination_together(self):
        item = self.content()
        login_as(self.client, self.admin)
        result = self.client.post(
            f"/pengaturan/konten/{item.pk}/",
            dict(key="shop", heading="New", button_label="Klik", link_route="", is_active="on"),
        )
        self.assertEqual(result.status_code, 200)
        item.refresh_from_db()
        self.assertNotEqual(item.heading, "New")

    def test_update_manifest_includes_dynamic_pages_and_migrations(self):
        import json
        from django.conf import settings

        files = set(
            json.loads((settings.BASE_DIR / "scripts/integration_update_files.json").read_text())
        )
        for name in [
            "catalog/editor.py",
            "static/css/dynamic.css",
            "static/js/select.js",
            "core/migrations/0004_initial_site_content.py",
            "customers/migrations/0003_emergencycontact_is_active.py",
            "templates/core/staff_dashboard.html",
            "templates/public/product_detail.html",
        ]:
            self.assertIn(name, files)
