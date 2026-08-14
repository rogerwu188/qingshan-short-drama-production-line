#!/usr/bin/env python3
"""Exact-SHA pinned invoker for the U29C V20 recovery writer."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base  # noqa: E402
import run_e40_u29c_v20_post_link_recovery_publish_gate as writer  # noqa: E402


WRITER = ROOT / "tools/run_e40_u29c_v20_post_link_recovery_publish_gate.py"
WRITER_SHA256 = "6b61cf37134e1a3a2fa16f95140db82efaf5fe164a52e5373ed324890cde227e"
V20_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v20_post_link_recovery_writer_v1/E40_U29C_V20_POST_LINK_RECOVERY_BOUNDED_MATRIX_V1.json"
V20_MATRIX_SHA256 = "6264a06504f9f9dc88da98a60a0fe1053e8abe420714ce9fa78f54714f3a0c81"
V19_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v19_atomic_link_exception_safety_audit_v1/E40_U29C_V19_ATOMIC_LINK_EXCEPTION_SAFETY_AUDIT_V1.json"
V19_AUDIT_SHA256 = "5b872fe948e6516bbfa571dd135fd8e02216800658a87a0c9f2ade8155b76ca5"
V21_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v21_pinned_recovery_regression_v1/E40_U29C_V21_PINNED_POST_LINK_RECOVERY_REGRESSION_SPEC_V1.json"
V21_SPEC_SHA256 = "48c399a938aa74a57cbb41104ba82406d388cc54fb7b45dff3f8845fe35a2526"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pins() -> None:
    for path, expected, code in [
        (WRITER, WRITER_SHA256, "PINNED_V20_WRITER_SHA_MISMATCH"),
        (V20_MATRIX, V20_MATRIX_SHA256, "PINNED_V20_MATRIX_SHA_MISMATCH"),
        (V19_AUDIT, V19_AUDIT_SHA256, "PINNED_V19_AUDIT_SHA_MISMATCH"),
        (V21_SPEC, V21_SPEC_SHA256, "PINNED_V21_SPEC_SHA_MISMATCH"),
    ]:
        if digest(path) != expected:
            raise base.GateError(code)


def execute(output_name: str) -> dict[str, object]:
    verify_pins()
    result = writer.execute(output_name)
    if result.get("wrapper_status") != "PASS_POST_LINK_OUTCOME_RECOVERY_FAIL_CLOSED_NO_SUBMIT":
        raise base.GateError("PINNED_V20_WRITER_STATUS_MISMATCH")
    return {
        **result,
        "invoker_status": "PASS_PINNED_V20_POST_LINK_RECOVERY_NO_SUBMIT",
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
    except base.GateError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
