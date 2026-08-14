#!/usr/bin/env python3
"""Invoke V75 only under the exact immutable V75/V76 pins."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PINS = [
    ("workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v76_pinned_recent_chain_audit/E40_U12_V76_PINNED_RECENT_CHAIN_AUDIT_SPEC.json", "524c7512d2c34fe5e28b1cdf66896de926afcacba77d4de65d873c5aea80cc0b"),
    ("workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v75_recent_chain_audit/E40_U12_V75_RECENT_CHAIN_AUDIT_SPEC.json", "d0990cd642d0965a73ac3b269efaf480178104d0a800cc1b501175bc6c4c57a3"),
    ("tools/audit_e40_u12_v75_recent_chain.py", "0de42c0b8c0a6e2a9e97438492df567c135bda40c612a883a8957aab597fc6c2"),
    ("qa/e40_preproduction_20260813/u12_v75_recent_chain_audit/E40_U12_V75_AUDIT.json", "b78855720474af068b9fcdb5a7fa0cca13bb445a7e6f1acd122e2c13e194f716"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if any(sha256(ROOT / path) != expected for path, expected in PINS):
        raise SystemExit("PIN_MISMATCH")
    return subprocess.run([sys.executable, str(ROOT / PINS[2][0]), "--out", args.out], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
