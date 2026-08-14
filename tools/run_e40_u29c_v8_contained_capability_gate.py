#!/usr/bin/env python3
"""Run the pinned U29C gate into a fixed, no-overwrite QA directory."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PINNED_INVOKER = ROOT / "tools/run_e40_u29c_v6_pinned_capability_gate.py"
PINNED_INVOKER_SHA256 = "5678c70075143cd86ea038e798720cff92b0fe28a5389214a23184c18c589964"
OUTPUT_ROOT = ROOT / "qa/e40_preproduction_20260808/u29c_v9_pinned_output_containment_v1"
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json\Z")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reject_symlink_components(path: Path) -> None:
    current = ROOT
    for part in path.relative_to(ROOT).parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise SystemExit("OUTPUT_PARENT_SYMLINK_FORBIDDEN")


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--output-name", required=True)
    args = parser.parse_args()

    if digest(PINNED_INVOKER) != PINNED_INVOKER_SHA256:
        raise SystemExit("PINNED_INVOKER_SHA_MISMATCH")
    if not SAFE_NAME.fullmatch(args.output_name):
        raise SystemExit("OUTPUT_NAME_MUST_BE_SAFE_JSON_BASENAME")

    output = OUTPUT_ROOT / args.output_name
    reject_symlink_components(output)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ROOT.is_symlink():
        raise SystemExit("OUTPUT_ROOT_SYMLINK_FORBIDDEN")
    if output.exists() or output.is_symlink():
        raise SystemExit("OUTPUT_OVERWRITE_FORBIDDEN")
    if output.resolve(strict=False).parent != OUTPUT_ROOT.resolve():
        raise SystemExit("OUTPUT_CONTAINMENT_FAILED")

    completed = subprocess.run(
        [sys.executable, str(PINNED_INVOKER), "--out", str(output)],
        cwd=ROOT,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
