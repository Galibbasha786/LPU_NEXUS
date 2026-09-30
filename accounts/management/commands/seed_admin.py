# accounts/management/commands/seed_admin.py
from django.core.management.base import BaseCommand
from accounts.mongo_auth import create_admin_if_missing, FIXED_ADMIN_EMAIL


class Command(BaseCommand):
    help = "Ensure the single fixed admin account exists."

    def handle(self, *args, **options):
        user = create_admin_if_missing(password='admin123')
        if user:
            self.stdout.write(self.style.SUCCESS(
                f"[OK] Admin created: {FIXED_ADMIN_EMAIL} / admin123"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"[WARNING] Admin already exists: {FIXED_ADMIN_EMAIL}"
            ))
        self.stdout.write(self.style.SUCCESS(
            "\n[NOTICE] Login and change the password immediately."
        ))