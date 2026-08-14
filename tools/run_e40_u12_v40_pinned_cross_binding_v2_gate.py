#!/usr/bin/env python3
"""Exact-SHA pinned invoker for E40/U12 V39 cross-binding policy V2."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v39_cross_binding_policy_v2/E40_U12_V39_FOUR_EVIDENCE_CROSS_BINDING_POLICY_V2.json"
POLICY_SHA256 = "1c5d8c15596e19ed66ed3417d4d21ad5068caed769df106cb42c91c81f83a536"
FIXTURES = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v39_cross_binding_policy_v2/E40_U12_V39_SYNTHETIC_NEGATIVE_FIXTURE_MATRIX_V2.json"
FIXTURES_SHA256 = "475e62a170b2a142beaedb50ab7ba7c9eef9c0a2e13474ff5c65dbb4b891e3ec"
VALIDATOR = ROOT / "tools/validate_e40_u12_v39_cross_binding_policy_v2.py"
VALIDATOR_SHA256 = "6a067ceee9ccb43f0c729f53a3578d5b65cf7a8123fde21f6f1bb6290e6d83e8"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_pin(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"PIN_FAIL_{label}_MISSING:{path}")
    actual = sha256(path)
    if actual != expected:
        raise SystemExit(f"PIN_FAIL_{label}_SHA256:expected={expected}:actual={actual}")


def safe_repo_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit("OUT_MUST_BE_REPO_RELATIVE")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SystemExit("OUT_OUTSIDE_REPOSITORY") from exc
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = safe_repo_path(args.out)
    if out.suffix != ".json":
        raise SystemExit("OUT_MUST_BE_JSON")
    if out.exists():
        raise SystemExit(f"OUT_OVERWRITE_FORBIDDEN:{out}")

    require_pin(POLICY, POLICY_SHA256, "POLICY")
    require_pin(FIXTURES, FIXTURES_SHA256, "FIXTURES")
    require_pin(VALIDATOR, VALIDATOR_SHA256, "VALIDATOR")
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--out", str(out.relative_to(ROOT))],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
