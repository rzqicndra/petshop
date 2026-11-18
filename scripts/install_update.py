"""Apply the packaged integration revision to an existing checkout, preserving secrets/data."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile

NEW_ENV_DEFAULTS = {
    "PUBLIC_WEBHOOK_BASE_URL": "",
    "DEBUG": "false",
    "WEB_PORT": "18000",
    "MAILPIT_WEB_PORT": "18025",
    "TRUST_PROXY_HTTPS": "false",
    "EMAIL_TIMEOUT": "20",
    "MAP_PROVIDER": "leaflet",
    "MAP_TILE_URL": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "MAP_TILE_ATTRIBUTION": "© OpenStreetMap contributors",
    "ORS_API_KEY": "",
    "ORS_BASE_URL": "https://api.heigit.org",
    "ORS_REQUESTS_PER_MINUTE": "30",
    "ORS_REQUESTS_PER_DAY": "1500",
    "ORS_CACHE_SECONDS": "3600",
}


def atomic_write(destination, contents, mode=0o600):
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
        os.chmod(name, mode)
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent.parent
    target = args.target.resolve()
    if target == source or not (target / "manage.py").is_file():
        parser.error(
            "Target harus instalasi lama dengan manage.py, berbeda dari folder paket baru."
        )
    files = json.loads((source / "scripts/integration_update_files.json").read_text())
    changes = []
    for name in files:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name == ".env":
            parser.error("Manifest pembaruan tidak valid.")
        src, dst = source / relative, target / relative
        if not dst.resolve().is_relative_to(target):
            parser.error("Path target keluar dari instalasi.")
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            changes.append((name, src, dst))
            print("UPDATE:", name)
    env = target / ".env"
    original_env = env.read_bytes() if env.exists() else None
    additions = []
    revised_env = original_env
    if original_env is not None:
        # This release explicitly migrates mapping providers. Preserve all secrets.
        import re

        text = original_env.decode("utf-8-sig")
        text, count = re.subn(
            r"(?m)^(?:export\s+)?ROUTES_MODE\s*=\s*google\s*$", "ROUTES_MODE=openrouteservice", text
        )
        if not re.search(r"(?m)^(?:export\s+)?ROUTES_MODE\s*=", text):
            text += "\nROUTES_MODE=openrouteservice\n"
        revised_env = text.encode("utf-8")
        keys = set()
        for line in revised_env.decode("utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if "=" in line and not line.startswith("#"):
                keys.add(line.split("=", 1)[0].strip())
        additions = [f"{key}={value}" for key, value in NEW_ENV_DEFAULTS.items() if key not in keys]
    print("Setting baru yang ditambahkan:", len(additions), "(nilai lama dipertahankan)")
    print(
        "Provider peta dimigrasikan: ROUTES_MODE=openrouteservice; Google Login tetap dipertahankan."
    )
    if args.dry_run:
        return
    backup = target / "var/update-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup.mkdir(parents=True, mode=0o700)
    for name, src, dst in changes:
        if dst.exists():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, saved)
        mode = (dst.stat().st_mode & 0o777) if dst.exists() else 0o644
        atomic_write(dst, src.read_bytes(), mode)
    if additions or revised_env != original_env:
        atomic_write(backup / ".env", original_env)
        atomic_write(
            env,
            revised_env
            + b"\n# Integration update: missing settings only\n"
            + ("\n".join(additions) + "\n").encode(),
        )
    print("Selesai. Backup lokal:", backup)
    print(
        "Isi PUBLIC_WEBHOOK_BASE_URL dan kredensial yang belum ada. Jalankan ulang Docker Compose sesuai panduan."
    )


if __name__ == "__main__":
    main()
