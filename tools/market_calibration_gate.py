#!/usr/bin/env python3
"""Validate market-learning evidence without allowing metrics to rewrite plot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_ENTRY_FIELDS = {
    "episode",
    "variable",
    "hypothesis",
    "expected_direction",
    "decision_window",
    "plays",
    "result",
    "inference_status",
}


def validate(
    policy: dict[str, Any],
    ledger: dict[str, Any],
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    evidence = policy.get("evidence_policy") or {}
    minimum_plays = int(evidence.get("minimum_plays_for_inference", 500))
    required_same_direction = int(
        evidence.get("same_direction_hypotheses_required", 3)
    )
    max_episodes = int(
        evidence.get("maximum_episodes_affected_per_change", 5)
    )
    allowed_fields = set(
        (policy.get("performance_layer") or {}).get("allowed_fields") or []
    )
    frozen_fields = set((policy.get("event_layer") or {}).get("frozen_fields") or [])

    eligible_by_direction: dict[str, int] = {}
    entries = ledger.get("entries") or []
    if not entries:
        failures.append("hypothesis_ledger_empty")
    for index, entry in enumerate(entries, start=1):
        episode = str(entry.get("episode") or index)
        for field in sorted(REQUIRED_ENTRY_FIELDS - set(entry)):
            failures.append(f"entry_missing_field:{episode}:{field}")
        if entry.get("decision_window") != evidence.get("decision_window", "T+72h"):
            failures.append(f"invalid_decision_window:{episode}")
        plays = int(entry.get("plays", 0) or 0)
        status = str(entry.get("inference_status") or "")
        if plays < minimum_plays:
            if status != "RECORD_ONLY_INSUFFICIENT_SAMPLE":
                failures.append(f"low_sample_must_be_record_only:{episode}")
        elif status == "DECISION_ELIGIBLE":
            direction = str(entry.get("expected_direction") or "")
            eligible_by_direction[direction] = eligible_by_direction.get(direction, 0) + 1

    if proposal:
        changed_fields = set(proposal.get("changed_fields") or [])
        event_changes = changed_fields & frozen_fields
        if event_changes and not proposal.get("roger_event_change_approval_ref"):
            failures.append(
                "event_layer_change_without_roger_approval:"
                + ",".join(sorted(event_changes))
            )
        unsupported = changed_fields - allowed_fields - frozen_fields
        if unsupported:
            failures.append(
                "unsupported_market_tunable_field:" + ",".join(sorted(unsupported))
            )
        affected = proposal.get("affected_episodes") or []
        if len(affected) > max_episodes:
            failures.append(
                f"affected_episode_limit_exceeded:{len(affected)}:{max_episodes}"
            )
        direction = str(proposal.get("evidence_direction") or "")
        count = eligible_by_direction.get(direction, 0)
        if count < required_same_direction:
            failures.append(
                f"same_direction_evidence_below_minimum:{count}:{required_same_direction}"
            )
        required_approvals = policy.get("approval_chain") or []
        approvals = proposal.get("approvals") or {}
        for approval in required_approvals:
            if not approvals.get(approval):
                failures.append(f"approval_missing:{approval}")

    return {
        "schema": "qingshan.market_calibration_gate_report.v1",
        "status": "PASS" if not failures else "FAIL",
        "entry_count": len(entries),
        "minimum_plays_for_inference": minimum_plays,
        "eligible_evidence_by_direction": eligible_by_direction,
        "proposal_checked": proposal is not None,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--proposal")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    proposal = (
        json.loads(Path(args.proposal).read_text(encoding="utf-8"))
        if args.proposal
        else None
    )
    report = validate(policy, ledger, proposal)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
