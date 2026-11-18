"""Generate local secrets once. Never overwrite a developer's existing environment."""

import secrets
from pathlib import Path
import base64

root = Path(__file__).resolve().parent.parent
target = root / ".env"
if target.exists():
    raise SystemExit(".env sudah ada; tidak ditimpa.")
password = secrets.token_urlsafe(24)
replacements = {
    "SECRET_KEY=": "SECRET_KEY=" + secrets.token_urlsafe(64),
    "DATA_ENCRYPTION_KEY=": "DATA_ENCRYPTION_KEY="
    + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "POSTGRES_PASSWORD=": "POSTGRES_PASSWORD=" + password,
    "DATABASE_URL=": f"DATABASE_URL=postgresql://sinau:{password}@db:5432/sinau",
    "DEMO_PASSWORD=": "DEMO_PASSWORD=" + secrets.token_urlsafe(18),
}
target.write_text(
    "\n".join(
        replacements.get(line, line) for line in (root / ".env.example").read_text().splitlines()
    )
    + "\n"
)
target.chmod(0o600)
print(".env dibuat. Password akun demo ada pada DEMO_PASSWORD. Jangan commit file ini.")
