#!/usr/bin/env python3
"""Fail when audit JSON contains timestamps later than the system clock."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TIMESTAMP_KEYS = {
    "created_at",
    "reviewed_at",
    "tested_at",
    "updated_at",
    "last_heartbeat_at",
    "blocked_since_at",
}


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def timestamp_rows(value: Any, location: str = "$") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{location}.{key}"
            if key in TIMESTAMP_KEYS and isinstance(item, str):
                rows.append((child, item))
            rows.extend(timestamp_rows(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(timestamp_rows(item, f"{location}[{index}]"))
    return rows


def validate(path: Path, now: datetime, tolerance_seconds: int = 60) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    upper_bound = now.astimezone(timezone.utc) + timedelta(seconds=tolerance_seconds)
    failures: list[str] = []
    for location, raw in timestamp_rows(payload):
        try:
            parsed = parse_iso(raw)
        except ValueError as exc:
            failures.append(f"{path}:{location}:invalid_timestamp:{exc}")
            continue
        if parsed > upper_bound:
            failures.append(f"{path}:{location}:future_timestamp:{raw}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--tolerance-seconds", type=int, default=60)
    parser.add_argument("--now", help="ISO timestamp override for deterministic tests")
    args = parser.parse_args()
    now = parse_iso(args.now) if args.now else datetime.now().astimezone()
    failures: list[str] = []
    for path in args.paths:
        failures.extend(validate(path.resolve(), now, args.tolerance_seconds))
    print(
        json.dumps(
            {
                "status": "PASS" if not failures else "FAIL",
                "checked_files": len(args.paths),
                "failures": failures,
            },
            ensure_ascii=False,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
