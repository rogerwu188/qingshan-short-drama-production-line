#!/usr/bin/env python3
"""Decide whether an automatic source reroll is allowed by the cost policy."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

try:
    from video_generation_failure_policy import PROVIDER_FAILURE_CLASSES
except ImportError:
    from tools.video_generation_failure_policy import PROVIDER_FAILURE_CLASSES


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


LEDGER_SCHEMA = "qingshan.reroll_ledger.v1"


def load_ledger(path: Path) -> dict:
    return load_json(path) or {"schema": LEDGER_SCHEMA, "events": []}


def record_reroll_event(
    ledger: dict,
    *,
    shot_id: str,
    reroll_number: int,
    failure_reason: str,
    failure_class: str = "CANDIDATE_QA_FAILURE",
    outcome: str,
    recorded_at: str,
    net_charged_credits: int | None = None,
    extra: dict | None = None,
) -> dict:
    """Append one reroll event to the ledger.

    ``evaluate`` has always *read* ``ledger["events"]`` to compute the per-shot
    reroll number, the episode reroll budget and the repeated-reason rule, but
    nothing in the repository ever wrote one: every caller passed a ledger whose
    ``events`` list was empty, so ``reroll_number`` was always 1, the episode
    budget never advanced, and the repeated-reason rule could never fire.  The
    writer lives here, next to the reader, so the two cannot drift.
    """
    events = ledger.setdefault("events", [])
    if not isinstance(events, list):
        raise ValueError("reroll ledger 'events' must be a list")
    event: dict = {
        "shot_id": str(shot_id),
        "reroll_number": int(reroll_number),
        "failure_reason": str(failure_reason),
        "failure_class": str(failure_class or "").upper(),
        "outcome": str(outcome).upper(),
        "recorded_at": str(recorded_at),
    }
    if net_charged_credits is not None:
        event["net_charged_credits"] = int(net_charged_credits)
    for key, value in (extra or {}).items():
        event.setdefault(str(key), value)
    events.append(event)
    ledger["schema"] = str(ledger.get("schema") or LEDGER_SCHEMA)
    ledger["event_count"] = len(events)
    return event


def reroll_number_for(ledger: dict, shot_id: str) -> int:
    """The ordinal this shot's next paid reroll will be, counting prior attempts."""
    events = ledger.get("events") or []
    prior = sum(
        1 for event in events
        if str(event.get("shot_id") or "") == str(shot_id)
        and str(event.get("outcome") or "").upper() in {"SUBMITTED", "COMPLETED"}
    )
    return prior + 1


def evaluate(
    policy: dict,
    ledger: dict,
    *,
    shot_id: str,
    reroll_number: int,
    failure_tier: str,
    failure_reason: str,
    total_paid_tasks: int,
    failure_class: str = "CANDIDATE_QA_FAILURE",
    provider_resolution_status: str | None = None,
    provider_resolution_ref: str | None = None,
) -> dict:
    failures = []
    warnings = []
    events = ledger.get("events", [])

    normalized_class = str(failure_class or "").upper()
    provider_failure = normalized_class in PROVIDER_FAILURE_CLASSES

    if provider_failure and (
        provider_resolution_status != "VERIFIED_RESOLVED"
        or not str(provider_resolution_ref or "").strip()
    ):
        failures.append("PROVIDER_FAILURE_REQUIRES_HUMAN_RESOLUTION")
    elif not provider_failure and failure_tier == "ADVISE":
        failures.append("ADVISE_FAILURE_MUST_NOT_AUTO_REROLL")
    elif not provider_failure and failure_tier != "BLOCK":
        failures.append("UNKNOWN_FAILURE_TIER")

    max_per_shot = int(policy["max_rerolls_per_shot"])
    if not provider_failure and reroll_number > max_per_shot:
        failures.append("PER_SHOT_REROLL_LIMIT_EXCEEDED")

    paid_reroll_events = [
        event for event in events
        if event.get("outcome") in {"SUBMITTED", "COMPLETED"}
        and str(event.get("failure_class") or "").upper() not in PROVIDER_FAILURE_CLASSES
        and event.get("net_charged_credits", event.get("actual_charged_credits", 1)) != 0
    ]
    paid_reroll_count_after_submit = len(paid_reroll_events) + (0 if provider_failure else 1)
    max_paid_rerolls = max(
        1, math.floor(total_paid_tasks * float(policy["episode_reroll_shot_fraction"]))
    )
    if not provider_failure and paid_reroll_count_after_submit > max_paid_rerolls:
        failures.append("EPISODE_REROLL_BUDGET_EXCEEDED")

    recent_same_reason = []
    for event in reversed(events):
        if event.get("failure_reason") != failure_reason:
            break
        if event.get("shot_id") not in recent_same_reason:
            recent_same_reason.append(event.get("shot_id"))
    if (
        not provider_failure
        and len(recent_same_reason)
        >= int(policy["same_reason_distinct_shot_limit"])
        and shot_id not in recent_same_reason
    ):
        failures.append("REPEATED_REASON_REQUIRES_PROMPT_OR_ASSET_FIX")

    if not provider_failure and reroll_number == max_per_shot:
        warnings.append("FINAL_AUTOMATIC_REROLL_FOR_SHOT")
    if provider_failure:
        warnings.append("PROVIDER_FAILURE_DOES_NOT_CONSUM_CREATIVE_OR_PAID_REROLL")

    # block_failure_classes: the named objective defect classes the policy owner
    # decided must block.  It was declared in the policy file and read by
    # nothing, so a run could not tell a class the policy blocks from one it
    # merely dislikes.  Read here; the failure class is matched on its own
    # name, and membership is reported so the caller need not re-read policy.
    block_classes = {
        str(value).upper() for value in policy.get("block_failure_classes") or []
    }
    policy_blocks_this_class = bool(block_classes) and normalized_class in block_classes
    if policy_blocks_this_class and not provider_failure and failure_tier != "BLOCK":
        failures.append("POLICY_BLOCK_CLASS_REQUIRES_BLOCK_TIER")

    # advise_margin_fraction: how close to the episode reroll budget an ADVISE
    # decision may run before it stops advising.  Also declared and unread.
    margin_fraction = float(policy.get("advise_margin_fraction") or 0)
    budget_headroom_ratio = (
        (max_paid_rerolls - paid_reroll_count_after_submit) / max_paid_rerolls
        if max_paid_rerolls else 0.0
    )
    if (
        not provider_failure
        and failure_tier == "ADVISE"
        and budget_headroom_ratio < margin_fraction
    ):
        warnings.append("ADVISE_WITHIN_EPISODE_REROLL_MARGIN")

    return {
        "schema": "qingshan.reroll_cost_guard_result.v1",
        "status": (
            "PASS_PROVIDER_RESOLVED_RETRY_ALLOWED"
            if provider_failure and not failures
            else "PASS_AUTO_REROLL_ALLOWED"
            if not failures
            else "BLOCK_AUTO_REROLL"
        ),
        "shot_id": shot_id,
        "reroll_number": reroll_number,
        "failure_tier": failure_tier,
        "failure_reason": failure_reason,
        "failure_class": normalized_class,
        "provider_resolution_status": provider_resolution_status,
        "provider_resolution_ref": provider_resolution_ref,
        "episode_paid_reroll_count_after_submit": paid_reroll_count_after_submit,
        "episode_paid_reroll_limit": max_paid_rerolls,
        "episode_total_paid_task_count": total_paid_tasks,
        "policy_block_failure_classes": sorted(block_classes),
        "policy_blocks_this_failure_class": policy_blocks_this_class,
        "episode_budget_headroom_ratio": round(budget_headroom_ratio, 6),
        "failures": failures,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--shot-id", required=True)
    parser.add_argument("--reroll-number", required=True, type=int)
    parser.add_argument("--failure-tier", required=True, choices=["BLOCK", "ADVISE"])
    parser.add_argument("--failure-reason", required=True)
    parser.add_argument("--total-paid-tasks", required=True, type=int)
    parser.add_argument("--failure-class", default="CANDIDATE_QA_FAILURE")
    parser.add_argument("--provider-resolution-status")
    parser.add_argument("--provider-resolution-ref")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    result = evaluate(
        load_json(Path(args.policy)),
        load_json(Path(args.ledger)),
        shot_id=args.shot_id,
        reroll_number=args.reroll_number,
        failure_tier=args.failure_tier,
        failure_reason=args.failure_reason,
        total_paid_tasks=args.total_paid_tasks,
        failure_class=args.failure_class,
        provider_resolution_status=args.provider_resolution_status,
        provider_resolution_ref=args.provider_resolution_ref,
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
