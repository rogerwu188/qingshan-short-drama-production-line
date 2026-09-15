#!/usr/bin/env python3
"""Fail-closed common-sense, physical-causality, and counterfactual gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: Any, minimum: int = 1) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= minimum
        and all(_text(item) for item in value)
    )


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    decisions: list[dict[str, Any]] = []
    units = payload.get("units")
    if not isinstance(units, list) or not units:
        failures.append("causality_units_missing")
        units = []

    for index, unit in enumerate(units, start=1):
        unit_id = str(unit.get("unit_id") or f"UNIT_{index}")
        evidence = unit.get("causality")
        unit_failures: list[str] = []
        if not isinstance(evidence, dict):
            unit_failures.append("causality_evidence_missing")
            evidence = {}

        applicable = evidence.get("applicable")
        if applicable is False:
            if not _text(evidence.get("not_applicable_reason")):
                unit_failures.append("not_applicable_reason_missing")
        elif applicable is not True:
            unit_failures.append("applicability_not_explicit")
        else:
            for key in ("purpose", "intended_effect", "visible_causality", "viewer_read"):
                if not _text(evidence.get(key)):
                    unit_failures.append(f"{key}_missing")
            if not _text_list(evidence.get("preconditions")):
                unit_failures.append("preconditions_missing")
            if not _text_list(evidence.get("mechanism_chain"), minimum=2):
                unit_failures.append("mechanism_chain_requires_at_least_two_steps")

            counterfactual = evidence.get("counterfactual_test")
            if not isinstance(counterfactual, dict):
                unit_failures.append("counterfactual_test_missing")
            else:
                if counterfactual.get("opponent_can_bypass") is not False:
                    unit_failures.append("counterfactual_bypass_not_disproved")
                if not _text(counterfactual.get("reasoning")):
                    unit_failures.append("counterfactual_reasoning_missing")

            if str(evidence.get("prop_function_status") or "").upper() != "PASS":
                unit_failures.append("prop_function_not_pass")
            if not _text_list(evidence.get("evidence_refs")):
                unit_failures.append("evidence_refs_missing")

        failures.extend(f"{unit_id}:{item}" for item in unit_failures)
        decisions.append(
            {
                "unit_id": unit_id,
                "status": "PASS" if not unit_failures else "FAIL",
                "failures": unit_failures,
            }
        )

    return {
        "schema": "qingshan.common_sense_causality_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "fail_closed": True,
        "decisions": decisions,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.plan.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
