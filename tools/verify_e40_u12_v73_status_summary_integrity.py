#!/usr/bin/env python3
"""Verify immutable V72 summary inputs without provider or production effects."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v73_status_summary_integrity/E40_U12_V73_STATUS_SUMMARY_INTEGRITY_SPEC.json"
V72_TOOL = ROOT / "tools/summarize_e40_u12_v72_status_integrity.py"
V72_RESULT = ROOT / "qa/e40_preproduction_20260813/u12_v72_status_integrity_summary/E40_U12_V72_SUMMARY.json"
PINS = {
    SPEC: "e85506076de0bdc5bf3cafc2d28159caaa5afa4b9f002bf92de8873b7e013151",
    V72_TOOL: "23c9fe8b4f0c39e2b9cd7e0bc60d941b70d05badbcf820cf063c1ab5924590d1",
    V72_RESULT: "fba81f07b1ab9d8761df0b2691522fc1fc666e32466afed1277e99256f42318e",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(path: Path) -> tuple[int, int, int, str]:
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, sha256(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    before = {path: fingerprint(path) for path in PINS}
    summary = json.loads(V72_RESULT.read_text())
    pin_rows = [
        {
            "path": str(path.relative_to(ROOT)),
            "expected_sha256": expected,
            "actual_sha256": before[path][3],
            "exact": before[path][3] == expected,
        }
        for path, expected in PINS.items()
    ]
    after = {path: fingerprint(path) for path in PINS}
    stable = before == after
    semantic_ok = (
        summary.get("status") == "PASS_V63_V71_9_OF_9_TERMINAL_EVIDENCE_EXACT"
        and summary.get("passed") == 9
        and summary.get("total") == 9
        and summary.get("authorization") is False
        and summary.get("maximum_new_submissions") == 0
    )
    ok = all(row["exact"] for row in pin_rows) and stable and semantic_ok
    result = {
        "schema": "qingshan.e40.u12.v73.gate.v1",
        "status": "PASS_3_OF_3_PINS_STABLE_AND_V72_9_OF_9_EXACT" if ok else "FAIL",
        "pins": pin_rows,
        "passed": sum(row["exact"] for row in pin_rows),
        "total": 3,
        "fingerprints_unchanged": stable,
        "v72_semantics_exact": semantic_ok,
        "authorization": False,
        "maximum_new_submissions": 0,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
