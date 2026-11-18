from django.test import TestCase, override_settings
from billing.models import Invoice
from .factories import fixture, login_as, booking


class PageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def test_public_pages_and_guest_booking_gate(self):
        for url in [
            "/",
            "/katalog/",
            "/layanan/",
            "/kontak/",
            "/ulasan/",
            "/privasi/",
            "/login/",
            "/register/",
            "/forgot-password/",
            "/keranjang/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.get("/booking/baru/")
        self.assertRedirects(response, "/login/?next=/booking/baru/", fetch_redirect_response=False)

    def test_customer_pages_render_and_have_no_back_to_website(self):
        login_as(self.client, self.user)
        for url in [
            "/dashboard/",
            "/hewan/",
            "/alamat/",
            "/profil/",
            "/booking/",
            "/booking/baru/",
            "/pesanan/",
            "/checkout/",
            "/keamanan/",
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "Kembali ke website")

    def test_staff_role_dashboards_render_and_admin_pages_are_scoped(self):
        slugs = {
            "SUPER_ADMIN": "super-admin",
            "OWNER": "owner",
            "ADMIN": "admin",
            "DOCTOR": "dokter",
            "GROOMER": "grooming",
            "CARETAKER": "penitipan",
        }
        for role, slug in slugs.items():
            login_as(self.client, self.users[role])
            with self.subTest(role=role):
                self.assertEqual(self.client.get("/staf/" + slug + "/").status_code, 200)
        login_as(self.client, self.admin)
        for url in [
            "/operasional/stok/",
            "/operasional/laporan/",
            "/operasional/ulasan/",
            "/operasional/pelanggan/",
            "/operasional/kasir/",
            "/operasional/kapasitas/",
            "/pengiriman/",
            "/management/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        login_as(self.client, self.users["SUPER_ADMIN"])
        self.assertEqual(self.client.get("/operasional/akun/").status_code, 200)
        self.assertEqual(self.client.get("/operasional/audit/").status_code, 200)

    def test_object_level_booking_and_invoice_scoping(self):
        bk = booking(self)
        invoice = Invoice.objects.get(booking=bk)
        login_as(self.client, self.user)
        self.assertEqual(self.client.get(f"/booking/{bk.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"/tagihan/{invoice.pk}/").status_code, 200)
        login_as(self.client, self.other)
        self.assertEqual(self.client.get(f"/booking/{bk.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/tagihan/{invoice.pk}/").status_code, 404)

    def test_catalog_intersects_species_and_category(self):
        response = self.client.get("/katalog/?species=DOG&category=FOOD")
        self.assertNotContains(response, "Cat food")
        self.assertContains(response, "Kategori disesuaikan dengan jenis hewan")
        self.assertContains(self.client.get("/katalog/?species=CAT&category=FOOD"), "Cat food")

    def test_security_headers_no_private_media_route(self):
        login_as(self.client, self.user)
        response = self.client.get("/dashboard/")
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("object-src 'none'", response["Content-Security-Policy"])
        self.assertIn("https://accounts.google.com", response["Content-Security-Policy"])
        self.assertIn("https://app.sandbox.midtrans.com", response["Content-Security-Policy"])
        self.assertEqual(self.client.get("/media/private.pdf").status_code, 404)

    def test_invalid_boarding_document_does_not_leave_a_booking(self):
        import uuid
        from datetime import timedelta
        from django.core.files.uploadedfile import SimpleUploadedFile
        from scheduling.models import Booking

        login_as(self.client, self.user)
        response = self.client.post(
            "/booking/baru/",
            {
                "pet": str(self.pet.pk),
                "package": str(self.packages["BOARDING"].pk),
                "starts_at": self.start.isoformat(),
                "checkout_at": (self.start + timedelta(days=2)).isoformat(),
                "emergency_contact": str(self.contact.pk),
                "key": str(uuid.uuid4()),
                "document": SimpleUploadedFile(
                    "health.pdf", b"invalid pdf payload", content_type="application/pdf"
                ),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Berkas tidak dapat diproses")
        self.assertEqual(Booking.objects.count(), 0)
