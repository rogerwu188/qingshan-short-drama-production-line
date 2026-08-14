#!/usr/bin/env python3
"""Pinned invoker for the E40/U12 immutable snapshot-before-upgrade gate."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools/validate_e40_u12_immutable_snapshot_upgrade_request.py"
VALIDATOR_SHA256 = "6e850c22a4685ab50469c5d1b9d4281d1125e4b4f4b04fefcb8fd408c60d4b78"
POLICY = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v22_immutable_snapshot_policy_v1/E40_U12_V22_IMMUTABLE_PRE_UPGRADE_SNAPSHOT_POLICY_V1.json"
POLICY_SHA256 = "f511ebca41fb884e35ee09ae56517d3b65915d7742b25e554b8debdafbe4c5c9"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_pin(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"PIN_FAIL_{label}_MISSING:{path}")
    actual = sha256_file(path)
    if actual != expected:
        raise SystemExit(f"PIN_FAIL_{label}_SHA256:expected={expected}:actual={actual}")


def safe_repo_path(raw: str, label: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit(f"{label}_MUST_BE_REPO_RELATIVE")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SystemExit(f"{label}_OUTSIDE_REPOSITORY") from exc
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the E40/U12 immutable snapshot gate with exact-SHA pinned policy and validator.",
        allow_abbrev=False,
    )
    parser.add_argument("--request", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-status")
    args = parser.parse_args()

    request = safe_repo_path(args.request, "REQUEST")
    out = safe_repo_path(args.out, "OUT")
    if not request.is_file():
        raise SystemExit(f"REQUEST_MISSING:{request}")
    require_pin(VALIDATOR, VALIDATOR_SHA256, "VALIDATOR")
    require_pin(POLICY, POLICY_SHA256, "POLICY")

    command = [
        sys.executable,
        str(VALIDATOR),
        "--policy",
        str(POLICY.relative_to(ROOT)),
        "--request",
        str(request.relative_to(ROOT)),
        "--out",
        str(out.relative_to(ROOT)),
    ]
    if args.expect_status:
        command.extend(["--expect-status", args.expect_status])
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
