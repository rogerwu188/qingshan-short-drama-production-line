#!/usr/bin/env python3
"""Verify that the three StoryClaw bridge tools share a healthy endpoint."""

from __future__ import annotations

import argparse
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse


PROJECT = Path("/Users/rogerwu/qingshan_short_drama")
DEFAULT_FIXED_URL = "https://qingshan-bridge-api.rogerwu188.workers.dev"


def configured_urls() -> dict[str, str | None]:
    from storyclaw_bridge_config import base_url

    endpoint = base_url()
    return {
        "storyclaw_outbox_poller.py": endpoint,
        "storyclaw_bridge_reply.py": endpoint,
        "storyclaw_realtime_sync.py": endpoint,
    }


def resolve(url: str) -> tuple[bool, str]:
    host = urlparse(url).hostname
    if not host:
        return False, "invalid URL"
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except OSError as exc:
        return False, str(exc)
    return True, ", ".join(addresses)


def health(url: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["curl", "-fsS", "--max-time", "8", f"{url.rstrip('/')}/health"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        return False, result.stderr.strip() or "health request failed"
    return True, result.stdout.strip()[:300]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check StoryClaw bridge endpoint readiness.")
    parser.add_argument("--expected-url", default=DEFAULT_FIXED_URL)
    parser.add_argument("--allow-temporary", action="store_true")
    args = parser.parse_args()

    configured = configured_urls()
    unique = set(configured.values())
    consistent = len(unique) == 1 and None not in unique
    endpoint = next(iter(unique)) if consistent else None
    print(f"tool_endpoints_consistent={str(consistent).lower()}")
    for name, url in configured.items():
        print(f"{name}={url or 'MISSING'}")
    if not consistent or endpoint is None:
        return 2

    temporary = endpoint.endswith(".trycloudflare.com")
    if temporary and not args.allow_temporary:
        print("cutover_ready=false")
        print("reason=temporary_endpoint_configured")
        return 3

    dns_ok, dns_detail = resolve(endpoint)
    print(f"dns_ok={str(dns_ok).lower()}")
    print(f"dns_detail={dns_detail}")
    if not dns_ok:
        return 4

    health_ok, health_detail = health(endpoint)
    print(f"health_ok={str(health_ok).lower()}")
    print(f"health_detail={health_detail}")
    if not health_ok:
        return 5

    expected = args.expected_url.rstrip("/")
    print(f"cutover_ready={str(endpoint.rstrip('/') == expected).lower()}")
    return 0 if endpoint.rstrip("/") == expected else 6


if __name__ == "__main__":
    raise SystemExit(main())
