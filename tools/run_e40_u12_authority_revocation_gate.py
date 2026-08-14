#!/usr/bin/env python3
"""Pinned invoker for the E40 U12 authority revocation gate."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools/validate_e40_u12_authority_revocation.py"
VALIDATOR_SHA256 = "1d8c9c178bd316fe82ae2ef212f7e26e82ad109cdc10c65c9b06602b2824fb18"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v10_authority_admission_contract_v1/E40_U12_V10_TRUSTED_AUTHORITY_ADMISSION_KEY_CUSTODY_CONTRACT_V1.json"
CONTRACT_SHA256 = "064ea0ee42f82d817fe33976f2a765a663fe4735c9f8e4fa97c8997bf03500fb"
REGISTRY = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v13_revocation_registry_v1/E40_U12_V13_REVOKED_TEST_KEY_REGISTRY_FIXTURE_V1.json"
REGISTRY_SHA256 = "63e8d909450e7c5051990c02e0749e19cc74ca27db9f9bf5ac085cbc1f0ac151"


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
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-reject", action="store_true")
    args = parser.parse_args()
    subject = safe_repo_path(args.subject, "SUBJECT")
    out = safe_repo_path(args.out, "OUT")
    if not subject.is_file():
        raise SystemExit(f"SUBJECT_MISSING:{subject}")
    require_pin(VALIDATOR, VALIDATOR_SHA256, "VALIDATOR")
    require_pin(CONTRACT, CONTRACT_SHA256, "CONTRACT")
    require_pin(REGISTRY, REGISTRY_SHA256, "REGISTRY")
    command = [
        sys.executable,
        str(VALIDATOR),
        "--contract",
        str(CONTRACT.relative_to(ROOT)),
        "--registry",
        str(REGISTRY.relative_to(ROOT)),
        "--subject",
        str(subject.relative_to(ROOT)),
        "--out",
        str(out.relative_to(ROOT)),
    ]
    if args.expect_reject:
        command.append("--expect-reject")
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
