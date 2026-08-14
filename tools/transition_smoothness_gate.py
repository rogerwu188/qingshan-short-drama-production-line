#!/usr/bin/env python3
"""Validate edit-timeline transition metadata against the smoothness contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _in_range(value: float, limits: dict) -> bool:
    return float(limits["min"]) <= float(value) <= float(limits["max"])


def evaluate(plan: dict, contract: dict) -> dict:
    failures: list[str] = []
    dialogue = plan.get("dialogue_transitions", [])
    if not dialogue:
        failures.append("missing_dialogue_transitions")

    jl_count = 0
    same_frame_count = 0
    for row in dialogue:
        transition_id = row.get("transition_id", "UNKNOWN")
        kind = row.get("cut_type")
        if kind in {"J", "L"}:
            jl_count += 1
        if row.get("same_frame_audio_visual_cut", False):
            same_frame_count += 1
        if kind == "J" and not _in_range(
            row.get("audio_lead_ms", -1),
            contract["dialogue"]["j_cut_audio_lead_ms"],
        ):
            failures.append(f"j_cut_lead_out_of_range:{transition_id}")
        if kind == "L" and not _in_range(
            row.get("audio_tail_ms", -1),
            contract["dialogue"]["l_cut_audio_tail_ms"],
        ):
            failures.append(f"l_cut_tail_out_of_range:{transition_id}")
        if not _in_range(
            row.get("speech_crossfade_ms", -1),
            contract["dialogue"]["speech_equal_power_crossfade_ms"],
        ):
            failures.append(f"speech_crossfade_out_of_range:{transition_id}")
        if not _in_range(
            row.get("action_cut_offset_frames", -1),
            contract["picture"]["action_cut_offset_frames"],
        ):
            failures.append(f"action_cut_offset_out_of_range:{transition_id}")
        if not _in_range(
            row.get("reaction_hold_ms", -1),
            contract["picture"]["reaction_hold_after_sentence_ms"],
        ):
            failures.append(f"reaction_hold_out_of_range:{transition_id}")

    count = len(dialogue)
    jl_ratio = jl_count / count if count else 0.0
    same_frame_ratio = same_frame_count / count if count else 1.0
    if jl_ratio < contract["dialogue"]["jl_cut_ratio_min"]:
        failures.append("jl_cut_ratio_below_min")
    if same_frame_ratio > contract["dialogue"]["same_frame_audio_visual_cut_ratio_max"]:
        failures.append("same_frame_audio_visual_cut_ratio_above_max")

    scene_transitions = plan.get("scene_transitions", [])
    if not scene_transitions:
        failures.append("missing_scene_transitions")
    for row in scene_transitions:
        transition_id = row.get("transition_id", "UNKNOWN")
        if not _in_range(
            row.get("ambience_prelap_ms", -1),
            contract["ambience_and_bgm"]["scene_prelap_ms"],
        ):
            failures.append(f"scene_prelap_out_of_range:{transition_id}")
        if not _in_range(
            row.get("ambience_crossfade_ms", -1),
            contract["ambience_and_bgm"]["equal_power_crossfade_ms"],
        ):
            failures.append(f"ambience_crossfade_out_of_range:{transition_id}")

    picture_segments = plan.get("picture_segments", [])
    back_to_back_allowed = plan.get("same_insert_source_back_to_back_allowed", False)
    if picture_segments and not back_to_back_allowed:
        for left, right in zip(picture_segments, picture_segments[1:]):
            if left.get("source_id") != right.get("source_id"):
                continue
            if left.get("diagnostic_only") or right.get("diagnostic_only"):
                continue
            failures.append(
                f"same_source_back_to_back:{left.get('segment_id', 'UNKNOWN')}->{right.get('segment_id', 'UNKNOWN')}"
            )
    for row in picture_segments:
        if row.get("requires_narrative_increment") and not row.get("narrative_increment"):
            failures.append(
                f"required_narrative_increment_missing:{row.get('segment_id', 'UNKNOWN')}"
            )

    return {
        "schema": "qingshan.transition_smoothness_gate_report.v1",
        "status": "PASS" if not failures else "FAIL",
        "dialogue_transition_count": count,
        "jl_cut_ratio": jl_ratio,
        "same_frame_audio_visual_cut_ratio": same_frame_ratio,
        "scene_transition_count": len(scene_transitions),
        "picture_segment_count": len(picture_segments),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    report = evaluate(plan, contract)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
