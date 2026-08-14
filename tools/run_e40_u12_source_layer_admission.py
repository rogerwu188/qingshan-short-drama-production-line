#!/usr/bin/env python3
"""Pinned local invoker for E40 U12 source-layer admission.

The caller may select only the candidate package and output receipt.  The
contract, validator and trust policy are fixed here by repository-relative path
and exact SHA, preventing a package or CLI caller from extending trust.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools/validate_e40_u12_source_layer_package.py"
VALIDATOR_SHA256 = "6c7fcd2923166c909b07e8d108e7efb75b1d070edd99a4bc998096565e0c70d2"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v6_source_authority_inventory_v1/E40_U12_V6_CLEAN_DESK_AND_PAPER_LAYER_ACQUISITION_CONTRACT_V1.json"
CONTRACT_SHA256 = "b81d84e563959ef7d5e845aa97f9e51ab091d7e5bb3ad9d2080cb11c71a51abf"
TRUST_POLICY = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v8_trusted_receipt_tamper_audit_v1/E40_U12_V8_TRUSTED_RECEIPT_POLICY_V1.json"
TRUST_POLICY_SHA256 = "db555f73e7497b9eb60e62a63aa78d6974bd3ddaa77ac4462b944b5499fe7737"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


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
        description="Run the E40 U12 fail-closed source-layer gate with pinned authority inputs.",
        allow_abbrev=False,
    )
    parser.add_argument("--package", required=True, help="repo-relative candidate package JSON")
    parser.add_argument("--out", required=True, help="repo-relative gate receipt JSON")
    parser.add_argument("--expect-reject", action="store_true", help="test mode: success means the candidate was rejected")
    args = parser.parse_args()

    package = safe_repo_path(args.package, "PACKAGE")
    out = safe_repo_path(args.out, "OUT")
    if not package.is_file():
        raise SystemExit(f"PACKAGE_MISSING:{package}")

    require_pin(VALIDATOR, VALIDATOR_SHA256, "VALIDATOR")
    require_pin(CONTRACT, CONTRACT_SHA256, "CONTRACT")
    require_pin(TRUST_POLICY, TRUST_POLICY_SHA256, "TRUST_POLICY")

    command = [
        sys.executable,
        str(VALIDATOR),
        "--contract",
        str(CONTRACT.relative_to(ROOT)),
        "--trust-policy",
        str(TRUST_POLICY.relative_to(ROOT)),
        "--package",
        str(package.relative_to(ROOT)),
        "--out",
        str(out.relative_to(ROOT)),
    ]
    if args.expect_reject:
        command.append("--expect-reject")
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
