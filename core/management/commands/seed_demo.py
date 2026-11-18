"""Idempotent local-only fixtures. No universal password is shipped with the application."""

import os
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from accounts.models import User
from accounts.permissions import ROLES
from catalog.models import Species, Category, Product, ProductSpecies, ProductVariant
from customers.models import Customer, Pet, Address, EmergencyContact
from inventory.models import InventoryBatch, StockMovement
from core.models import StoreSettings
from scheduling.models import (
    Service,
    ServicePackage,
    PackageSpecies,
    Resource,
    StaffShift,
    PackageResource,
)
from boarding.models import BoardingUnit
from delivery.models import DeliveryPolicy, DeliveryWindow


class Command(BaseCommand):
    help = "Create illustrative local data and one account per role, without overwriting existing data."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.LOCAL_MODE:
            raise CommandError("Data demo hanya dapat dibuat pada DEPLOYMENT_MODE=local.")
        password = os.environ.get("DEMO_PASSWORD", "")
        if len(password) < 16:
            raise CommandError("Isi DEMO_PASSWORD acak minimal 16 karakter di .env.")
        users = {}
        for role in ROLES:
            group, _ = Group.objects.get_or_create(name=role)
            user, created = User.objects.get_or_create(
                email=f"{role.lower()}@sinau.test",
                defaults={
                    "full_name": "Demo " + ROLES[role][0],
                    "email_verified_at": timezone.now(),
                    "is_staff": role in {"SUPER_ADMIN", "ADMIN", "OWNER"},
                    "can_deliver": role == "ADMIN",
                },
            )
            if created:
                user.set_password(password)
                user.save()
                user.groups.add(group)
            users[role] = user
        customer, _ = Customer.objects.get_or_create(
            user=users["CUSTOMER"],
            defaults={
                "name": "Ayu Pramesti",
                "contact_email": users["CUSTOMER"].email,
                "phone": "6281200000000",
                "origin": "DEMO",
                "linked_at": timezone.now(),
            },
        )
        cat, _ = Species.objects.get_or_create(code="CAT", defaults={"name": "Kucing"})
        dog, _ = Species.objects.get_or_create(code="DOG", defaults={"name": "Anjing"})
        for name, species, breed, weight in [
            ("Milo", cat, "Domestic shorthair", 4.2),
            ("Boba", dog, "French bulldog", 8.5),
        ]:
            Pet.objects.get_or_create(
                customer=customer,
                name=name,
                defaults={"species": species, "breed": breed, "sex": "MALE", "weight_kg": weight},
            )
        Address.objects.get_or_create(
            customer=customer,
            label="Alamat contoh",
            defaults={
                "recipient_name": "Ayu Pramesti",
                "recipient_phone": "6281200000000",
                "address_line": "Alamat ilustrasi untuk pengujian, bukan alamat pelanggan nyata",
                "province": "DKI Jakarta",
                "city": "Jakarta Selatan",
                "district": "Kebayoran Baru",
                "postal_code": "12120",
                "latitude": -6.244200,
                "longitude": 106.783500,
                "is_default": True,
            },
        )
        EmergencyContact.objects.get_or_create(
            customer=customer,
            name="Kontak contoh",
            defaults={
                "relationship": "Keluarga",
                "phone": "6281200000001",
                "contact_consent": True,
            },
        )
        opening = {str(day): ["08:00", "20:00"] for day in range(7)}
        StoreSettings.objects.get_or_create(
            pk=1,
            defaults={
                "business_name": "Sinau Satwa",
                "address": "Alamat resmi menunggu data pemilik usaha. Koordinat lokal adalah ilustrasi.",
                "latitude": -6.225300,
                "longitude": 106.799400,
                "cs_whatsapp": "",
                "timezone": "Asia/Jakarta",
                "opening_hours": opening,
                "public_contact_ready": False,
            },
        )
        food, _ = Category.objects.get_or_create(code="FOOD", defaults={"name": "Makanan"})
        care, _ = Category.objects.get_or_create(code="CARE", defaults={"name": "Perawatan"})
        catalog = [
            (
                "SS-CAT-01",
                "Daily Balance",
                "Adult cat · 1 kg",
                cat,
                food,
                89000,
                1000,
                "images/product-cat.svg",
            ),
            (
                "SS-CAT-02",
                "Gentle Wet Food",
                "Tuna · 85 g",
                cat,
                food,
                16000,
                85,
                "images/product-wet.svg",
            ),
            (
                "SS-DOG-01",
                "Active Companion",
                "Adult dog · 1 kg",
                dog,
                food,
                95000,
                1000,
                "images/product-dog.svg",
            ),
            (
                "SS-CARE-01",
                "Soft Coat",
                "Shampoo · 250 ml",
                dog,
                care,
                65000,
                300,
                "images/product-shampoo.svg",
            ),
        ]
        for sku, name, label, species, category, price, weight, image in catalog:
            product, _ = Product.objects.get_or_create(
                name=name,
                defaults={
                    "category": category,
                    "description": "Produk ilustrasi untuk pengujian katalog. Harga dan ketersediaan dapat dikelola melalui data master.",
                },
            )
            ProductSpecies.objects.get_or_create(product=product, species=species)
            variant, _ = ProductVariant.objects.get_or_create(
                sku=sku,
                defaults={
                    "product": product,
                    "label": label,
                    "price_rp": price,
                    "weight_g": weight,
                    "length_cm": 20,
                    "width_cm": 12,
                    "height_cm": 8,
                    "tracks_expiry": True,
                    "image_path": image,
                },
            )
            batch, created = InventoryBatch.objects.get_or_create(
                variant=variant,
                batch_code="DEMO-01",
                defaults={"expires_on": timezone.localdate() + timedelta(days=365), "on_hand": 25},
            )
            if created:
                StockMovement.objects.create(
                    batch=batch,
                    quantity_delta=25,
                    kind="RECEIPT",
                    reason="Saldo awal data demo",
                    operation_key=f"seed:{batch.pk}",
                )
        for kind, label, price, duration, staff_role in [
            ("VET", "Konsultasi dokter", 120000, 30, "DOCTOR"),
            ("GROOMING", "Grooming menyeluruh", 95000, 60, "GROOMER"),
            ("BOARDING", "Comfort stay", None, None, None),
        ]:
            service, _ = Service.objects.get_or_create(
                code=kind, defaults={"name": label, "kind": kind}
            )
            package, _ = ServicePackage.objects.get_or_create(
                service=service,
                name=label,
                defaults={"price_rp": price, "duration_minutes": duration, "buffer_minutes": 15},
            )
            for species in (cat, dog):
                PackageSpecies.objects.get_or_create(package=package, species=species)
            if staff_role:
                resource, _ = Resource.objects.get_or_create(
                    code=staff_role,
                    defaults={
                        "kind": "STAFF",
                        "staff_user": users[staff_role],
                        "name": users[staff_role].full_name,
                    },
                )
                PackageResource.objects.get_or_create(
                    package=package, resource=resource, defaults={"pool": "STAFF"}
                )
                for day in range(31):
                    date = timezone.localdate() + timedelta(days=day)
                    start = timezone.make_aware(
                        timezone.datetime.combine(date, timezone.datetime.min.time()).replace(
                            hour=8
                        )
                    )
                    StaffShift.objects.get_or_create(
                        resource=resource,
                        starts_at=start,
                        defaults={"ends_at": start + timedelta(hours=12), "is_available": True},
                    )
            if kind == "GROOMING":
                station, _ = Resource.objects.get_or_create(
                    code="GROOM-STATION-01",
                    defaults={"kind": "STATION", "name": "Meja grooming 01"},
                )
                PackageResource.objects.get_or_create(
                    package=package, resource=station, defaults={"pool": "STATION"}
                )
        for species, label in [(cat, "Kucing"), (dog, "Anjing")]:
            for number in (1, 2):
                resource, _ = Resource.objects.get_or_create(
                    code=f"ROOM-{species.code}-{number}",
                    defaults={"kind": "BOARDING_UNIT", "name": f"Comfort {label} {number:02}"},
                )
                BoardingUnit.objects.get_or_create(
                    resource=resource,
                    defaults={
                        "species": species,
                        "category": "Comfort",
                        "nightly_rate_rp": 125000,
                        "cleaning_minutes": 60,
                    },
                )
        DeliveryPolicy.objects.get_or_create(
            pk=1,
            defaults={
                "internal_enabled": True,
                "max_route_m": 5000,
                "base_fee_rp": 5000,
                "per_km_fee_rp": 2000,
                "max_weight_g": 15000,
                "max_length_cm": 60,
                "max_width_cm": 50,
                "max_height_cm": 60,
                "packaging_weight_g": 100,
                "travel_mode": "DRIVE",
                "service_hours": opening,
                "version": 1,
            },
        )
        for day in range(1, 15):
            date = timezone.localdate() + timedelta(days=day)
            for hour in (10, 15):
                start = timezone.make_aware(
                    timezone.datetime.combine(date, timezone.datetime.min.time()).replace(hour=hour)
                )
                DeliveryWindow.objects.get_or_create(
                    starts_at=start,
                    defaults={"ends_at": start + timedelta(hours=2), "max_orders": 3},
                )
        self.stdout.write(
            self.style.SUCCESS(
                "Data demo tersedia. Akun: customer/admin/doctor/groomer/caretaker/owner/super_admin@sinau.test. Password: lihat DEMO_PASSWORD pada .env."
            )
        )
