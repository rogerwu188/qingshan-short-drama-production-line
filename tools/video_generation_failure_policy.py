#!/usr/bin/env python3
"""Classify media-generation failures and select the only safe successor.

Provider failures stop the line for human resolution.  With a healthy provider,
prompt/candidate failures automatically rewrite the prompt up to the media cap:
ten attempts for still images/keyframes and three attempts for video.
"""

from __future__ import annotations

import argparse
import json
from typing import Any
from pathlib import Path
import sys


MAX_VIDEO_CREATIVE_ATTEMPTS = 3
MAX_IMAGE_CREATIVE_ATTEMPTS = 10
# Backwards-compatible import used by video-only callers.
MAX_CREATIVE_ATTEMPTS = MAX_VIDEO_CREATIVE_ATTEMPTS

PROVIDER_FAILURE_CLASSES = frozenset({
    "PROVIDER_TRANSPORT_FAILURE",
    "PROVIDER_TRANSIENT_FAILURE",
    "PROVIDER_INSUFFICIENT_CREDITS",
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
INSUFFICIENT_CREDIT_TERMS = (
    "insufficient credit",
    "insufficient credits",
    "insufficient balance",
    "not enough credit",
    "not enough credits",
    "credit balance too low",
    "余额不足",
    "积分不足",
    "额度不足",
)
PROMPT_REJECTION_TERMS = (
    "prompt rejected",
    "content policy",
    "safety policy",
    "moderation",
    "unsafe prompt",
    "invalid prompt",
)


def media_kind(payload: dict[str, Any]) -> str:
    """Return IMAGE only when the payload explicitly identifies still generation."""
    declared = " ".join(
        str(payload.get(key) or "")
        for key in ("media_type", "generation_type", "generation_stage", "deliverable_type")
    ).upper()
    if any(token in declared for token in ("IMAGE", "KEYFRAME", "STILL")):
        return "IMAGE"
    if "VIDEO" in declared:
        return "VIDEO"
    for attempt in payload.get("attempts") or []:
        candidate = str(attempt.get("output_path") or attempt.get("candidate_ref") or "").lower()
        if candidate.endswith((".png", ".jpg", ".jpeg", ".webp")):
            return "IMAGE"
    return "VIDEO"


def max_creative_attempts(payload: dict[str, Any]) -> int:
    return MAX_IMAGE_CREATIVE_ATTEMPTS if media_kind(payload) == "IMAGE" else MAX_VIDEO_CREATIVE_ATTEMPTS


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
    if any(term in text for term in INSUFFICIENT_CREDIT_TERMS):
        return "PROVIDER_INSUFFICIENT_CREDITS"
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


def prompt_failure_record(attempt: dict[str, Any]) -> dict[str, Any]:
    reason = (
        attempt.get("prompt_failure_reason")
        or attempt.get("failure_reason")
        or attempt.get("defect_class")
        or attempt.get("err_msg")
        or attempt.get("error")
        or "UNSPECIFIED_GENERATION_FAILURE"
    )
    do_not_repeat = attempt.get("do_not_repeat") or attempt.get("failure_memory")
    return {
        "attempt_no": attempt.get("attempt_no", attempt.get("attempt")),
        "prompt_sha256": attempt.get("prompt_sha256"),
        "failure_class": classify_attempt(attempt),
        "failure_reason": str(reason),
        "do_not_repeat": do_not_repeat,
    }


def evaluate_failure_workflow(unit: dict[str, Any]) -> dict[str, Any]:
    kind = media_kind(unit)
    attempt_limit = max_creative_attempts(unit)
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
    provider_resolution = unit.get("provider_resolution") or {}
    provider_resolved = (
        provider_resolution.get("status") == "VERIFIED_RESOLVED"
        and bool(provider_resolution.get("evidence_ref"))
    )
    prompt_failures = [
        prompt_failure_record(attempt)
        for attempt in attempts
        if classify_attempt(attempt) in CREATIVE_FAILURE_CLASSES
    ]
    prompt_memory_failures: list[dict[str, Any]] = []
    for record in prompt_failures:
        if not record["prompt_sha256"]:
            prompt_memory_failures.append({
                "code": "FAILED_PROMPT_SHA_MISSING",
                "attempt_no": record["attempt_no"],
            })
        if record["failure_reason"] == "UNSPECIFIED_GENERATION_FAILURE":
            prompt_memory_failures.append({
                "code": "PROMPT_FAILURE_REASON_MISSING",
                "attempt_no": record["attempt_no"],
            })
        if not record["do_not_repeat"]:
            prompt_memory_failures.append({
                "code": "PROMPT_DO_NOT_REPEAT_RULE_MISSING",
                "attempt_no": record["attempt_no"],
            })
    violations.extend(prompt_memory_failures)

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
    elif latest_class in PROVIDER_FAILURE_CLASSES and not provider_resolved:
        next_action = "BLOCKED_ON_INPUT_PROVIDER_FAILURE_REQUIRES_HUMAN"
    elif latest_class in PROVIDER_FAILURE_CLASSES:
        next_action = "RESUME_GENERATION_AFTER_VERIFIED_PROVIDER_RESOLUTION"
    elif latest_class == UNKNOWN_CLASS:
        next_action = "BLOCKED_ON_INPUT_UNKNOWN_FAILURE_REQUIRES_HUMAN"
    elif prompt_memory_failures:
        next_action = "BLOCKED_ON_INPUT_PROMPT_FAILURE_MEMORY_INCOMPLETE"
    elif creative_count < attempt_limit:
        next_action = f"AUTO_REWRITE_PROMPT_AND_SUBMIT_ATTEMPT_{creative_count + 1}"
    elif action and decision.get("human_approval_ref") and not violations:
        next_action = f"TERMINAL_{action}"
    else:
        next_action = "BLOCKED_ON_INPUT_PROMPT_ATTEMPTS_EXHAUSTED_REQUIRES_HUMAN"

    if any_pass or not attempts or next_action.startswith("AUTO_REWRITE_") or next_action.startswith("RESUME_"):
        status = "PASS"
    elif next_action.startswith("BLOCKED_ON_INPUT_PROVIDER_FAILURE"):
        status = "BLOCKED_ON_INPUT_PROVIDER_FAILURE"
    elif next_action.startswith("BLOCKED_ON_INPUT_PROMPT_ATTEMPTS"):
        status = "BLOCKED_ON_INPUT_PROMPT_ATTEMPTS_EXHAUSTED"
    elif next_action.startswith("BLOCKED_ON_INPUT_UNKNOWN"):
        status = "BLOCKED_ON_INPUT_UNKNOWN_FAILURE"
    elif next_action.startswith("BLOCKED_ON_INPUT_PROMPT_FAILURE_MEMORY"):
        status = "BLOCKED_ON_INPUT_PROMPT_FAILURE_MEMORY_INCOMPLETE"
    else:
        status = "BLOCK_INVALID_SUCCESSOR" if violations else "PASS"

    if latest_class in PROVIDER_FAILURE_CLASSES and not provider_resolved:
        required_fields = ["status=VERIFIED_RESOLVED", "evidence_ref"]
        if latest_class == "PROVIDER_INSUFFICIENT_CREDITS":
            required_fields.append("credits_restored=true")
        notification = {
            "notify_human": True,
            "reason": "Provider failure stopped all downstream work until verified resolution.",
            "provider_failure_class": latest_class,
            "required_resolution_fields": required_fields,
        }
    elif creative_count >= attempt_limit and not any_pass:
        notification = {
            "notify_human": True,
            "reason": f"{attempt_limit} provider-healthy {kind.lower()} generation attempts failed.",
            "prompt_failure_records": prompt_failures,
        }
    else:
        notification = {"notify_human": False}

    rewrite_contract = None
    if next_action.startswith("AUTO_REWRITE_PROMPT_AND_SUBMIT_ATTEMPT_"):
        rewrite_contract = {
            "next_creative_attempt": creative_count + 1,
            "forbidden_prompt_sha256": [row["prompt_sha256"] for row in prompt_failures],
            "must_fix_reasons": [row["failure_reason"] for row in prompt_failures],
            "do_not_repeat": [row["do_not_repeat"] for row in prompt_failures],
            "material_change_required": True,
            "canonical_story_and_native_audio_must_be_preserved": True,
        }

    return {
        "schema": "qingshan.media_generation_failure_workflow.v3",
        "media_kind": kind,
        "creative_attempt_limit": attempt_limit,
        "status": status,
        "attempt_classifications": rows,
        "submission_attempt_count": len(rows),
        "paid_attempt_count": paid_count,
        "creative_attempt_count": creative_count,
        "provider_failure_count": provider_count,
        "latest_failure_class": latest_class,
        "provider_resolved": provider_resolved,
        "prompt_failure_records": prompt_failures,
        "human_notification": notification,
        "prompt_rewrite_contract": rewrite_contract,
        "any_pass": any_pass,
        "next_action": next_action,
        "violations": violations,
        "automatic_fallback_eligible": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?")
    args = parser.parse_args(argv)
    raw = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    result = evaluate_failure_workflow(json.loads(raw))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 3 if result["status"].startswith("BLOCKED_ON_INPUT") else 2


if __name__ == "__main__":
    raise SystemExit(main())
