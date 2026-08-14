#!/usr/bin/env python3
"""V74 canonical invocation plus CLI substitution rejection matrix."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVOKER = ROOT / "tools/run_e40_u12_v74_pinned_status_summary_integrity.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--canonical", required=True)
    args = parser.parse_args()
    out = ROOT / args.out
    canonical = ROOT / args.canonical
    canonical.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(
        [sys.executable, str(INVOKER), "--out", args.canonical], cwd=ROOT
    )
    gate = json.loads(canonical.read_text())
    cases = [
        run.returncode == 0
        and gate.get("status") == "PASS_3_OF_3_PINS_STABLE_AND_V72_9_OF_9_EXACT"
        and gate.get("passed") == 3
        and gate.get("total") == 3
    ]
    for option in ("--spec", "--verifier", "--gate"):
        candidate = canonical.with_name(canonical.stem + option[2:] + ".json")
        result = subprocess.run(
            [sys.executable, str(INVOKER), "--out", str(candidate.relative_to(ROOT)), option, "x"],
            cwd=ROOT,
            capture_output=True,
        )
        cases.append(result.returncode == 2 and not candidate.exists())
    ok = all(cases)
    matrix = {
        "schema": "qingshan.e40.u12.v74.matrix.v1",
        "status": "PASS_V73_3_OF_3_AND_3_SUBSTITUTIONS_REJECTED" if ok else "FAIL",
        "cases_passed": sum(cases),
        "cases_total": 4,
        "canonical_v73_status": gate.get("status"),
        "authorization": False,
        "maximum_new_submissions": 0,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
