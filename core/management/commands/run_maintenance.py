from django.core.management.base import BaseCommand
from core.tasks import maintenance


class Command(BaseCommand):
    help = "Run one maintenance cycle without Redis; useful for local manual tests."

    def handle(self, *args, **options):
        maintenance()
        self.stdout.write(
            self.style.SUCCESS("Expiry, reminder, outbox, dan rekonsiliasi diproses.")
        )
