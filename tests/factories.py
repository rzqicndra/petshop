"""Small deterministic domain fixtures, without a dependency on the demo seed command."""

from datetime import timedelta
from django.contrib.auth.models import Group
from django.utils import timezone
from accounts.models import User
from accounts.permissions import ROLES
from customers.models import Customer, Pet, Address, EmergencyContact
from catalog.models import Species, Category, Product, ProductSpecies, ProductVariant
from core.models import StoreSettings, PrivateFile
from inventory.models import InventoryBatch
from scheduling.models import (
    Service,
    ServicePackage,
    PackageSpecies,
    Resource,
    PackageResource,
    StaffShift,
)
from boarding.models import BoardingUnit, BoardingStay, BoardingIntakeFile
from delivery.models import DeliveryPolicy, DeliveryWindow


def fixture(cls):
    cls.users = {}
    for role in ROLES:
        group, _ = Group.objects.get_or_create(name=role)
        user = User.objects.create_user(
            email=role.lower() + "@example.test",
            full_name=role,
            email_verified_at=timezone.now(),
            is_staff=role in {"SUPER_ADMIN", "ADMIN", "OWNER"},
            can_deliver=role == "ADMIN",
        )
        user.groups.add(group)
        cls.users[role] = user
    cls.user = cls.users["CUSTOMER"]
    cls.admin = cls.users["ADMIN"]
    cls.other = User.objects.create_user(
        email="other@example.test", full_name="Other", email_verified_at=timezone.now()
    )
    cls.other.groups.add(Group.objects.get(name="CUSTOMER"))
    cls.customer = Customer.objects.create(
        user=cls.user, name="Ayu", contact_email=cls.user.email, origin="ONLINE"
    )
    cls.other_customer = Customer.objects.create(user=cls.other, name="Budi", origin="ONLINE")
    cls.cat = Species.objects.create(code="CAT", name="Kucing")
    cls.dog = Species.objects.create(code="DOG", name="Anjing")
    cls.pet = Pet.objects.create(customer=cls.customer, species=cls.cat, name="Milo", sex="MALE")
    cls.pet2 = Pet.objects.create(
        customer=cls.other_customer, species=cls.cat, name="Luna", sex="FEMALE"
    )
    category = Category.objects.create(code="FOOD", name="Makanan")
    cls.product = Product.objects.create(name="Cat food", category=category)
    ProductSpecies.objects.create(product=cls.product, species=cls.cat)
    cls.variant = ProductVariant.objects.create(
        product=cls.product,
        sku="TEST-CAT",
        label="1 kg",
        price_rp=89000,
        weight_g=1000,
        length_cm=20,
        width_cm=12,
        height_cm=8,
    )
    cls.batch = InventoryBatch.objects.create(
        variant=cls.variant,
        batch_code="B1",
        on_hand=10,
        expires_on=timezone.localdate() + timedelta(days=365),
    )
    cls.start = timezone.make_aware(
        timezone.datetime.combine(
            timezone.localdate() + timedelta(days=1), timezone.datetime.min.time()
        ).replace(hour=10)
    )
    opening = {str(day): ["08:00", "20:00"] for day in range(7)}
    StoreSettings.objects.create(
        pk=1,
        business_name="Sinau Satwa",
        latitude=-6.225300,
        longitude=106.799400,
        address="Test origin",
        timezone="Asia/Jakarta",
        opening_hours=opening,
    )
    cls.packages = {}
    for kind, role in [("VET", "DOCTOR"), ("GROOMING", "GROOMER"), ("BOARDING", None)]:
        service = Service.objects.create(code=kind, name=kind, kind=kind)
        package = ServicePackage.objects.create(
            service=service,
            name=kind,
            price_rp=100000 if role else None,
            duration_minutes=60 if role else None,
            buffer_minutes=15,
        )
        PackageSpecies.objects.create(package=package, species=cls.cat)
        cls.packages[kind] = package
        if role:
            resource = Resource.objects.create(
                code=role, kind="STAFF", staff_user=cls.users[role], name=role
            )
            PackageResource.objects.create(package=package, resource=resource, pool="STAFF")
            for day in range(6):
                start = cls.start.replace(hour=8) + timedelta(days=day)
                StaffShift.objects.create(
                    resource=resource,
                    starts_at=start,
                    ends_at=start + timedelta(hours=12),
                    is_available=True,
                )
    room = Resource.objects.create(code="ROOM", kind="BOARDING_UNIT", name="Comfort cat")
    cls.unit = BoardingUnit.objects.create(
        resource=room,
        species=cls.cat,
        category="Comfort",
        nightly_rate_rp=125000,
        cleaning_minutes=60,
    )
    cls.address = Address.objects.create(
        customer=cls.customer,
        label="Rumah",
        recipient_name="Ayu",
        recipient_phone="628123456789",
        address_line="Jalan contoh 1",
        province="DKI Jakarta",
        city="Jakarta",
        district="Kebayoran",
        postal_code="12120",
        latitude=-6.244200,
        longitude=106.783500,
    )
    cls.contact = EmergencyContact.objects.create(
        customer=cls.customer, name="Kontak", phone="628123456780", contact_consent=True
    )
    cls.policy = DeliveryPolicy.objects.create(
        pk=1,
        internal_enabled=True,
        max_route_m=5000,
        base_fee_rp=5000,
        per_km_fee_rp=2000,
        max_weight_g=15000,
        max_length_cm=60,
        max_width_cm=50,
        max_height_cm=60,
        packaging_weight_g=100,
        travel_mode="DRIVE",
        service_hours=opening,
        version=1,
    )
    cls.window = DeliveryWindow.objects.create(
        starts_at=cls.start, ends_at=cls.start + timedelta(hours=2), max_orders=1
    )


def login_as(client, user, role=None):
    client.force_login(user)
    session = client.session
    session["auth_version"] = user.auth_version
    session["workspace"] = role or user.groups.first().name
    session["mfa_verified"] = True
    session.save()


def booking(cls, kind="VET", pet=None, actor=None, start=None):
    import uuid
    from scheduling.services import create_booking

    return create_booking(
        actor or cls.user,
        pet or cls.pet,
        cls.packages[kind],
        start or cls.start,
        (start or cls.start) + timedelta(days=2) if kind == "BOARDING" else None,
        str(uuid.uuid4()),
        emergency=(
            {"name": "Contact", "phone": "628123456780", "consent": True}
            if kind == "BOARDING"
            else None
        ),
    )


def pay(invoice, transaction_id=None):
    import uuid
    from billing.models import PaymentAttempt
    from billing.services import apply_settled_payment

    attempt = PaymentAttempt.objects.create(
        invoice=invoice,
        provider="MOCK",
        provider_order_id=str(uuid.uuid4()),
        method="MOCK",
        status="PENDING",
        expected_amount_rp=invoice.total_rp,
        request_key=str(uuid.uuid4()),
        expires_at=invoice.expires_at,
    )
    return apply_settled_payment(attempt, transaction_id or str(uuid.uuid4()), invoice.total_rp)


def paid_stay(cls):
    from boarding.services import approve_stay
    from billing.models import Invoice

    bk = booking(cls, "BOARDING")
    stay = BoardingStay.objects.get(booking=bk)
    file = PrivateFile.objects.create(
        uploaded_by=cls.user,
        storage_key="tests/intake.pdf",
        original_name="health.pdf",
        mime_type="application/pdf",
        size_bytes=100,
        sha256="0" * 64,
        classification="BOARDING_INTAKE",
        scan_status="VALIDATED",
    )
    BoardingIntakeFile.objects.create(
        stay=stay,
        file=file,
        document_type="HEALTH",
        verified_by=cls.admin,
        verified_at=timezone.now(),
        valid_until=timezone.localdate(cls.start) + timedelta(days=30),
    )
    approve_stay(cls.admin, stay, cls.unit, cls.users["CARETAKER"])
    pay(Invoice.objects.get(booking=bk))
    stay.refresh_from_db()
    return stay
