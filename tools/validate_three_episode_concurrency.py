#!/usr/bin/env python3
"""Validate the effective episode allocation, including Roger-authorized overrides."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def validate(policy: dict, ledger: dict) -> list[str]:
    errors: list[str] = []
    runtime_override = policy.get("runtime_override") or policy.get("active_override") or {}
    target = runtime_override.get(
        "target_concurrent_episode_lines",
        policy.get("target_concurrent_episode_lines"),
    )
    slots = policy.get("current_slots") or []
    lines = ledger.get("parallel_lines") or []
    if not isinstance(target, int) or target < 1:
        errors.append("target_concurrent_episode_lines_invalid")
        target = 0
    if len(slots) != target:
        errors.append("current_slot_count_mismatch")
    slot_episodes = [row.get("episode") for row in slots]
    if len(set(slot_episodes)) != len(slot_episodes):
        errors.append("duplicate_episode_slot")
    line_by_episode = {row.get("episode"): row for row in lines}
    for episode in slot_episodes:
        line = line_by_episode.get(episode)
        if not line:
            errors.append(f"missing_parallel_line:{episode}")
            continue
        has_work = bool(line.get("active_work"))
        has_blocker = bool(line.get("blocked_by") and line.get("blocker_ref"))
        if not (has_work or has_blocker):
            errors.append(f"line_has_neither_work_nor_blocker:{episode}")

    slot_history = policy.get("slot_refill_history") or []
    release_gate = policy.get("slot_release_gate") or {}
    required_evidence = release_gate.get("required_evidence") or []
    for refill in slot_history:
        if refill.get("reason") == "AUTHORIZED_REMOVAL":
            continue
        if refill.get("previous_episode_status") != release_gate.get("required_status", "RELEASED"):
            errors.append(f"refill_before_release:{refill.get('incoming_episode')}")
        evidence = refill.get("release_evidence") or {}
        missing = [key for key in required_evidence if not evidence.get(key)]
        if missing:
            errors.append(
                f"refill_missing_release_evidence:{refill.get('incoming_episode')}:" + ",".join(missing)
            )
    override = policy.get("active_override")
    if override:
        required = set((policy.get("override_policy") or {}).get("required_fields") or [])
        missing = sorted(field for field in required if not override.get(field))
        if missing:
            errors.append("override_missing_fields:" + ",".join(missing))
        roles = set((policy.get("override_policy") or {}).get("allowed_roles") or [])
        if override.get("authorized_role") not in roles:
            errors.append("override_role_not_authorized")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        default=str(ROOT / "workflow/production_line/THREE_EPISODE_CONCURRENCY_POLICY.json"),
    )
    parser.add_argument(
        "--ledger",
        default=str(ROOT / "workflow/production_line/ACTIVE_EPISODE_LINES_LATEST.json"),
    )
    parser.add_argument("--out")
    args = parser.parse_args()
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    errors = validate(policy, ledger)
    report = {"status": "PASS" if not errors else "FAIL", "errors": errors}
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
