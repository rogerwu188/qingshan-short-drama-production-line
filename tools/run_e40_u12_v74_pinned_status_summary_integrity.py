#!/usr/bin/env python3
"""Run V73 only when the immutable V73 chain is pinned exactly."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PINS = [
    (
        "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v74_pinned_status_summary_integrity/E40_U12_V74_PINNED_STATUS_SUMMARY_INTEGRITY_SPEC.json",
        "a5d7d67c64fc470ecf4c05a063bb19ac5c248b1f9d60b20063075ad36230a282",
    ),
    (
        "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v73_status_summary_integrity/E40_U12_V73_STATUS_SUMMARY_INTEGRITY_SPEC.json",
        "e85506076de0bdc5bf3cafc2d28159caaa5afa4b9f002bf92de8873b7e013151",
    ),
    (
        "tools/verify_e40_u12_v73_status_summary_integrity.py",
        "64a25b33d40607a71a18686bc34d9113933d6b4993d27b8c9e30b1973f67cd85",
    ),
    (
        "qa/e40_preproduction_20260813/u12_v73_status_summary_integrity/E40_U12_V73_GATE.json",
        "72de722b613722c89b1684785076b9e868ce6d2af2aed9e8485015f925b804d4",
    ),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if any(sha256(ROOT / path) != expected for path, expected in PINS):
        raise SystemExit("PIN_MISMATCH")
    return subprocess.run(
        [sys.executable, str(ROOT / PINS[2][0]), "--out", args.out], cwd=ROOT
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
