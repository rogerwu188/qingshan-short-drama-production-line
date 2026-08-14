#!/usr/bin/env python3
"""Exact-SHA pinned local invoker for the U29C V17 atomic-link writer."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as writer  # noqa: E402


WRITER = ROOT / "tools/run_e40_u29c_v17_atomic_link_publish_gate.py"
WRITER_SHA256 = "7728588e210ae17f61cc1c08eef6a18fdd3dfdba3e6cc1e77e61e2f8ae1778d8"
V17_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v17_atomic_link_writer_v1/E40_U29C_V17_ATOMIC_LINK_READER_CONTENTION_MATRIX_V1.json"
V17_MATRIX_SHA256 = "e9927de46465e09c1e70403aeebb1235bfa57ce6a42c46ac13a5b106adba0062"
VALIDATOR = ROOT / "tools/validate_e40_u29c_v6_capability_contract.py"
VALIDATOR_SHA256 = "ebf2275931a09cd51dbb00af8268959faea62e1885b5b3a24be11d6c00fd87e5"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u29c_v6_changed_representation_no_submit_v1/E40_U29C_V6_PROVIDER_CAPABILITY_AND_EXECUTION_CONTRACT_V1.json"
CONTRACT_SHA256 = "10d38f21b46d37819f4205a265662d011beebc1e778d6f658a97ad394fe935a2"
V18_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v18_pinned_atomic_link_regression_v1/E40_U29C_V18_PINNED_ATOMIC_LINK_REGRESSION_SPEC_V1.json"
V18_SPEC_SHA256 = "e35dcfc0b446a72be8e05e214989d8dc35d692722020152d20407cf023adf372"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pins() -> None:
    pins = [
        (WRITER, WRITER_SHA256, "PINNED_V17_WRITER_SHA_MISMATCH"),
        (V17_MATRIX, V17_MATRIX_SHA256, "PINNED_V17_MATRIX_SHA_MISMATCH"),
        (VALIDATOR, VALIDATOR_SHA256, "PINNED_VALIDATOR_SHA_MISMATCH"),
        (CONTRACT, CONTRACT_SHA256, "PINNED_CONTRACT_SHA_MISMATCH"),
        (V18_SPEC, V18_SPEC_SHA256, "PINNED_V18_SPEC_SHA_MISMATCH"),
    ]
    for path, expected, code in pins:
        if digest(path) != expected:
            raise writer.GateError(code)


def execute(output_name: str) -> dict[str, object]:
    verify_pins()
    result = writer.execute(output_name)
    if result.get("wrapper_status") != "PASS_ATOMIC_LINK_PUBLICATION_FAIL_CLOSED_NO_SUBMIT":
        raise writer.GateError("PINNED_WRITER_STATUS_MISMATCH")
    return {
        **result,
        "invoker_status": "PASS_PINNED_V17_ATOMIC_LINK_WRITER_NO_SUBMIT",
        "pinned_writer_sha256": WRITER_SHA256,
        "execution_permitted": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--output-name", required=True)
    args = parser.parse_args()
    try:
        result = execute(args.output_name)
    except writer.GateError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
