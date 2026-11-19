"""Guard own-account changes and the shop-local opening/closing boundary."""

from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch
from django.test import TestCase, override_settings
from core.models import StoreSettings
from core.opening import opening_summary
from .factories import fixture, login_as


@override_settings(REQUIRE_STAFF_MFA=False)
class CompactAccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def test_every_staff_role_can_update_own_name_without_changing_privileges(self):
        for role in ("SUPER_ADMIN", "ADMIN", "OWNER", "DOCTOR", "GROOMER", "CARETAKER"):
            with self.subTest(role=role):
                user = self.users[role]
                email, staff, superuser = user.email, user.is_staff, user.is_superuser
                login_as(self.client, user)
                self.assertContains(self.client.get("/akun/profil/"), "Profil saya")
                response = self.client.post(
                    "/akun/profil/",
                    {
                        "full_name": "Nama " + role,
                        "email": "forged@example.test",
                        "is_superuser": True,
                        "is_staff": True,
                    },
                )
                self.assertRedirects(response, "/akun/profil/")
                user.refresh_from_db()
                self.assertEqual(user.full_name, "Nama " + role)
                self.assertEqual(
                    (user.email, user.is_staff, user.is_superuser), (email, staff, superuser)
                )
                self.assertFalse(user.groups.filter(name="CUSTOMER").exists())
        self.assertEqual(self.client.post("/pengaturan/toko/", {}).status_code, 403)

    def test_staff_profile_keeps_mandatory_mfa_and_customer_profile_routes(self):
        login_as(self.client, self.users["DOCTOR"])
        with override_settings(REQUIRE_STAFF_MFA=True):
            response = self.client.post("/akun/profil/", {"full_name": "Changed"})
            self.assertRedirects(response, "/keamanan/")
        self.users["DOCTOR"].refresh_from_db()
        self.assertEqual(self.users["DOCTOR"].full_name, "DOCTOR")
        login_as(self.client, self.user)
        self.assertRedirects(self.client.get("/akun/profil/"), "/profil/")
        self.assertEqual(self.client.get("/alamat/").status_code, 200)
        login_as(self.client, self.users["DOCTOR"])
        self.assertEqual(self.client.get("/alamat/").status_code, 403)
        self.assertNotContains(self.client.get("/keamanan/"), 'href="/alamat/"')

    def test_shop_local_open_close_and_published_changes(self):
        store = StoreSettings.objects.get(pk=1)
        store.opening_hours = {"3": ["08:00", "17:00"], "4": ["09:00", "18:00"]}
        store.save()
        with patch(
            "core.opening.timezone.now",
            return_value=datetime(2026, 11, 19, 0, 59, tzinfo=dt_timezone.utc),
        ):
            status = opening_summary(store)
            self.assertFalse(status["is_open"])
            self.assertEqual(status["next_opening"], "Buka hari ini pukul 08:00")
        with patch(
            "core.opening.timezone.now",
            return_value=datetime(2026, 11, 19, 1, 0, tzinfo=dt_timezone.utc),
        ):
            self.assertTrue(opening_summary(store)["is_open"])
        with patch(
            "core.opening.timezone.now",
            return_value=datetime(2026, 11, 19, 10, 0, tzinfo=dt_timezone.utc),
        ):
            status = opening_summary(store)
            self.assertFalse(status["is_open"])
            self.assertEqual(status["next_opening"], "Buka besok pukul 09:00")
        store.opening_hours = {"3": ["18:00", "20:00"]}
        store.save()
        with patch(
            "core.opening.timezone.now",
            return_value=datetime(2026, 11, 19, 10, 0, tzinfo=dt_timezone.utc),
        ):
            response = self.client.get("/katalog/")
            self.assertContains(response, "Buka hari ini pukul 18:00")
            self.assertContains(response, "18:00–20:00")
        store.opening_hours = None
        self.assertFalse(opening_summary(store)["published"])
