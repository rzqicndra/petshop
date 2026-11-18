from pathlib import Path
import subprocess
import sys
import tempfile
from django.conf import settings
from django.test import SimpleTestCase


class UpdateInstallerTests(SimpleTestCase):
    def target(self, root):
        (root / "manage.py").write_text("# Existing installation\n")
        (root / "config").mkdir()
        (root / "config/settings.py").write_text("# Old settings\n")
        (root / "var").mkdir()
        (root / "var/customer-upload.txt").write_text("KEEP CUSTOMER DATA")
        original = b"SECRET_KEY=KEEP-SECRET\nEMAIL_HOST_PASSWORD=KEEP-SMTP\nAPP_URL=http://localhost:18000\n"
        (root / ".env").write_bytes(original)
        return original

    def run_update(self, root, dry=False):
        command = [
            sys.executable,
            str(settings.BASE_DIR / "scripts/install_update.py"),
            "--target",
            str(root),
        ]
        if dry:
            command.append("--dry-run")
        return subprocess.run(command, check=True, capture_output=True, text=True)

    def test_update_preserves_existing_secrets_and_runtime_files_and_backs_up_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.target(root)
            output = self.run_update(root)
            self.assertTrue((root / ".env").read_bytes().startswith(original))
            self.assertIn("PUBLIC_WEBHOOK_BASE_URL=", (root / ".env").read_text())
            self.assertEqual((root / "var/customer-upload.txt").read_text(), "KEEP CUSTOMER DATA")
            backups = list((root / "var/update-backups").glob("*/config/settings.py"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), "# Old settings\n")
            self.assertNotIn("KEEP-SECRET", output.stdout)
            self.assertNotIn("KEEP-SMTP", output.stdout)

    def test_dry_run_does_not_change_files_or_create_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.target(root)
            self.run_update(root, dry=True)
            self.assertEqual((root / ".env").read_bytes(), original)
            self.assertEqual((root / "config/settings.py").read_text(), "# Old settings\n")
            self.assertFalse((root / "var/update-backups").exists())

    def test_google_mode_migrates_without_replacing_existing_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.target(root) + b"ROUTES_MODE=google\nGOOGLE_CLIENT_SECRET=KEEP-OAUTH\n"
            (root / ".env").write_bytes(original)
            self.run_update(root)
            updated = (root / ".env").read_text()
            self.assertIn("ROUTES_MODE=openrouteservice", updated)
            self.assertNotIn("ROUTES_MODE=google", updated)
            self.assertIn("EMAIL_HOST_PASSWORD=KEEP-SMTP", updated)
            self.assertIn("GOOGLE_CLIENT_SECRET=KEEP-OAUTH", updated)
            self.assertIn("ORS_API_KEY=", updated)

    def test_update_preserves_chosen_route_mode_and_includes_audit_migrations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.target(root) + b"ROUTES_MODE=mock\nDEBUG=true\n"
            (root / ".env").write_bytes(original)
            self.run_update(root)
            self.assertTrue((root / ".env").read_bytes().startswith(original))
            self.assertTrue((root / "billing/migrations/0004_payment_environment.py").is_file())
            self.assertTrue((root / "delivery/migrations/0005_quote_origin.py").is_file())
            self.assertTrue((root / "config/debug_policy.py").is_file())
