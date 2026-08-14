#!/usr/bin/env python3
"""Build E21 V17 by replacing only DIA-021 with its verified speech source."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v16_audio_source_and_visual_gate_repair_20260719.json"
SOURCE = ROOT / "working_assets/e21_failed_only_dia021_speech_repair_20260719/candidates/E21_E21-DIA-021-R2-SPEECH-VIDEO_8020933f-418c-496d-a8cb-00ecac143545.mp4"
SOURCE_QA = ROOT / "qa/e21_failed_only_dia021_speech_repair_20260719/E21_DIA021_R2_FOCUSED_ASR_ACCEPTANCE.json"
V16_SENTENCE = ROOT / "qa/e21_agentcut_v16_audio_source_and_visual_gate_repair_20260719/E21_FINAL_SENTENCE_COMPLETENESS_V16.json"
OUT_PROJECT = ROOT / "configs/e21_agentcut_project_v17_dia021_verified_source_repair_20260719.json"
OUT_QA = ROOT / "qa/e21_agentcut_v17_dia021_verified_source_repair_20260719"
OUT_TIMELINE = OUT_QA / "E21_FINAL_TIMELINE_SHOTS_V17.json"
OUT_AUDIO_BOUNDARIES = OUT_QA / "E21_AUDIO_EDIT_BOUNDARIES_V17.json"
OUT_RECEIPT = ROOT / "workflow/tasks/E21_AGENTCUT_V17_DIA021_VERIFIED_SOURCE_REPAIR_20260719.json"
OUT_VIDEO = ROOT / "exports/e21/agentcut_v17_dia021_verified_source_repair_20260719/E21_AGENTCUT_V17_DIA021_VERIFIED_SOURCE_REPAIR_NOT_FINAL.mp4"
TARGET = "DIA-021"
OLD_END = 135.582008
NEW_DURATION = 2.5
SHIFT = 1.0


def dialogue_id(clip: dict) -> str | None:
    explicit = clip.get("metadata", {}).get("dialogue_id") or clip.get("dialogue_id")
    if explicit:
        return explicit
    return TARGET if TARGET in clip.get("id", "") else None


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    source_qa = json.loads(SOURCE_QA.read_text(encoding="utf-8"))
    sentence = json.loads(V16_SENTENCE.read_text(encoding="utf-8"))
    if source_qa.get("status") != "PASS" or source_qa.get("recognized_text") != "灯！":
        raise SystemExit("DIA-021 verified source QA is not a clean exact-dialogue PASS")
    if sentence.get("failures") != [TARGET]:
        raise SystemExit(f"Unexpected V16 sentence failure set: {sentence.get('failures')}")

    replacements: dict[str, int] = {}
    for track_group in ("videoTracks", "audioTracks", "subtitleTracks"):
        count = 0
        for track in project["timeline"].get(track_group, []):
            for clip in track.get("clips", []):
                old_start = float(clip["start"])
                if old_start >= OLD_END - 0.001:
                    clip["start"] = round(old_start + SHIFT, 6)
                if dialogue_id(clip) != TARGET:
                    continue
                clip["duration"] = NEW_DURATION
                if track_group in ("videoTracks", "audioTracks"):
                    clip["source"] = str(SOURCE)
                if track_group == "audioTracks":
                    clip["volume"] = 0.72
                clip.setdefault("metadata", {})["v17_verified_dialogue_source"] = {
                    "expected": "灯！",
                    "recognized": "灯！",
                    "source_qa": str(SOURCE_QA.relative_to(ROOT)),
                    "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                }
                count += 1
        replacements[track_group] = count
    if replacements != {"videoTracks": 1, "audioTracks": 1, "subtitleTracks": 1}:
        raise SystemExit(f"Unexpected replacement counts: {replacements}")

    project["metadata"].update({
        "status": "V17_DIA021_VERIFIED_SOURCE_REPAIR_NOT_FINAL",
        "version": "E21_AGENTCUT_V17_DIA021_VERIFIED_SOURCE_REPAIR",
        "source_project": str(BASE.relative_to(ROOT)),
        "change_scope": "Replace only DIA-021 picture/native audio with exact-dialogue focused-ASR PASS source and extend its admitted window to 2.5 seconds",
        "runtime_delta_seconds": SHIFT,
        "rollback": str(BASE.relative_to(ROOT)),
    })
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    OUT_QA.mkdir(parents=True, exist_ok=True)
    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    OUT_TIMELINE.write_text(json.dumps({
        "schema": "qingshan.final_timeline_shots.v1", "episode": "E21", "version": "V17",
        "shots": [{
            "shot_id": clip["id"], "scene_id": clip.get("metadata", {}).get("scene_id"),
            "start": clip["start"], "end": round(float(clip["start"]) + float(clip["duration"]), 6),
        } for clip in video_clips],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    boundaries = sorted({
        round(float(clip["start"]), 6)
        for track in project["timeline"].get("audioTracks", [])
        for clip in track.get("clips", [])
        if float(clip["start"]) > 0.0
    })
    OUT_AUDIO_BOUNDARIES.write_text(json.dumps({
        "schema": "qingshan.audio_edit_boundaries.v1", "episode": "E21", "version": "V17",
        "boundaries": boundaries, "source": str(OUT_PROJECT.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    OUT_RECEIPT.write_text(json.dumps({
        "schema": "qingshan.production.task.v1",
        "task_id": "E21_AGENTCUT_V17_DIA021_VERIFIED_SOURCE_REPAIR_20260719",
        "episode": "E21", "status": "PROJECT_BUILT_PENDING_RENDER",
        "project": str(OUT_PROJECT), "output": str(OUT_VIDEO),
        "failed_only_repair": [TARGET], "replacement_counts": replacements,
        "replacement_source": str(SOURCE),
        "replacement_source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "source_qa": str(SOURCE_QA), "audio_boundaries": str(OUT_AUDIO_BOUNDARIES),
        "rollback": str(BASE),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(OUT_PROJECT), "output": str(OUT_VIDEO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
