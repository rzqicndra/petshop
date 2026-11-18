from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from accounts.models import User
from accounts.permissions import ROLES
from accounts.services import issue_otp
from core.services import commerce_transaction, audit
from core.models import StoreSettings
from delivery.models import DeliveryPolicy


class Command(BaseCommand):
    help = "Create the first business Super Admin with an email OTP invitation. No shared password."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", required=True)

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        validate_email(email)
        with commerce_transaction():
            if User.objects.filter(groups__name="SUPER_ADMIN").exists():
                raise CommandError(
                    "Super Admin sudah tersedia. Kelola akun melalui portal yang ada."
                )
            if User.objects.filter(email__iexact=email).exists():
                raise CommandError("Email sudah digunakan. Provisioning tidak menimpa akun lama.")
            for role in ROLES:
                Group.objects.get_or_create(name=role)
            user = User.objects.create_user(
                email=email, full_name=options["name"][:150], is_staff=True
            )
            user.groups.add(Group.objects.get(name="SUPER_ADMIN"))
            StoreSettings.objects.get_or_create(
                pk=1, defaults={"business_name": "Sinau Satwa", "timezone": "Asia/Jakarta"}
            )
            DeliveryPolicy.objects.get_or_create(
                pk=1,
                defaults={
                    "internal_enabled": False,
                    "max_route_m": 1,
                    "max_weight_g": 1,
                    "max_length_cm": 1,
                    "max_width_cm": 1,
                    "max_height_cm": 1,
                    "travel_mode": "DRIVE",
                    "version": 1,
                },
            )
            issue_otp(user, "INVITE")
            audit(None, "account.initial_super_admin", user)
        self.stdout.write(
            self.style.SUCCESS(
                "Super Admin dibuat. Worker mengirim undangan OTP ke email yang ditentukan."
            )
        )
