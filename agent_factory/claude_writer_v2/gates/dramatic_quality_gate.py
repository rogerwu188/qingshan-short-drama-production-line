#!/usr/bin/env python3
"""Enforce the script council, canonical US-drama techniques, and fight floor."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ADVISORS = {
    "film_director",
    "short_drama_director",
    "original_author",
    "ordinary_audience",
    "executive_producer",
    "american_tv_pacing",
}
TECHNIQUES = {
    "cold_open",
    "late_in_early_out",
    "every_scene_turns",
    "cross_cutting",
    "button",
    "dangle_setup_payoff",
    "act_out",
    "overlap_interrupt",
}
APPROVAL_REF = re.compile(r"^ROGER-[A-Za-z0-9_-]+$")


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    script_sha = str(payload.get("script_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", script_sha):
        failures.append("script_sha256_missing_or_invalid")

    council = payload.get("council") or {}
    rows = council.get("advisors") or []
    by_role = {str(row.get("role") or ""): row for row in rows if isinstance(row, dict)}
    for role in sorted(ADVISORS):
        row = by_role.get(role)
        if not row:
            failures.append(f"council_advisor_missing:{role}")
        elif row.get("independent") is not True or len(str(row.get("analysis") or "").strip()) < 20:
            failures.append(f"council_advisor_not_independent_or_empty:{role}")
    chair_verdict = str(council.get("chair_verdict") or "").upper()
    revision_cascade = council.get("revision_cascade") or {}
    cascade_targets = revision_cascade.get("affected_unproduced_episodes") or []
    published_impacts = revision_cascade.get("affected_published_episodes") or []
    if chair_verdict != "PASS":
        failures.append("council_chair_verdict_not_pass")
    if chair_verdict == "REVISE":
        if not cascade_targets:
            failures.append("revision_cascade_targets_missing")
        if revision_cascade.get("status") not in {"TASKS_CREATED", "IN_PROGRESS", "COMPLETE"}:
            failures.append("revision_cascade_not_started")
        if published_impacts and not APPROVAL_REF.fullmatch(
            str(revision_cascade.get("roger_published_impact_approval_ref") or "")
        ):
            failures.append("published_episode_revision_missing_roger_approval")
    if not str(council.get("experience_memory_ref") or "").strip():
        failures.append("council_experience_memory_ref_missing")

    beats = payload.get("beats") or []
    if not beats:
        failures.append("narrative_beats_missing")
    contract = payload.get("narrative_technique_contract") or {}
    cold_open = contract.get("cold_open") or {}
    cold_open_pass = (
        cold_open.get("enabled") is True
        and float(cold_open.get("within_seconds", 999) or 999) <= 3.0
        and cold_open.get("event_in_progress") is True
    )
    if not cold_open_pass:
        failures.append("cold_open_not_event_in_progress_within_3s")

    dual_line_episode = contract.get("dual_line_episode") is True
    unresolved_ids: set[str] = set()
    intercut_count = 0
    interruption_count = 0
    act_out_count = 0
    late_in_early_out_pass = bool(beats)
    every_scene_turns_pass = bool(beats)
    button_pass = bool(beats)
    for index, beat in enumerate(beats, 1):
        if not isinstance(beat, dict):
            failures.append(f"beat_technique_fields_missing:{index}")
            continue
        required_fields = (
            "scene_entry",
            "scene_exit",
            "power_shift",
            "intercut_with",
            "end_button",
            "unresolved_question_id",
            "act_out",
            "dialogue_interruption_refs",
        )
        missing = [key for key in required_fields if key not in beat]
        if missing:
            failures.append(f"beat_technique_fields_missing:{index}:" + ",".join(missing))
        if beat.get("scene_entry") != "late" or beat.get("scene_exit") != "early":
            late_in_early_out_pass = False
            failures.append(f"beat_not_late_in_early_out:{index}")
        if not str(beat.get("power_shift") or "").strip():
            every_scene_turns_pass = False
            failures.append(f"beat_scene_turn_missing:{index}")
        intercut = str(beat.get("intercut_with") or "").strip()
        if intercut:
            intercut_count += 1
        button = beat.get("end_button")
        if isinstance(button, dict):
            button = button.get("line") or button.get("action") or button.get("reveal")
        if not str(button or "").strip():
            button_pass = False
            failures.append(f"beat_end_button_missing:{index}")
        unresolved = str(beat.get("unresolved_question_id") or "").strip()
        if unresolved:
            unresolved_ids.add(unresolved)
        if beat.get("act_out") is True:
            act_out_count += 1
        interruptions = beat.get("dialogue_interruption_refs") or []
        if not isinstance(interruptions, list):
            failures.append(f"beat_dialogue_interruption_refs_not_list:{index}")
        else:
            interruption_count += len([row for row in interruptions if str(row).strip()])

    if dual_line_episode and intercut_count < 1:
        failures.append("dual_line_episode_missing_cross_cut")
    if len(unresolved_ids) < 2:
        failures.append(f"unresolved_dangle_count_below_2:{len(unresolved_ids)}")
    runtime_seconds = float(payload.get("runtime_seconds") or 0)
    required_act_outs = max(1, int(runtime_seconds // 50)) if beats else 0
    if act_out_count < required_act_outs:
        failures.append(f"act_out_count_below_required:{act_out_count}:{required_act_outs}")
    if interruption_count < 1:
        failures.append("overlap_interrupt_evidence_missing")

    coverage = {
        "cold_open": cold_open_pass,
        "late_in_early_out": late_in_early_out_pass,
        "every_scene_turns": every_scene_turns_pass,
        "cross_cutting": (not dual_line_episode) or intercut_count > 0,
        "button": button_pass,
        "dangle_setup_payoff": len(unresolved_ids) >= 2,
        "act_out": act_out_count >= required_act_outs,
        "overlap_interrupt": interruption_count >= 1,
    }

    fight = payload.get("two_episode_fight_floor") or {}
    qualifying = int(fight.get("qualifying_true_fight_scene_count") or 0)
    minimum_duration = float(fight.get("minimum_qualifying_duration_seconds") or 0)
    approval = str(fight.get("roger_skip_approval_ref") or "")
    if qualifying < 1 or minimum_duration < 15.0:
        if not APPROVAL_REF.fullmatch(approval):
            failures.append("fs1_true_fight_floor_not_met_and_no_roger_approval")

    return {
        "schema": "qingshan.dramatic_quality_gate.v1",
        "episode": payload.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "generation_allowed": not failures,
        "advisor_roles": sorted(ADVISORS),
        "chair_verdict": chair_verdict or "MISSING",
        "revision_cascade_required": chair_verdict == "REVISE",
        "revision_cascade_targets": cascade_targets,
        "published_episode_impacts": published_impacts,
        "next_action": (
            "BLOCK_GENERATION_AND_EXECUTE_REVISION_CASCADE"
            if chair_verdict == "REVISE"
            else "PROCEED" if chair_verdict == "PASS" and not failures else "BLOCK_GENERATION"
        ),
        "narrative_technique_coverage": coverage,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.report.read_text(encoding="utf-8")))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
