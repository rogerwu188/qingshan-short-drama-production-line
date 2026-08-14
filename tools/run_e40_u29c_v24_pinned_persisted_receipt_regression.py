#!/usr/bin/env python3
"""Exact-SHA pinned invoker for the U29C V23 persisted receipt writer."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base  # noqa: E402
import run_e40_u29c_v23_persisted_recovery_receipt_gate as writer  # noqa: E402


WRITER = ROOT / "tools/run_e40_u29c_v23_persisted_recovery_receipt_gate.py"
WRITER_SHA256 = "3f5af7ba788f1b62015da87826033ca5ba77995da9537d2b2bdca7044403f175"
V23_MATRIX = ROOT / "qa/e40_preproduction_20260808/u29c_v23_persisted_recovery_receipt_writer_v1/E40_U29C_V23_PERSISTED_RECOVERY_RECEIPT_BOUNDED_MATRIX_V1.json"
V23_MATRIX_SHA256 = "ee95eea5e5a4114376807b3ccffe9214b0dabdd2d2c34d5156f72b829577d765"
V22_AUDIT = ROOT / "qa/e40_preproduction_20260808/u29c_v22_recovery_receipt_crash_boundary_audit_v1/E40_U29C_V22_RECOVERED_SUCCESS_RECEIPT_AND_CRASH_BOUNDARY_AUDIT_V1.json"
V22_AUDIT_SHA256 = "09943bbd534f3f69567f98609bbb2a86ca7740062c8e5b036e2321c46725ed85"
V24_SPEC = ROOT / "qa/e40_preproduction_20260808/u29c_v24_pinned_persisted_receipt_regression_v1/E40_U29C_V24_PINNED_PERSISTED_RECEIPT_RESTART_REGRESSION_SPEC_V1.json"
V24_SPEC_SHA256 = "7c180f2bd06ee4582ed39a31681c6ade6f49a0f37fe3fbb32d5f76d493fb576e"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_pins() -> None:
    for path, expected, code in [
        (WRITER, WRITER_SHA256, "PINNED_V23_WRITER_SHA_MISMATCH"),
        (V23_MATRIX, V23_MATRIX_SHA256, "PINNED_V23_MATRIX_SHA_MISMATCH"),
        (V22_AUDIT, V22_AUDIT_SHA256, "PINNED_V22_AUDIT_SHA_MISMATCH"),
        (V24_SPEC, V24_SPEC_SHA256, "PINNED_V24_SPEC_SHA_MISMATCH"),
    ]:
        if digest(path) != expected:
            raise base.GateError(code)


def execute(output_name: str) -> dict[str, object]:
    verify_pins()
    result = writer.execute(output_name)
    return {
        **result,
        "invoker_status": "PASS_PINNED_V23_PERSISTED_RECEIPT_WRITER_NO_SUBMIT",
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
