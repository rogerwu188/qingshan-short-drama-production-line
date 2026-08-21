#!/usr/bin/env python3
"""Enforce three paid attempts and a terminal coverage decision per unit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


MAX_ATTEMPTS = 3
P0_DEFECTS = {
    "IDENTITY_DRIFT", "WRONG_CHARACTER", "COPYRIGHT", "RIGHTS_MISSING",
    "MEDIA_CORRUPT", "PLOT_BREAK", "MISSING_DIALOGUE", "NO_SUBTITLE",
}
TERMINAL_DECISIONS = {"ADMIT_BEST_EFFORT", "SWITCH_COVERAGE"}


def evaluate_unit(unit: dict) -> dict:
    attempts = unit.get("attempts") or []
    decision = unit.get("terminal_decision")
    violations: list[dict] = []
    seen: dict[str, object] = {}
    for attempt in attempts:
        prompt_sha = attempt.get("prompt_sha256")
        number = attempt.get("attempt_no")
        if not prompt_sha:
            violations.append({"code": "PROMPT_SHA_MISSING", "attempt_no": number})
        elif prompt_sha in seen:
            violations.append({
                "code": "PROMPT_UNCHANGED_RETRY",
                "attempt_no": number,
                "matches_attempt_no": seen[prompt_sha],
            })
        else:
            seen[str(prompt_sha)] = number

    if len(attempts) > MAX_ATTEMPTS:
        violations.append({"code": "ATTEMPT_CAP_EXCEEDED", "attempts": len(attempts)})

    passed = [row for row in attempts if str(row.get("qa_verdict") or "").upper() == "PASS"]
    exhausted = len(attempts) >= MAX_ATTEMPTS and not passed
    if exhausted:
        action = decision.get("action") if decision else None
        if not decision:
            violations.append({"code": "STALLED_NO_TERMINAL_DECISION"})
        elif action not in TERMINAL_DECISIONS:
            violations.append({"code": "INVALID_TERMINAL_DECISION", "got": action})
        else:
            p0 = {str(row.get("defect_class") or "").upper() for row in attempts} & P0_DEFECTS
            if action == "ADMIT_BEST_EFFORT":
                if p0:
                    violations.append({"code": "P0_CANNOT_BE_BEST_EFFORTED", "p0_defects": sorted(p0)})
                if not decision.get("selected_candidate_ref"):
                    violations.append({"code": "BEST_EFFORT_WITHOUT_SELECTION"})
                if not decision.get("selection_reason"):
                    violations.append({"code": "BEST_EFFORT_WITHOUT_REASON"})
            elif not decision.get("replacement_plan"):
                violations.append({"code": "SWITCH_WITHOUT_PLAN"})

    if passed:
        next_action = "PASS_ADMITTED"
    elif not attempts:
        next_action = "ATTEMPT_1"
    elif len(attempts) < MAX_ATTEMPTS:
        next_action = f"ATTEMPT_{len(attempts) + 1}_WITH_CHANGED_PROMPT"
    elif decision and decision.get("action") in TERMINAL_DECISIONS and not violations:
        next_action = f"TERMINAL_{decision['action']}"
    else:
        p0 = {str(row.get("defect_class") or "").upper() for row in attempts} & P0_DEFECTS
        next_action = "MUST_DECIDE_NOW: SWITCH_COVERAGE" if p0 else "MUST_DECIDE_NOW: ADMIT_BEST_EFFORT"

    return {
        "unit_id": unit.get("unit_id", "?"),
        "attempts_used": len(attempts),
        "max_attempts": MAX_ATTEMPTS,
        "any_pass": bool(passed),
        "attempts_exhausted": exhausted,
        "terminal_decision": decision.get("action") if decision else None,
        "violations": violations,
        "next_action": next_action,
        "verdict": "OK" if not violations else "RETRY_POLICY_VIOLATION",
    }


def evaluate(payload: dict) -> dict:
    results = [evaluate_unit(unit) for unit in payload.get("units") or []]
    return {
        "rule": "maximum three paid attempts per unit; terminal decision required",
        "units_checked": len(results),
        "units_violating": sum(row["verdict"] != "OK" for row in results),
        "units_stalled": sum(
            any(item["code"] == "STALLED_NO_TERMINAL_DECISION" for item in row["violations"])
            for row in results
        ),
        "results": results,
        "verdict": "OK" if all(row["verdict"] == "OK" for row in results) else "RETRY_POLICY_VIOLATION",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?")
    args = parser.parse_args(argv)
    raw = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    result = evaluate(json.loads(raw))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
