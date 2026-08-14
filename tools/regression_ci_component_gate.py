#!/usr/bin/env python3
"""Project one mandatory regression-CI report into a named registered gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


COMPONENTS = {
    "GATE-REGISTRY-INTEGRITY": "gate_registry_integrity",
    "FINAL-AUDIO-BED-CONTINUITY": "audio_bed_continuity",
    "FINAL-STATIC-HOLD": "static_hold_gate",
}
FROZEN_PROFILE = "v2-final+v2.1+v2.2+v2.3-frozen"


def evaluate(report: dict, gate_id: str) -> dict:
    failures: list[str] = []
    evidence: dict = {}
    if gate_id in COMPONENTS:
        key = COMPONENTS[gate_id]
        component = report.get(key)
        evidence = {"component": key, "result": component}
        if not isinstance(component, dict):
            failures.append(f"ci_component_missing:{key}")
        elif not str(component.get("status") or "").upper().startswith("PASS"):
            failures.append(f"ci_component_failed:{key}:{component.get('status') or 'MISSING'}")
    elif gate_id == "FROZEN-THRESHOLD-PROFILE":
        profile = report.get("threshold_profile")
        override = report.get("threshold_override_audit") or {}
        evidence = {"threshold_profile": profile, "threshold_override_audit": override}
        if profile != FROZEN_PROFILE:
            failures.append(f"frozen_profile_mismatch:{profile or 'MISSING'}")
        override_status = str(override.get("status") or "").upper()
        if override_status not in {"NOT_REQUESTED", "PASS_WITH_AUTHORIZED_OVERRIDE"}:
            failures.append(f"threshold_override_invalid:{override_status or 'MISSING'}")
    else:
        failures.append(f"unsupported_regression_component_gate:{gate_id}")
    return {
        "schema": "qingshan.regression_ci_component_gate.v1",
        "gate_id": gate_id,
        "status": "PASS" if not failures else "FAIL",
        "source_ci_status": report.get("status"),
        "evidence": evidence,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--gate-id", required=True, choices=sorted([*COMPONENTS, "FROZEN-THRESHOLD-PROFILE"]))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.report).expanduser().resolve().read_text(encoding="utf-8"))
    result = evaluate(report, args.gate_id)
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "gate_id": args.gate_id, "out": str(out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
