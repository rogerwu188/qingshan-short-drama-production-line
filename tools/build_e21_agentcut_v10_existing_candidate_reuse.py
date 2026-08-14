#!/usr/bin/env python3
"""Build E21 V10 from ASR- and cadence-approved existing alternatives."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v9_sentence_tail_repair_20260719.json"
QA = ROOT / "qa/e21_agentcut_v9_sentence_tail_repair_20260719/E21_EXISTING_CANDIDATE_REUSE_QA_V10.json"
OUT_PROJECT = ROOT / "configs/e21_agentcut_project_v10_existing_candidate_reuse_20260719.json"
OUT_TIMELINE = ROOT / "qa/e21_agentcut_v10_existing_candidate_reuse_20260719/E21_FINAL_TIMELINE_SHOTS_V10.json"
OUT_RECEIPT = ROOT / "workflow/tasks/E21_AGENTCUT_V10_EXISTING_CANDIDATE_REUSE_20260719.json"
OUT_VIDEO = ROOT / "exports/e21/agentcut_v10_existing_candidate_reuse_20260719/E21_AGENTCUT_V10_EXISTING_CANDIDATE_REUSE_NOT_FINAL.mp4"
SOURCES = {
    "DIA-007": ROOT / "working_assets/e21_full_dialogue_parallel_20260719/candidates/E21_E21-DIA-007-VIDEO_cedd03fc-4049-40ca-a0ba-1a3294dbfa63.mp4",
    "DIA-024": ROOT / "working_assets/e21_full_dialogue_parallel_20260719/candidates/E21_E21-DIA-024-VIDEO_88f5b30a-2781-4592-af87-af20f08cfc99.mp4",
    "DIA-026": ROOT / "working_assets/e21_full_dialogue_parallel_20260719/candidates/E21_E21-DIA-026-VIDEO_9406127a-df54-4dd8-9ab1-438580fa6730.mp4",
    "DIA-031": ROOT / "working_assets/e21_v2_us_drama_new_dialogue_20260719/candidates/E21_E21-DIA-031-VIDEO-V2-NEW_4a2f0745-f411-4be0-887b-d7c9d0bf4694.mp4",
    "DIA-032": ROOT / "working_assets/e21_v2_us_drama_new_dialogue_20260719/candidates/E21_E21-DIA-032-VIDEO-V2-NEW_096b9d39-a5f3-4bdd-8fe1-8b4c3ba5e267.mp4",
}


def dialogue_id(clip: dict) -> str | None:
    explicit = clip.get("metadata", {}).get("dialogue_id") or clip.get("dialogue_id")
    if explicit:
        return explicit
    return next((dia_id for dia_id in SOURCES if dia_id in clip.get("id", "")), None)


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    qa = json.loads(QA.read_text(encoding="utf-8"))
    eligible = {row["candidate"] for row in qa["eligible_alternatives"]}
    for source in SOURCES.values():
        if not source.is_file() or str(source) not in eligible:
            raise SystemExit(f"Replacement lacks eligible QA evidence: {source}")

    replaced: dict[str, list[str]] = {"videoTracks": [], "audioTracks": []}
    for track_group in ("videoTracks", "audioTracks"):
        for track in project["timeline"][track_group]:
            for clip in track.get("clips", []):
                dia_id = dialogue_id(clip)
                if dia_id not in SOURCES:
                    continue
                source = SOURCES[dia_id]
                clip["source"] = str(source)
                metadata = clip.setdefault("metadata", {})
                evidence = next(row for row in qa["eligible_alternatives"] if row["candidate"] == str(source))
                metadata["v10_existing_candidate_reuse"] = True
                metadata["v10_source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
                metadata["v10_source_asr"] = evidence["transcript"]
                metadata["v10_semantic_recall"] = evidence["semantic_recall"]
                metadata["v10_source_motion_mean"] = evidence["motion_mean"]
                metadata["v10_source_near_duplicate_ratio"] = evidence["near_duplicate_ratio"]
                metadata["source_qa"] = "PASS_EXISTING_REUSE_ASR_AND_CADENCE_V10"
                replaced[track_group].append(dia_id)

    expected = sorted(SOURCES)
    for track_group, rows in replaced.items():
        if sorted(rows) != expected:
            raise SystemExit(f"Expected replacements {expected} in {track_group}, got {sorted(rows)}")

    # The V2 DIA-032 source completes the sentence in 4 seconds. Remove the
    # one-second V9 tail extension and ripple every later track in lockstep.
    target_video = next(
        clip
        for track in project["timeline"]["videoTracks"]
        for clip in track.get("clips", [])
        if dialogue_id(clip) == "DIA-032"
    )
    old_duration = float(target_video["duration"])
    new_duration = 4.041667
    ripple = round(old_duration - new_duration, 6)
    boundary = round(float(target_video["start"]) + old_duration, 6)
    if abs(ripple - 1.0) > 0.001:
        raise SystemExit(f"Unexpected DIA-032 ripple: {ripple}")

    for track_group in ("videoTracks", "audioTracks"):
        for track in project["timeline"][track_group]:
            for clip in track.get("clips", []):
                if dialogue_id(clip) == "DIA-032":
                    clip["duration"] = new_duration
                    clip.setdefault("metadata", {})["v10_removed_obsolete_tail_extension_seconds"] = ripple
                elif float(clip["start"]) >= boundary - 0.001:
                    clip["start"] = round(float(clip["start"]) - ripple, 6)

    for track in project["timeline"].get("subtitleTracks", []):
        for clip in track.get("clips", []):
            if clip.get("dialogue_id") == "DIA-032":
                clip["duration"] = round(float(clip["duration"]) - ripple, 6)
                clip.setdefault("metadata", {})["v10_removed_obsolete_tail_extension_seconds"] = ripple
            elif float(clip["start"]) >= boundary - 0.001:
                clip["start"] = round(float(clip["start"]) - ripple, 6)

    project["metadata"].update(
        {
            "status": "V10_EXISTING_CANDIDATE_REUSE_NOT_FINAL",
            "version": "E21_AGENTCUT_V10_EXISTING_CANDIDATE_REUSE",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Replace five near-duplicate contributors with existing alternatives that passed source ASR and cadence QA; remove DIA-032's obsolete one-second V9 tail extension and ripple all later tracks",
            "replacement_dialogue_ids": expected,
            "source_qa_evidence": str(QA.relative_to(ROOT)),
            "rollback": str(BASE.relative_to(ROOT)),
            "dia032_removed_tail_extension_seconds": ripple,
        }
    )
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    OUT_TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    OUT_TIMELINE.write_text(
        json.dumps(
            {
                "schema": "qingshan.final_timeline_shots.v1",
                "episode": "E21",
                "version": "V10",
                "shots": [
                    {
                        "shot_id": clip["id"],
                        "scene_id": clip.get("metadata", {}).get("scene_id"),
                        "start": clip["start"],
                        "end": round(float(clip["start"]) + float(clip["duration"]), 6),
                    }
                    for clip in video_clips
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
                "task_id": "E21_AGENTCUT_V10_EXISTING_CANDIDATE_REUSE_20260719",
                "episode": "E21",
                "status": "PROJECT_BUILT_PENDING_RENDER",
                "project": str(OUT_PROJECT),
                "output": str(OUT_VIDEO),
                "replacement_dialogue_ids": expected,
                "source_qa": str(QA),
                "rollback": str(BASE),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "project": str(OUT_PROJECT), "output": str(OUT_VIDEO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
