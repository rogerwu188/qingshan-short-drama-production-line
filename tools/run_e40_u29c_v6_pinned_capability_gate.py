#!/usr/bin/env python3
"""Run the U29C capability gate with an immutable validator and V6 contract."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools/validate_e40_u29c_v6_capability_contract.py"
VALIDATOR_SHA256 = "ebf2275931a09cd51dbb00af8268959faea62e1885b5b3a24be11d6c00fd87e5"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u29c_v6_changed_representation_no_submit_v1/E40_U29C_V6_PROVIDER_CAPABILITY_AND_EXECUTION_CONTRACT_V1.json"
CONTRACT_SHA256 = "10d38f21b46d37819f4205a265662d011beebc1e778d6f658a97ad394fe935a2"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if digest(VALIDATOR) != VALIDATOR_SHA256:
        raise SystemExit("PINNED_VALIDATOR_SHA_MISMATCH")
    if digest(CONTRACT) != CONTRACT_SHA256:
        raise SystemExit("PINNED_CONTRACT_SHA_MISMATCH")

    output = Path(args.out).expanduser()
    if not output.is_absolute():
        output = ROOT / output
    command = [
        sys.executable,
        str(VALIDATOR),
        "--contract",
        str(CONTRACT),
        "--out",
        str(output),
    ]
    completed = subprocess.run(command, cwd=ROOT, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
