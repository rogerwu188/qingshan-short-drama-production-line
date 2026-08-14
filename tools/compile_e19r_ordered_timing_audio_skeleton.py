#!/usr/bin/env python3
"""Compile a frame-exact, non-final E19R timing and audio-binding skeleton."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
FPS = 24
MAX_SOURCE_FRAMES = 4 * FPS
MIN_DIALOGUE_FRAMES = 2 * FPS

NATIVE_AUDIO_CANDIDATES = {
    "DIA-006": {
        "state": "NATIVE_CANDIDATE_NOT_FINAL",
        "path": "assets/e19r_shizi_voice_pilot_r1_20260717/E19R-SHIZI-DIA-006-NATIVE-VOICE.wav",
    },
    "DIA-011": {
        "state": "NATIVE_VIDEO_AUDIO_CANDIDATE_NOT_FINAL",
        "path": "assets/e19r_shizi_role_gated_r1_20260717/DIA-011.mp4",
    },
    "DIA-037": {
        "state": "NATIVE_VIDEO_AUDIO_CANDIDATE_NOT_FINAL_TIMBRE_SPOT_CHECK_REQUIRED",
        "path": "assets/e19r_shizi_role_gated_r1_20260717/DIA-037.mp4",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def visible_char_count(text: str) -> int:
    return sum(1 for char in text if not char.isspace() and char not in "，。！？、；：,.!?;:")


def planned_dialogue_frames(text: str) -> int:
    seconds = 1.25 + 0.16 * visible_char_count(text)
    return max(MIN_DIALOGUE_FRAMES, min(MAX_SOURCE_FRAMES, round(seconds * FPS)))


def split_bridge_frames(total: int) -> list[int]:
    if total <= 0:
        return []
    count = math.ceil(total / MAX_SOURCE_FRAMES)
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def source_map(candidate: dict[str, Any]) -> tuple[dict[str, dict[str, str]], dict[str, list[dict[str, str]]]]:
    by_dialogue: dict[str, dict[str, str]] = {}
    by_beat: dict[str, list[dict[str, str]]] = {}
    for beat in candidate["ordered_beats"]:
        sources = []
        for coverage in beat["coverage"]:
            item = {"source_id": coverage["source_id"], "path": coverage["path"]}
            sources.append(item)
            for dialogue_id in coverage["dialogue_ids"]:
                if dialogue_id in by_dialogue:
                    raise ValueError(f"duplicate coverage binding: {dialogue_id}")
                by_dialogue[dialogue_id] = item
        by_beat[beat["beat_id"]] = sources
    return by_dialogue, by_beat


def choose_bridge_source(sources: list[dict[str, str]], previous_source_id: str | None, cursor: int) -> tuple[dict[str, str], int]:
    for offset in range(len(sources)):
        index = (cursor + offset) % len(sources)
        candidate = sources[index]
        if candidate["source_id"] != previous_source_id or len(sources) == 1:
            return candidate, index + 1
    return sources[cursor % len(sources)], cursor + 1


def seconds(frames: int) -> float:
    return round(frames / FPS, 6)


def compile_skeleton(beat_sheet: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    dialogue_rows = beat_sheet["dialogue_draft"]
    dialogue_by_beat: dict[str, list[dict[str, Any]]] = {}
    for row in dialogue_rows:
        dialogue_by_beat.setdefault(row["beat_id"], []).append(row)

    by_dialogue, sources_by_beat = source_map(candidate)
    shots: list[dict[str, Any]] = []
    frame_cursor = 0
    shot_index = 1

    for beat in candidate["ordered_beats"]:
        beat_id = beat["beat_id"]
        beat_start = frame_cursor
        beat_target_frames = int(beat["target_seconds"] * FPS)
        dialogues = dialogue_by_beat[beat_id]
        dialogue_frames = [planned_dialogue_frames(row["text"]) for row in dialogues]
        bridge_frames = split_bridge_frames(beat_target_frames - sum(dialogue_frames))
        if sum(dialogue_frames) > beat_target_frames:
            raise ValueError(f"dialogue timing exceeds beat target: {beat_id}")

        bridge_slots: list[list[int]] = [[] for _ in range(len(dialogues) + 1)]
        for index, duration in enumerate(bridge_frames):
            slot = round(index * len(dialogues) / max(1, len(bridge_frames)))
            bridge_slots[min(slot, len(dialogues))].append(duration)

        bridge_source_cursor = 0
        previous_source_id: str | None = None
        for dialogue_index in range(len(dialogues) + 1):
            for bridge_duration in bridge_slots[dialogue_index]:
                source, bridge_source_cursor = choose_bridge_source(
                    sources_by_beat[beat_id], previous_source_id, bridge_source_cursor
                )
                shots.append({
                    "shot_index": shot_index,
                    "shot_type": "VISUAL_ONLY_BRIDGE_NOT_FINAL",
                    "beat_id": beat_id,
                    "dialogue_id": None,
                    "source_id": source["source_id"],
                    "source_path": source["path"],
                    "timeline_in_frame": frame_cursor,
                    "timeline_out_frame_exclusive": frame_cursor + bridge_duration,
                    "timeline_in_seconds": seconds(frame_cursor),
                    "timeline_out_seconds": seconds(frame_cursor + bridge_duration),
                    "duration_frames": bridge_duration,
                    "duration_seconds": seconds(bridge_duration),
                    "source_in_seconds": 0.0,
                    "source_out_seconds": seconds(bridge_duration),
                    "audio_binding": {"state": "VISUAL_ONLY_SILENCE_OR_AMBIENCE_PENDING", "path": None},
                    "final_lock_allowed": False,
                })
                frame_cursor += bridge_duration
                shot_index += 1
                previous_source_id = source["source_id"]

            if dialogue_index == len(dialogues):
                continue
            dialogue = dialogues[dialogue_index]
            duration = dialogue_frames[dialogue_index]
            source = by_dialogue[dialogue["dia_id"]]
            audio = NATIVE_AUDIO_CANDIDATES.get(dialogue["dia_id"], {
                "state": "PENDING_APPROVED_VOICE_BINDING_NOT_FINAL",
                "path": None,
            })
            shots.append({
                "shot_index": shot_index,
                "shot_type": "DIALOGUE_COVERAGE_NOT_FINAL",
                "beat_id": beat_id,
                "dialogue_id": dialogue["dia_id"],
                "speaker": dialogue["speaker"],
                "dialogue_text": dialogue["text"],
                "source_id": source["source_id"],
                "source_path": source["path"],
                "timeline_in_frame": frame_cursor,
                "timeline_out_frame_exclusive": frame_cursor + duration,
                "timeline_in_seconds": seconds(frame_cursor),
                "timeline_out_seconds": seconds(frame_cursor + duration),
                "duration_frames": duration,
                "duration_seconds": seconds(duration),
                "source_in_seconds": 0.0,
                "source_out_seconds": seconds(duration),
                "audio_binding": {
                    **audio,
                    "planned_j_cut_lead_frames": 4,
                    "planned_speech_crossfade_frames": 1,
                    "sentence_cut_forbidden": True,
                },
                "final_lock_allowed": False,
            })
            frame_cursor += duration
            shot_index += 1
            previous_source_id = source["source_id"]

        if frame_cursor - beat_start != beat_target_frames:
            raise ValueError(f"beat frame mismatch: {beat_id}")

    dialogue_ids = [shot["dialogue_id"] for shot in shots if shot["dialogue_id"]]
    expected_ids = [row["dia_id"] for row in dialogue_rows]
    missing = [item for item in expected_ids if item not in dialogue_ids]
    duplicates = sorted({item for item in dialogue_ids if dialogue_ids.count(item) > 1})
    runtime_frames = frame_cursor
    target_frames = int(candidate["runtime_target_seconds"] * FPS)
    if runtime_frames != target_frames or missing or duplicates:
        raise ValueError("compiled skeleton failed runtime or dialogue coverage checks")

    return {
        "schema": "qingshan.e19r.ordered_timing_audio_skeleton.v1",
        "episode": "E19R",
        "created_at": "2026-07-17T07:45:00-07:00",
        "status": "PASS_FRAME_EXACT_LOCAL_SKELETON_NOT_FINAL",
        "authorization_ref": candidate["authorization_ref"],
        "approved_script_sha256": candidate["approved_script_sha256"],
        "fps": FPS,
        "runtime_frames": runtime_frames,
        "runtime_seconds": seconds(runtime_frames),
        "dialogue_count": len(dialogue_ids),
        "visual_bridge_count": sum(1 for shot in shots if shot["shot_type"] == "VISUAL_ONLY_BRIDGE_NOT_FINAL"),
        "native_audio_candidate_count": sum(1 for shot in shots if str(shot["audio_binding"]["state"]).startswith("NATIVE")),
        "pending_audio_binding_count": sum(1 for shot in shots if shot["audio_binding"]["state"] == "PENDING_APPROVED_VOICE_BINDING_NOT_FINAL"),
        "shots": shots,
        "coverage_check": {
            "expected_dialogue_count": len(expected_ids),
            "compiled_dialogue_count": len(dialogue_ids),
            "missing_dialogue_ids": missing,
            "duplicate_dialogue_ids": duplicates,
            "timeline_contiguous": all(
                shots[index]["timeline_out_frame_exclusive"] == shots[index + 1]["timeline_in_frame"]
                for index in range(len(shots) - 1)
            ),
            "max_source_window_seconds": max(shot["source_out_seconds"] for shot in shots),
        },
        "ordering_guard": {
            "final_source_lock_allowed": False,
            "edit_admission_allowed": False,
            "package_allowed": False,
            "platform_action_allowed": False,
            "reason": "Local timing and audio preparation may proceed in parallel, but final admission remains ordered after E17 and E18R.",
        },
        "rollback": "Delete this derived skeleton without changing approved script, source candidates, audio candidates, final locks, package state, or platforms.",
    }


def build_qa(payload: dict[str, Any], output_ref: str) -> dict[str, Any]:
    checks = {
        "runtime_exact_178_seconds": payload["runtime_frames"] == 178 * FPS,
        "dialogues_40_of_40_once": payload["dialogue_count"] == 40
        and not payload["coverage_check"]["missing_dialogue_ids"]
        and not payload["coverage_check"]["duplicate_dialogue_ids"],
        "timeline_contiguous": payload["coverage_check"]["timeline_contiguous"],
        "source_windows_at_most_4_seconds": payload["coverage_check"]["max_source_window_seconds"] <= 4.0,
        "no_final_lock": all(not shot["final_lock_allowed"] for shot in payload["shots"]),
        "platform_actions_forbidden": not payload["ordering_guard"]["platform_action_allowed"],
    }
    return {
        "schema": "qingshan.e19r.ordered_timing_audio_skeleton_qa.v1",
        "episode": "E19R",
        "created_at": payload["created_at"],
        "status": "PASS" if all(checks.values()) else "FAIL",
        "machine_confidence": "HIGH",
        "skeleton_ref": output_ref,
        "checks": checks,
        "failures": [name for name, passed in checks.items() if not passed],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beat-sheet", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--qa-out", required=True, type=Path)
    args = parser.parse_args()

    beat_sheet = load_json(args.beat_sheet if args.beat_sheet.is_absolute() else ROOT / args.beat_sheet)
    candidate = load_json(args.candidate if args.candidate.is_absolute() else ROOT / args.candidate)
    payload = compile_skeleton(beat_sheet, candidate)
    out = args.out if args.out.is_absolute() else ROOT / args.out
    qa_out = args.qa_out if args.qa_out.is_absolute() else ROOT / args.qa_out
    out.parent.mkdir(parents=True, exist_ok=True)
    qa_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    qa = build_qa(payload, str(args.out))
    qa_out.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": qa["status"],
        "runtime_seconds": payload["runtime_seconds"],
        "dialogues": payload["dialogue_count"],
        "bridges": payload["visual_bridge_count"],
        "out": str(out),
        "qa_out": str(qa_out),
    }, ensure_ascii=False))
    return 0 if qa["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
