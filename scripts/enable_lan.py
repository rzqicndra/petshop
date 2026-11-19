"""Configure this local checkout for a phone on the same private Wi-Fi network."""

import argparse
import ipaddress
import os
from pathlib import Path
import re
import socket
import tempfile

PRIVATE_NETWORKS = [
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
]


def private_ipv4(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.version == 4 and any(address in network for network in PRIVATE_NETWORKS)


def environment_values(content):
    values = {}
    for line in content.splitlines():
        found = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if found:
            values[found[1]] = found[2].strip("\"'")
    return values


def lan_environment(content, host):
    if not private_ipv4(host):
        raise ValueError("Gunakan IPv4 jaringan pribadi, misalnya 192.168.1.10.")
    old = environment_values(content)
    if old.get("DEPLOYMENT_MODE", "local") != "local":
        raise ValueError("Pengaturan ini hanya untuk DEPLOYMENT_MODE=local.")
    port = int(old.get("WEB_PORT") or 18000)
    if not 1 <= port <= 65535:
        raise ValueError("WEB_PORT harus berada antara 1 dan 65535.")
    origin = f"http://{host}:{port}"
    updates = {"WEB_BIND_IP": "0.0.0.0", "WEB_PORT": str(port), "DEBUG": "false"}
    for key, value in [("ALLOWED_HOSTS", host), ("CSRF_TRUSTED_ORIGINS", origin)]:
        existing = [part.strip() for part in old.get(key, "").split(",") if part.strip()]
        defaults = (
            ["localhost", "127.0.0.1", "[::1]"]
            if key == "ALLOWED_HOSTS"
            else [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
        )
        updates[key] = ",".join(dict.fromkeys(existing + defaults + [value]))
    lines, seen = [], set()
    for line in content.splitlines():
        found = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=", line)
        key = found[1] if found else None
        if key in updates:
            if key not in seen:
                lines.append(key + "=" + updates[key])
                seen.add(key)
        else:
            lines.append(line)
    lines += [key + "=" + value for key, value in updates.items() if key not in seen]
    return "\n".join(lines) + "\n", origin, port


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="IPv4 Wi-Fi/Ethernet laptop, misalnya 192.168.1.10")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env"
    )
    args = parser.parse_args()
    try:
        host = args.host
        if not host:
            candidates = sorted(
                {
                    item[4][0]
                    for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                    if private_ipv4(item[4][0])
                }
            )
            if len(candidates) != 1:
                raise ValueError(
                    "Pilih IPv4 Wi-Fi/Ethernet dari ipconfig, lalu jalankan: py scripts\\enable_lan.py --host IP_LAPTOP. Alamat terdeteksi: "
                    + (", ".join(candidates) or "tidak ada")
                )
            host = candidates[0]
        content = args.env_file.read_text(encoding="utf-8-sig")
        updated, origin, port = lan_environment(content, host)
        if args.dry_run:
            print("Pemeriksaan berhasil; file tidak diubah. URL HP:", origin)
            return
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, 0))
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=args.env_file.parent, prefix=".env-lan-", delete=False
        ) as output:
            temp = Path(output.name)
            output.write(updated)
        try:
            temp.chmod(args.env_file.stat().st_mode & 0o777)
            os.replace(temp, args.env_file)
        finally:
            temp.unlink(missing_ok=True)
        print("Pengaturan Wi-Fi disimpan. Jalankan:")
        print("docker compose up -d --build --force-recreate --wait web worker beat")
        print("Di HP, buka:", origin)
        print("Jika masih terblokir, jalankan PowerShell sebagai Administrator:")
        print(
            f'New-NetFirewallRule -DisplayName "Sinau Satwa LAN {port}" -Direction Inbound -Action Allow -Protocol TCP -LocalPort {port} -RemoteAddress LocalSubnet -Profile Private'
        )
        print("Gunakan jaringan Windows Private yang dipercaya. Profil Public tidak dibuka.")
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
