#!/usr/bin/env python3
"""Decide whether an automatic source reroll is allowed by the cost policy."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(
    policy: dict,
    ledger: dict,
    *,
    shot_id: str,
    reroll_number: int,
    failure_tier: str,
    failure_reason: str,
    total_paid_tasks: int,
) -> dict:
    failures = []
    warnings = []
    events = ledger.get("events", [])

    if failure_tier == "ADVISE":
        failures.append("ADVISE_FAILURE_MUST_NOT_AUTO_REROLL")
    elif failure_tier != "BLOCK":
        failures.append("UNKNOWN_FAILURE_TIER")

    max_per_shot = int(policy["max_rerolls_per_shot"])
    if reroll_number > max_per_shot:
        failures.append("PER_SHOT_REROLL_LIMIT_EXCEEDED")

    paid_reroll_events = [
        event for event in events
        if event.get("outcome") in {"SUBMITTED", "COMPLETED"}
    ]
    paid_reroll_count_after_submit = len(paid_reroll_events) + 1
    max_paid_rerolls = max(
        1, math.floor(total_paid_tasks * float(policy["episode_reroll_shot_fraction"]))
    )
    if paid_reroll_count_after_submit > max_paid_rerolls:
        failures.append("EPISODE_REROLL_BUDGET_EXCEEDED")

    recent_same_reason = []
    for event in reversed(events):
        if event.get("failure_reason") != failure_reason:
            break
        if event.get("shot_id") not in recent_same_reason:
            recent_same_reason.append(event.get("shot_id"))
    if (
        len(recent_same_reason)
        >= int(policy["same_reason_distinct_shot_limit"])
        and shot_id not in recent_same_reason
    ):
        failures.append("REPEATED_REASON_REQUIRES_PROMPT_OR_ASSET_FIX")

    if reroll_number == max_per_shot:
        warnings.append("FINAL_AUTOMATIC_REROLL_FOR_SHOT")

    return {
        "schema": "qingshan.reroll_cost_guard_result.v1",
        "status": "PASS_AUTO_REROLL_ALLOWED" if not failures else "BLOCK_AUTO_REROLL",
        "shot_id": shot_id,
        "reroll_number": reroll_number,
        "failure_tier": failure_tier,
        "failure_reason": failure_reason,
        "episode_paid_reroll_count_after_submit": paid_reroll_count_after_submit,
        "episode_paid_reroll_limit": max_paid_rerolls,
        "episode_total_paid_task_count": total_paid_tasks,
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
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS_AUTO_REROLL_ALLOWED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
