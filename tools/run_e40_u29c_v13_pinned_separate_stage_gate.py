#!/usr/bin/env python3
"""Invoke the V12 separate-stage gate through exact immutable pins."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / "tools/run_e40_u29c_v12_separate_stage_capability_gate.py"
WRITER_SHA256 = "00696e5c81a5e41510fad9f2244c8068c35d373c09f55c2911e21e47e65d23f9"
SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v13_pinned_separate_stage_regression_v1/E40_U29C_V13_PINNED_WRITER_RESIDUE_AND_PARENT_CONTAINMENT_SPEC_V1.json"
SPEC_SHA256 = "36bc00ee54c340471656a6353df16476984dbb2a44274fb278811d27764a682d"
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json\Z")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--output-name", required=True)
    args = parser.parse_args()
    if not SAFE_NAME.fullmatch(args.output_name):
        raise SystemExit("OUTPUT_NAME_MUST_BE_SAFE_JSON_BASENAME")
    if digest(WRITER) != WRITER_SHA256:
        raise SystemExit("PINNED_V12_WRITER_SHA_MISMATCH")
    if digest(SPEC) != SPEC_SHA256:
        raise SystemExit("PINNED_V13_SPEC_SHA_MISMATCH")
    completed = subprocess.run(
        [sys.executable, str(WRITER), "--output-name", args.output_name],
        cwd=ROOT,
        close_fds=True,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
