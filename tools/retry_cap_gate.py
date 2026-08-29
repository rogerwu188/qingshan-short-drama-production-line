#!/usr/bin/env python3
"""Enforce media-specific creative-attempt caps and durable failure memory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from video_generation_failure_policy import (
        MAX_CREATIVE_ATTEMPTS,
        max_creative_attempts,
        PROVIDER_FAILURE_CLASSES,
        evaluate_failure_workflow,
    )
except ImportError:
    from tools.video_generation_failure_policy import (
        MAX_CREATIVE_ATTEMPTS,
        max_creative_attempts,
        PROVIDER_FAILURE_CLASSES,
        evaluate_failure_workflow,
    )


MAX_ATTEMPTS = MAX_CREATIVE_ATTEMPTS
P0_DEFECTS = {
    "IDENTITY_DRIFT", "WRONG_CHARACTER", "COPYRIGHT", "RIGHTS_MISSING",
    "MEDIA_CORRUPT", "PLOT_BREAK", "MISSING_DIALOGUE", "NO_SUBTITLE",
}
TERMINAL_DECISIONS = {
    "ADMIT_BEST_EFFORT",
    "SWITCH_COVERAGE",
    "SCRIPT_EQUIVALENT_ADJUSTMENT",
}


def validate_submission_attempt(task: dict) -> list[str]:
    """Enforce the paid-attempt contract at provider entrypoints."""
    failures: list[str] = []
    raw_attempt = task.get("retry_attempt", 1)
    if not isinstance(raw_attempt, int) or isinstance(raw_attempt, bool):
        return ["RETRY_ATTEMPT_NOT_INTEGER"]
    attempt = int(raw_attempt)
    creative_attempt = task.get("creative_attempt_ordinal", task.get("paid_attempt_ordinal", attempt))
    if not isinstance(creative_attempt, int) or isinstance(creative_attempt, bool):
        return ["CREATIVE_ATTEMPT_ORDINAL_NOT_INTEGER"]
    attempt_limit = max_creative_attempts(task)
    if attempt < 1 or creative_attempt < 1 or creative_attempt > attempt_limit:
        return ["RETRY_ATTEMPT_CAP_EXCEEDED"]
    prior_classes = [str(value).upper() for value in task.get("prior_failure_classifications") or []]
    prior_provider_failure = bool(prior_classes and prior_classes[-1] in PROVIDER_FAILURE_CLASSES)
    if prior_provider_failure:
        if task.get("provider_resolution_status") != "VERIFIED_RESOLVED":
            failures.append("PROVIDER_FAILURE_REQUIRES_HUMAN_RESOLUTION")
        if not str(task.get("provider_resolution_ref") or "").strip():
            failures.append("PROVIDER_RESOLUTION_EVIDENCE_MISSING")
    if attempt > attempt_limit:
        if not prior_classes or any(value not in PROVIDER_FAILURE_CLASSES for value in prior_classes):
            failures.append("SUBMISSION_ATTEMPT_ABOVE_CAP_REQUIRES_PROVIDER_FAILURE_HISTORY")
    if attempt == 1:
        return failures
    if not task.get("failure_memory"):
        failures.append("RETRY_FAILURE_MEMORY_MISSING")
    if not str(task.get("material_change_from_prior_attempt") or "").strip():
        failures.append("RETRY_MATERIAL_CHANGE_MISSING")
    prior = [str(value) for value in task.get("prior_prompt_sha256") or [] if value]
    current = str(task.get("prompt_sha256") or "")
    if len(prior) < attempt - 1:
        failures.append("RETRY_PRIOR_PROMPT_HISTORY_INCOMPLETE")
    if not current:
        failures.append("RETRY_CURRENT_PROMPT_SHA_MISSING")
    elif current in prior:
        failures.append("PROMPT_UNCHANGED_RETRY")
    if creative_attempt == attempt_limit and task.get("no_further_automatic_retry") is not True:
        failures.append("FINAL_ATTEMPT_MUST_CLOSE_AUTOMATIC_RETRY")
    return failures


def evaluate_unit(unit: dict) -> dict:
    attempt_limit = max_creative_attempts(unit)
    attempts = unit.get("attempts") or []
    decision = unit.get("terminal_decision")
    violations: list[dict] = []
    workflow = evaluate_failure_workflow(unit)
    violations.extend(workflow["violations"])
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

    if workflow["creative_attempt_count"] > attempt_limit:
        violations.append({
            "code": "ATTEMPT_CAP_EXCEEDED",
            "attempts": workflow["creative_attempt_count"],
        })

    passed = workflow["any_pass"]
    exhausted = workflow["creative_attempt_count"] >= attempt_limit and not passed
    if exhausted:
        action = decision.get("action") if decision else None
        if not decision:
            violations.append({"code": "STALLED_NO_TERMINAL_DECISION"})
        elif not decision.get("human_approval_ref"):
            violations.append({"code": "THREE_FAILED_PROMPTS_REQUIRE_HUMAN_APPROVAL"})
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
            elif action == "SWITCH_COVERAGE" and not decision.get("replacement_plan"):
                violations.append({"code": "SWITCH_WITHOUT_PLAN"})

    next_action = workflow["next_action"]
    if exhausted and decision and decision.get("action") in TERMINAL_DECISIONS and not violations:
        next_action = f"TERMINAL_{decision['action']}"

    return {
        "unit_id": unit.get("unit_id", "?"),
        "attempts_used": workflow["creative_attempt_count"],
        "submission_attempt_count": workflow["submission_attempt_count"],
        "paid_attempt_count": workflow["paid_attempt_count"],
        "provider_failure_count": workflow["provider_failure_count"],
        "attempt_classifications": workflow["attempt_classifications"],
        "max_attempts": attempt_limit,
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
        "rule": "maximum ten image attempts or three video attempts per unit; terminal decision required",
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
