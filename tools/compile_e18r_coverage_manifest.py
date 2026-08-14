#!/usr/bin/env python3
"""Compile the approved E18R beat sheet into a complete coverage manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SHOT_PATTERN = {
    "dialogue": ["speaker_a", "speaker_b", "listener", "evidence_insert", "space_bridge"],
    "burst": ["wide_action", "moving_medium", "evidence_insert", "reaction", "space_bridge"],
    "dialogue_burst": ["speaker_a", "speaker_b", "listener", "evidence_insert", "moving_space_bridge"],
    "hook": ["speaker", "listener", "evidence_insert", "decision_action", "end_hook"],
}

STATIC_LOCKS = {
    "B01": ["E18R-VL-PASTRY-BOX"],
    "B02": ["E18R-VL-NIGHT-ROAD-STRETCHER", "E18R-VL-BRUISED-HAND-INSERT"],
    "B03": [],
    "B04": ["E18R-VL-CARRIAGE-TEST"],
    "B05": ["E18R-VL-RED-JADE-PENDANT"],
    "B06": [],
}


def compile_manifest(beat_sheet: dict, voice_manifest: dict, static_status: dict) -> dict:
    lines = beat_sheet["dialogue_draft"]
    voice_lines = voice_manifest["lines"]
    if [row["dia_id"] for row in lines] != [row["dia_id"] for row in voice_lines]:
        raise ValueError("Beat-sheet and voice-manifest dialogue order differ")

    submitted = {row["view_id"] for row in static_status["submitted"]}
    required_locks = {item for values in STATIC_LOCKS.values() for item in values}
    missing_locks = sorted(required_locks - submitted)
    if missing_locks:
        raise ValueError(f"Static locks were not submitted: {missing_locks}")

    beats = []
    covered = []
    for beat in beat_sheet["structure"]:
        beat_id = beat["beat_id"]
        beat_lines = [row["dia_id"] for row in lines if row["beat_id"] == beat_id]
        covered.extend(beat_lines)
        segment_type = beat["segment_type"]
        beats.append(
            {
                "beat_id": beat_id,
                "name": beat["name"],
                "target_seconds": beat["target_seconds"],
                "segment_type": segment_type,
                "dialogue_ids": beat_lines,
                "dialogue_count": len(beat_lines),
                "shot_pattern": SHOT_PATTERN[segment_type],
                "required_static_locks": STATIC_LOCKS[beat_id],
                "static_lock_state": "REMOTE_RUNNING" if STATIC_LOCKS[beat_id] else "NOT_REQUIRED_NEW_ASSET",
                "minimum_picture_delta_count": max(4, len(beat_lines) // 2),
                "maximum_average_shot_length_seconds": 2.0 if "burst" in segment_type else 3.5,
                "must_show": beat["must_show"],
            }
        )

    expected = [row["dia_id"] for row in lines]
    if covered != expected:
        raise ValueError("Coverage does not preserve all dialogue IDs in order")

    return {
        "schema": "qingshan.e18r_coverage_manifest.v1",
        "episode": "E18R",
        "status": "PASS_41_LINES_COVERED_STATIC_LOCKS_RUNNING",
        "final_admission": False,
        "beat_sheet": "configs/e18_remake_dialogue_beat_sheet_v1_20260716.json",
        "voice_binding_manifest": "configs/e18r_dialogue_voice_binding_manifest_v1_20260716.json",
        "static_batch_status": "workflow/tasks/e18r_visual_lock_static_batch_status_20260716.json",
        "dialogue_count": len(lines),
        "beat_count": len(beats),
        "runtime_target_seconds": beat_sheet["runtime_target_seconds"],
        "beats": beats,
        "coverage_checks": {
            "all_dialogue_ids_exactly_once_in_order": True,
            "all_six_beats_have_shot_patterns": True,
            "all_new_static_locks_submitted": True,
            "candidate_audio_allowed": False,
            "video_generation_allowed_before_static_qa": False,
        },
        "next_gate": "COLLECT_STATIC_LOCKS_AND_RUN_VISUAL_QA_BEFORE_VIDEO_PROMPT_COMPILATION",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beat-sheet", default=ROOT / "configs/e18_remake_dialogue_beat_sheet_v1_20260716.json", type=Path)
    parser.add_argument("--voice-manifest", default=ROOT / "configs/e18r_dialogue_voice_binding_manifest_v1_20260716.json", type=Path)
    parser.add_argument("--static-status", default=ROOT / "workflow/tasks/e18r_visual_lock_static_batch_status_20260716.json", type=Path)
    parser.add_argument("--out", default=ROOT / "configs/e18r_coverage_manifest_v1_20260716.json", type=Path)
    args = parser.parse_args()
    result = compile_manifest(
        json.loads(args.beat_sheet.read_text(encoding="utf-8")),
        json.loads(args.voice_manifest.read_text(encoding="utf-8")),
        json.loads(args.static_status.read_text(encoding="utf-8")),
    )
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "dialogue_count": result["dialogue_count"], "beat_count": result["beat_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
