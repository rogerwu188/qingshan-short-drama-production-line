#!/usr/bin/env python3
"""Build E22 V15 by reverting only DIA-018 to its V13 dialogue-correct source."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e22_agentcut_project_v14_existing_motion_sources_20260719.json"
V13 = ROOT / "configs/e22_agentcut_project_v13_sentence_tail_repair_20260719.json"
OUT_PROJECT = ROOT / "configs/e22_agentcut_project_v15_dia018_semantic_rollback_20260719.json"
OUT_TIMELINE = ROOT / "qa/e22_agentcut_v15_dia018_semantic_rollback_20260719/E22_FINAL_TIMELINE_SHOTS_V15.json"
OUT_RECEIPT = ROOT / "workflow/tasks/E22_AGENTCUT_V15_DIA018_SEMANTIC_ROLLBACK_20260719.json"
OUT_VIDEO = ROOT / "exports/e22/agentcut_v15_dia018_semantic_rollback_20260719/E22_AGENTCUT_V15_DIA018_SEMANTIC_ROLLBACK_NOT_FINAL.mp4"
TARGET = "DIA-018"


def dialogue_id(clip: dict) -> str | None:
    explicit = clip.get("metadata", {}).get("dialogue_id") or clip.get("dialogue_id")
    if explicit:
        return explicit
    return TARGET if TARGET in clip.get("id", "") else None


def source_for(project: dict, track_group: str) -> str:
    matches = [
        clip["source"]
        for track in project["timeline"][track_group]
        for clip in track.get("clips", [])
        if dialogue_id(clip) == TARGET
    ]
    if len(matches) != 1:
        raise SystemExit(f"Expected one {TARGET} source in {track_group}, found {len(matches)}")
    return matches[0]


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    v13 = json.loads(V13.read_text(encoding="utf-8"))
    replacements: dict[str, str] = {}

    for track_group in ("videoTracks", "audioTracks"):
        approved_source = source_for(v13, track_group)
        replaced = 0
        for track in project["timeline"][track_group]:
            for clip in track.get("clips", []):
                if dialogue_id(clip) != TARGET:
                    continue
                clip["source"] = approved_source
                metadata = clip.setdefault("metadata", {})
                metadata.pop("v14_existing_motion_source", None)
                metadata.pop("v14_replacement_source", None)
                metadata.pop("v14_repair_reason", None)
                metadata["v15_semantic_rollback"] = True
                metadata["v15_repair_reason"] = "V14 source ASR contained dialogue from a different narrative beat"
                metadata["source_qa"] = "PASS_EDIT_ADMISSION_V10_REPEAT_REPAIR_RESTORED_FROM_V13"
                replaced += 1
        if replaced != 1:
            raise SystemExit(f"Expected one {TARGET} clip in {track_group}, replaced {replaced}")
        replacements[track_group] = approved_source

    project["metadata"].update(
        {
            "status": "V15_DIA018_SEMANTIC_ROLLBACK_NOT_FINAL",
            "version": "E22_AGENTCUT_V15_DIA018_SEMANTIC_ROLLBACK",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Revert only DIA-018 video and native audio to the dialogue-correct V13 source; preserve the other 12 V14 motion replacements and the full timeline",
            "failed_dialogue_ids": [TARGET],
            "source_failure_evidence": "qa/e22_agentcut_v14_existing_motion_sources_20260719/E22_FINAL_SENTENCE_COMPLETENESS_V14.json",
            "rollback": str(BASE.relative_to(ROOT)),
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
                "episode": "E22",
                "version": "V15",
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
                "task_id": "E22_AGENTCUT_V15_DIA018_SEMANTIC_ROLLBACK_20260719",
                "episode": "E22",
                "status": "PROJECT_BUILT_PENDING_RENDER",
                "project": str(OUT_PROJECT),
                "output": str(OUT_VIDEO),
                "failed_only_repair": [TARGET],
                "replacements": replacements,
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
