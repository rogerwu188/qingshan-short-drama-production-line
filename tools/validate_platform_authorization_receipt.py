#!/usr/bin/env python3
"""Validate a SHA-bound human authorization receipt before publication."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_AUTHORIZERS = {"ROGER", "SUPERVISOR"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate(
    receipt_path: Path,
    final_path: Path,
    episode: str,
    platforms: set[str],
    submit_at: datetime | None,
) -> dict:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    if receipt.get("schema") != "qingshan.platform_authorization.v1":
        failures.append("SCHEMA_MISMATCH")
    if receipt.get("authorized") is not True:
        failures.append("AUTHORIZED_NOT_TRUE")
    if receipt.get("episode") != episode:
        failures.append("EPISODE_MISMATCH")
    if receipt.get("authorizer") not in ALLOWED_AUTHORIZERS:
        failures.append("AUTHORIZER_NOT_ALLOWED")
    if not str(receipt.get("authorization_quote", "")).strip():
        failures.append("AUTHORIZATION_QUOTE_MISSING")

    issued_at = None
    try:
        issued_at = parse_time(str(receipt.get("issued_at", "")))
    except (TypeError, ValueError):
        failures.append("ISSUED_AT_INVALID")
    if submit_at is not None and issued_at is not None and issued_at > submit_at:
        failures.append("AUTHORIZATION_POSTDATES_SUBMISSION")

    actual_final_sha = sha256(final_path)
    if receipt.get("final_sha256") != actual_final_sha:
        failures.append("FINAL_SHA_MISMATCH")

    authorized_platforms = {
        str(platform).lower() for platform in receipt.get("platform_targets", [])
    }
    missing_platforms = sorted(platforms - authorized_platforms)
    if missing_platforms:
        failures.append("PLATFORM_TARGET_MISSING:" + ",".join(missing_platforms))

    result = {
        "status": "PASS" if not failures else "FAIL",
        "authorized": not failures,
        "episode": episode,
        "final": str(final_path),
        "final_sha256": actual_final_sha,
        "authorization_receipt": str(receipt_path),
        "authorization_receipt_sha256": sha256(receipt_path),
        "platform_targets": sorted(platforms),
        "failures": failures,
        "next_action": "PLATFORM_SUBMISSION_ALLOWED" if not failures else "PLATFORM_SUBMISSION_FORBIDDEN",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--final", required=True, type=Path)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--platform", action="append", required=True)
    parser.add_argument("--submit-at")
    args = parser.parse_args()

    submit_at = parse_time(args.submit_at) if args.submit_at else None
    result = validate(
        args.receipt,
        args.final,
        args.episode,
        {platform.lower() for platform in args.platform},
        submit_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["authorized"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
