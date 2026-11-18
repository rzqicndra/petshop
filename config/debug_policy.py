"""Technical debug pages are restricted to explicitly loopback-only setups."""
from ipaddress import ip_address


def debug_allowed(requested, local_mode, allowed_hosts, public_webhook_url):
    if not requested or not local_mode or public_webhook_url or not allowed_hosts:
        return False
    for host in allowed_hosts:
        if host == "localhost":
            continue
        try:
            if not ip_address(host.strip("[]")).is_loopback:
                return False
        except ValueError:
            return False
    return True
