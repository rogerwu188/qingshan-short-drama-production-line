#!/usr/bin/env python3
"""Build E21 V14 with speech-safe tail trims and motivated jump-cut separation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v13_dia001_repeat_repair_20260719.json"
QA = ROOT / "qa/e21_agentcut_v13_dia001_repeat_repair_20260719/E21_FINAL_SENTENCE_COMPLETENESS_V13.json"
CI = ROOT / "qa/e21_agentcut_v13_dia001_repeat_repair_20260719/E21_REGRESSION_CI_V13_FROZEN_THRESHOLDS.json"
OUT_PROJECT = ROOT / "configs/e21_agentcut_project_v14_runtime_and_cut_separation_repair_20260719.json"
OUT_TIMELINE = ROOT / "qa/e21_agentcut_v14_runtime_and_cut_separation_repair_20260719/E21_FINAL_TIMELINE_SHOTS_V14.json"
OUT_RECEIPT = ROOT / "workflow/tasks/E21_AGENTCUT_V14_RUNTIME_AND_CUT_SEPARATION_REPAIR_20260719.json"
OUT_VIDEO = ROOT / "exports/e21/agentcut_v14_runtime_and_cut_separation_repair_20260719/E21_AGENTCUT_V14_RUNTIME_AND_CUT_SEPARATION_REPAIR_NOT_FINAL.mp4"

# Absolute admitted durations. Every aggressive trim retains 0.5 seconds after
# the final source-ASR speech segment; 6.042-second clips lose only two frames.
TARGET_DURATIONS = {
    "DIA-006": 2.94,
    "DIA-014": 5.942,
    "DIA-019": 1.7,
    "DIA-020": 2.5,
    "DIA-021": 1.5,
    "DIA-036": 2.03,
}

# Alternate wider and tighter punch-ins at CI-merged boundaries. These are
# ordinary short-drama jump cuts, not retiming, filler, or synthetic flashes.
PUNCH_INS = {
    "DIA-004": {"size": {"width": 864, "height": 1536}, "position": {"x": -72, "y": -128}},
    "DIA-007": {"size": {"width": 900, "height": 1600}, "position": {"x": -90, "y": -160}},
    "DIA-013": {"size": {"width": 864, "height": 1536}, "position": {"x": -72, "y": -128}},
    "DIA-031": {"size": {"width": 900, "height": 1600}, "position": {"x": -90, "y": -160}},
    "DIA-016": {"size": {"width": 900, "height": 1600}, "position": {"x": -120, "y": -160}},
    "DIA-017": {"size": {"width": 828, "height": 1472}, "position": {"x": -20, "y": -96}},
    "DIA-020": {"size": {"width": 864, "height": 1536}, "position": {"x": -72, "y": -128}},
    "DIA-024": {"size": {"width": 900, "height": 1600}, "position": {"x": -90, "y": -160}},
    "DIA-026": {"size": {"width": 900, "height": 1600}, "position": {"x": -120, "y": -160}},
    "DIA-037": {"size": {"width": 828, "height": 1472}, "position": {"x": -20, "y": -96}}
}


def dialogue_id(clip: dict) -> str | None:
    explicit = clip.get("metadata", {}).get("dialogue_id") or clip.get("dialogue_id")
    if explicit:
        return explicit
    return next((dia_id for dia_id in set(TARGET_DURATIONS) | set(PUNCH_INS) if dia_id in clip.get("id", "")), None)


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    qa = json.loads(QA.read_text(encoding="utf-8"))
    ci = json.loads(CI.read_text(encoding="utf-8"))
    if qa.get("status") != "PASS" or qa.get("failures"):
        raise SystemExit("V13 sentence audit is not a clean PASS")
    expected_ci_failures = {"too_many_long_shots:12", "speech_density_below_threshold:14.01"}
    if set(ci.get("failures", [])) != expected_ci_failures:
        raise SystemExit(f"Unexpected V13 CI failure set: {ci.get('failures')}")

    rows = {row["id"]: row for row in qa["sentences"]}
    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    original = {dialogue_id(clip): (float(clip["start"]), float(clip["duration"])) for clip in video_clips}
    missing = sorted(set(TARGET_DURATIONS) - set(original))
    if missing:
        raise SystemExit(f"Missing timeline clips: {missing}")

    for dia_id, target in TARGET_DURATIONS.items():
        last_speech_end = max(float(segment["end"]) for segment in rows[dia_id]["segments"])
        if target - last_speech_end < 0.45:
            raise SystemExit(f"Unsafe trim for {dia_id}: {target=} {last_speech_end=}")
        if target > original[dia_id][1] + 0.001:
            raise SystemExit(f"Trim target extends {dia_id}: {target} > {original[dia_id][1]}")

    deltas = {dia_id: round(target - original[dia_id][1], 6) for dia_id, target in TARGET_DURATIONS.items()}
    boundaries = sorted((original[dia_id][0] + original[dia_id][1], dia_id, delta) for dia_id, delta in deltas.items())

    for track_group in ("videoTracks", "audioTracks", "subtitleTracks"):
        for track in project["timeline"].get(track_group, []):
            for clip in track.get("clips", []):
                dia_id = dialogue_id(clip)
                old_start = float(clip["start"])
                prior_shift = sum(delta for boundary, _, delta in boundaries if boundary <= old_start + 0.001)
                clip["start"] = round(old_start + prior_shift, 6)
                if dia_id in TARGET_DURATIONS:
                    clip["duration"] = TARGET_DURATIONS[dia_id]
                    clip.setdefault("metadata", {})["v14_speech_safe_tail_trim_seconds"] = round(-deltas[dia_id], 6)
                if track_group == "videoTracks" and dia_id in PUNCH_INS:
                    clip.update(PUNCH_INS[dia_id])
                    clip.setdefault("metadata", {})["v14_motivated_jump_cut_punch_in"] = True

    net_delta = round(sum(deltas.values()), 6)
    project["metadata"].update(
        {
            "status": "V14_RUNTIME_AND_CUT_SEPARATION_REPAIR_NOT_FINAL",
            "version": "E21_AGENTCUT_V14_RUNTIME_AND_CUT_SEPARATION_REPAIR",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Remove only ASR-proven post-speech tails and add motivated punch-ins at CI-merged dialogue boundaries",
            "target_durations_seconds": TARGET_DURATIONS,
            "punch_in_dialogue_ids": list(PUNCH_INS),
            "net_runtime_delta_seconds": net_delta,
            "source_sentence_qa": str(QA.relative_to(ROOT)),
            "source_ci": str(CI.relative_to(ROOT)),
            "rollback": str(BASE.relative_to(ROOT)),
        }
    )
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    final_clips = project["timeline"]["videoTracks"][0]["clips"]
    OUT_TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    OUT_TIMELINE.write_text(
        json.dumps(
            {
                "schema": "qingshan.final_timeline_shots.v1",
                "episode": "E21",
                "version": "V14",
                "shots": [
                    {
                        "shot_id": clip["id"],
                        "scene_id": clip.get("metadata", {}).get("scene_id"),
                        "start": clip["start"],
                        "end": round(float(clip["start"]) + float(clip["duration"]), 6),
                    }
                    for clip in final_clips
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    OUT_RECEIPT.write_text(
        json.dumps(
            {
                "schema": "qingshan.production.task.v1",
                "task_id": "E21_AGENTCUT_V14_RUNTIME_AND_CUT_SEPARATION_REPAIR_20260719",
                "episode": "E21",
                "status": "PROJECT_BUILT_PENDING_RENDER",
                "project": str(OUT_PROJECT),
                "output": str(OUT_VIDEO),
                "target_durations_seconds": TARGET_DURATIONS,
                "punch_in_dialogue_ids": list(PUNCH_INS),
                "net_runtime_delta_seconds": net_delta,
                "source_sentence_qa": str(QA),
                "source_ci": str(CI),
                "source_project_sha256": hashlib.sha256(BASE.read_bytes()).hexdigest(),
                "rollback": str(BASE),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "project": str(OUT_PROJECT), "output": str(OUT_VIDEO), "net_delta": net_delta}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
