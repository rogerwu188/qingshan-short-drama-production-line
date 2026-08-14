#!/usr/bin/env python3
"""Fail closed unless a StoryClaw online-agent sync receipt is fully verified."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


REQUIRED = (
    ("SYNC_STATUS", "VERIFIED"),
    ("REMOTE_AGENT_VERSION", None),
    ("REMOTE_UPDATED_AT", None),
    ("REMOTE_EDITOR_URL", None),
    ("REMOTE_SAVE_EVIDENCE", None),
)


def value_for(text: str, name: str) -> str | None:
    match = re.search(rf"^{re.escape(name)}=(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()

    receipt = Path(args.receipt).expanduser()
    if not receipt.is_file():
        print(f"STORYCLAW_SYNC_BLOCKED missing receipt: {receipt}")
        return 2

    text = receipt.read_text(encoding="utf-8")
    gate = re.search(
        r"^## Online Verification Gate\s*$([\s\S]*?)(?=^## |\Z)",
        text,
        flags=re.MULTILINE,
    )
    if not gate:
        print("STORYCLAW_SYNC_BLOCKED missing Online Verification Gate section")
        return 1
    status_text = gate.group(1)
    failures: list[str] = []
    for field, expected in REQUIRED:
        value = value_for(status_text, field)
        if not value or (expected is not None and value != expected):
            failures.append(f"{field}={value or '<missing>'}")

    if failures:
        print("STORYCLAW_SYNC_BLOCKED " + "; ".join(failures))
        return 1

    print(f"STORYCLAW_SYNC_VERIFIED receipt={receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
