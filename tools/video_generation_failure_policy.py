#!/usr/bin/env python3
"""Classify video-generation failures and select the only safe successor.

Provider transport/capacity failures are not creative failures.  They must not
consume a paid/creative attempt or automatically authorize editorial coverage.
"""

from __future__ import annotations

import argparse
import json
from typing import Any
from pathlib import Path
import sys


MAX_CREATIVE_ATTEMPTS = 3

PROVIDER_FAILURE_CLASSES = frozenset({
    "PROVIDER_TRANSPORT_FAILURE",
    "PROVIDER_TRANSIENT_FAILURE",
    "SUBMISSION_NOT_ACCEPTED",
})
CREATIVE_FAILURE_CLASSES = frozenset({
    "PROMPT_OR_POLICY_REJECTION",
    "CANDIDATE_QA_FAILURE",
    "CANDIDATE_TECHNICAL_FAILURE",
})
SUCCESS_CLASS = "CANDIDATE_SUCCESS"
UNKNOWN_CLASS = "UNKNOWN_FAILURE_REQUIRES_ADJUDICATION"

TRANSPORT_TERMS = (
    "router mapping not found",
    "route not found",
    "routing error",
    "unsupported route",
    "asset mapping",
    "missing task_id",
    "missing task id",
    "no task_id",
    "no task id",
    "response lost",
)
TRANSIENT_TERMS = (
    "provider timeout",
    "upstream timeout",
    "timed out",
    "timeout",
    "overloaded",
    "capacity",
    "rate limit",
    "temporarily unavailable",
    "internal server error",
    "bad gateway",
    "service unavailable",
)
PROMPT_REJECTION_TERMS = (
    "prompt rejected",
    "content policy",
    "safety policy",
    "moderation",
    "unsafe prompt",
    "invalid prompt",
)


def _failure_text(attempt: dict[str, Any]) -> str:
    values = [
        attempt.get("provider_error"),
        attempt.get("terminal_error"),
        attempt.get("err_msg"),
        attempt.get("error"),
        attempt.get("failure_reason"),
        attempt.get("message"),
    ]
    return " ".join(str(value) for value in values if value).casefold()


def has_candidate(attempt: dict[str, Any]) -> bool:
    remote_status = str(attempt.get("remote_status") or attempt.get("status") or "").casefold()
    return bool(
        attempt.get("output_path")
        or attempt.get("candidate_ref")
        or attempt.get("media_sha256")
        or attempt.get("sha256") and remote_status in {"completed", "complete", "success"}
        or remote_status in {"completed", "complete", "success"}
    )


def classify_attempt(attempt: dict[str, Any]) -> str:
    explicit = str(attempt.get("failure_class") or "").upper()
    known = PROVIDER_FAILURE_CLASSES | CREATIVE_FAILURE_CLASSES | {SUCCESS_CLASS, UNKNOWN_CLASS}
    if explicit in known:
        return explicit

    qa = str(attempt.get("qa_verdict") or "").upper()
    if has_candidate(attempt):
        if qa == "PASS" or attempt.get("success") is True:
            return SUCCESS_CLASS
        if str(attempt.get("defect_class") or "").upper() in {"MEDIA_CORRUPT", "DECODE_FAIL"}:
            return "CANDIDATE_TECHNICAL_FAILURE"
        return "CANDIDATE_QA_FAILURE"

    text = _failure_text(attempt)
    if any(term in text for term in TRANSPORT_TERMS):
        return "PROVIDER_TRANSPORT_FAILURE"
    if any(term in text for term in TRANSIENT_TERMS):
        return "PROVIDER_TRANSIENT_FAILURE"
    if any(term in text for term in PROMPT_REJECTION_TERMS):
        return "PROMPT_OR_POLICY_REJECTION"

    state = str(attempt.get("state") or attempt.get("status") or "").casefold()
    if not attempt.get("task_id") and state in {
        "submit_failed",
        "submit_failed_terminal",
        "response_lost_pending_ledger_reconciliation",
    }:
        return "SUBMISSION_NOT_ACCEPTED"

    # Legacy retry-cap inputs represented a reviewed candidate only by QA fields.
    if qa in {"FAIL", "BLOCK"} or attempt.get("defect_class"):
        return "CANDIDATE_QA_FAILURE"
    if qa == "PASS" or attempt.get("success") is True:
        return SUCCESS_CLASS
    return UNKNOWN_CLASS


def net_charged_credits(attempt: dict[str, Any]) -> float | None:
    for key in ("net_charged_credits", "actual_charged_credits", "net_credits"):
        value = attempt.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    paid = attempt.get("paid_credits")
    refunded = attempt.get("refunded_credits")
    if isinstance(paid, (int, float)) and isinstance(refunded, (int, float)):
        return float(paid) - float(refunded)
    charge_status = str(attempt.get("charge_status") or "").upper()
    if "ZERO" in charge_status or "REFUND" in charge_status:
        return 0.0
    return None


def consumes_paid_attempt(attempt: dict[str, Any]) -> bool:
    charged = net_charged_credits(attempt)
    if charged is not None:
        return charged > 0
    classification = classify_attempt(attempt)
    # Preserve legacy reviewed-candidate accounting when old evidence omitted billing.
    return classification in CREATIVE_FAILURE_CLASSES | {SUCCESS_CLASS}


def consumes_creative_attempt(attempt: dict[str, Any]) -> bool:
    return classify_attempt(attempt) in CREATIVE_FAILURE_CLASSES | {SUCCESS_CLASS}


def evaluate_failure_workflow(unit: dict[str, Any]) -> dict[str, Any]:
    attempts = list(unit.get("attempts") or [])
    rows = [
        {
            "attempt_no": row.get("attempt_no", row.get("attempt")),
            "task_id": row.get("task_id"),
            "failure_class": classify_attempt(row),
            "net_charged_credits": net_charged_credits(row),
            "consumes_paid_attempt": consumes_paid_attempt(row),
            "consumes_creative_attempt": consumes_creative_attempt(row),
        }
        for row in attempts
    ]
    paid_count = sum(row["consumes_paid_attempt"] for row in rows)
    creative_count = sum(row["consumes_creative_attempt"] for row in rows)
    provider_count = sum(row["failure_class"] in PROVIDER_FAILURE_CLASSES for row in rows)
    any_pass = any(row["failure_class"] == SUCCESS_CLASS for row in rows)
    latest_class = rows[-1]["failure_class"] if rows else None
    decision = unit.get("terminal_decision") or {}
    action = decision.get("action")
    violations: list[dict[str, Any]] = []

    if latest_class in PROVIDER_FAILURE_CLASSES and action in {
        "SWITCH_COVERAGE",
        "SCRIPT_EQUIVALENT_ADJUSTMENT",
        "ADMIT_BEST_EFFORT",
    }:
        violations.append({"code": "PROVIDER_FAILURE_CANNOT_TRIGGER_CREATIVE_FALLBACK"})

    if action == "SCRIPT_EQUIVALENT_ADJUSTMENT":
        if not decision.get("human_approval_ref"):
            violations.append({"code": "SCRIPT_EQUIVALENT_REQUIRES_EXPLICIT_HUMAN_APPROVAL"})
        if decision.get("retires_spoken_dialogue") and not decision.get("dialogue_retirement_approval_ref"):
            violations.append({"code": "DIALOGUE_RETIREMENT_REQUIRES_EXPLICIT_HUMAN_APPROVAL"})

    if action == "SWITCH_COVERAGE" and decision.get("preserves_spoken_dialogue") is False:
        if not decision.get("dialogue_retirement_approval_ref"):
            violations.append({"code": "COVERAGE_CANNOT_SILENTLY_RETIRE_DIALOGUE"})

    if any_pass:
        next_action = "PASS_ADMITTED"
    elif not attempts:
        next_action = "ATTEMPT_1"
    elif latest_class in PROVIDER_FAILURE_CLASSES:
        next_action = "RETRY_AFTER_PROVIDER_RECOVERY_WITH_CHANGED_PROMPT_OR_TRANSPORT"
    elif latest_class == "PROMPT_OR_POLICY_REJECTION":
        next_action = "RETRY_WITH_MATERIALLY_CHANGED_PROMPT"
    elif latest_class == UNKNOWN_CLASS:
        next_action = "HUMAN_ADJUDICATION_REQUIRED_UNKNOWN_FAILURE"
    elif creative_count < MAX_CREATIVE_ATTEMPTS:
        next_action = f"ATTEMPT_{creative_count + 1}_WITH_CHANGED_PROMPT"
    elif not action:
        next_action = "HUMAN_DECISION_REQUIRED_AFTER_THREE_REAL_CREATIVE_ATTEMPTS"
    elif not violations:
        next_action = f"TERMINAL_{action}"
    else:
        next_action = "BLOCK_INVALID_FALLBACK"

    return {
        "schema": "qingshan.video_generation_failure_workflow.v1",
        "status": "PASS" if not violations else "BLOCK_INVALID_SUCCESSOR",
        "attempt_classifications": rows,
        "submission_attempt_count": len(rows),
        "paid_attempt_count": paid_count,
        "creative_attempt_count": creative_count,
        "provider_failure_count": provider_count,
        "latest_failure_class": latest_class,
        "any_pass": any_pass,
        "next_action": next_action,
        "violations": violations,
        "fallback_eligible": creative_count >= MAX_CREATIVE_ATTEMPTS and provider_count == 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?")
    args = parser.parse_args(argv)
    raw = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    result = evaluate_failure_workflow(json.loads(raw))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
