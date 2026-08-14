#!/usr/bin/env python3
"""Build E22 V16 by replacing only DIA-016 with a dialogue-correct lower-luma source."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e22_agentcut_project_v15_dia018_semantic_rollback_20260719.json"
OUT_PROJECT = ROOT / "configs/e22_agentcut_project_v16_dia016_luma_repair_20260719.json"
OUT_TIMELINE = ROOT / "qa/e22_agentcut_v16_dia016_luma_repair_20260719/E22_FINAL_TIMELINE_SHOTS_V16.json"
OUT_RECEIPT = ROOT / "workflow/tasks/E22_AGENTCUT_V16_DIA016_LUMA_REPAIR_20260719.json"
OUT_VIDEO = ROOT / "exports/e22/agentcut_v16_dia016_luma_repair_20260719/E22_AGENTCUT_V16_DIA016_LUMA_REPAIR_NOT_FINAL.mp4"
SOURCE = ROOT / "working_assets/e22_v4_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-016-VIDEO_e2375cd2-8d53-4088-8fc4-6a0c8a79bb6f.mp4"
TARGET = "DIA-016"


def dialogue_id(clip: dict) -> str | None:
    explicit = clip.get("metadata", {}).get("dialogue_id") or clip.get("dialogue_id")
    if explicit:
        return explicit
    return TARGET if TARGET in clip.get("id", "") else None


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    if not SOURCE.is_file():
        raise SystemExit(f"Missing replacement source: {SOURCE}")

    replacements: dict[str, str] = {}
    for track_group in ("videoTracks", "audioTracks"):
        replaced = 0
        for track in project["timeline"][track_group]:
            for clip in track.get("clips", []):
                if dialogue_id(clip) != TARGET:
                    continue
                clip["source"] = str(SOURCE)
                metadata = clip.setdefault("metadata", {})
                metadata["v16_luma_repair"] = True
                metadata["v16_repair_reason"] = "DIA-015 to DIA-016 measured luma jump 30.07 exceeded the frozen 25.0 gate"
                metadata["source_asr"] = "陈公子果然认得"
                metadata["source_cadence_qa"] = "PASS"
                metadata["source_mean_luma"] = 85.38
                replaced += 1
        if replaced != 1:
            raise SystemExit(f"Expected one {TARGET} clip in {track_group}, replaced {replaced}")
        replacements[track_group] = str(SOURCE)

    project["metadata"].update(
        {
            "status": "V16_DIA016_LUMA_REPAIR_NOT_FINAL",
            "version": "E22_AGENTCUT_V16_DIA016_LUMA_REPAIR",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Replace only DIA-016 video and native audio with the dialogue-correct cadence-PASS lower-luma source",
            "failed_dialogue_ids": [TARGET],
            "source_failure_evidence": "qa/e22_agentcut_v15_dia018_semantic_rollback_20260719/E22_REGRESSION_CI_V15_REPORT_ONLY_DIAGNOSTICS.json",
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
                "version": "V16",
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
                "task_id": "E22_AGENTCUT_V16_DIA016_LUMA_REPAIR_20260719",
                "episode": "E22",
                "status": "PROJECT_BUILT_PENDING_RENDER",
                "project": str(OUT_PROJECT),
                "output": str(OUT_VIDEO),
                "failed_only_repair": [TARGET],
                "replacement_source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
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
