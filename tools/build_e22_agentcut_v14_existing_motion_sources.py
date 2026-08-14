#!/usr/bin/env python3
"""Build E22 V14 from V13 using already-generated, source-QA-passing motion alternatives."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e22_agentcut_project_v13_sentence_tail_repair_20260719.json"
OUT_PROJECT = ROOT / "configs/e22_agentcut_project_v14_existing_motion_sources_20260719.json"
OUT_TIMELINE = ROOT / "qa/e22_agentcut_v14_existing_motion_sources_20260719/E22_FINAL_TIMELINE_SHOTS_V14.json"
OUT_RECEIPT = ROOT / "workflow/tasks/E22_AGENTCUT_V14_EXISTING_MOTION_SOURCES_20260719.json"
OUT_VIDEO = ROOT / "exports/e22/agentcut_v14_existing_motion_sources_20260719/E22_AGENTCUT_V14_EXISTING_MOTION_SOURCES_NOT_FINAL.mp4"

REPLACEMENTS = {
    "DIA-002": "working_assets/e22_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-002-VIDEO_473ff180-a1dc-4b53-98b0-7f94afaf3231.mp4",
    "DIA-004": "working_assets/e22_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-004-VIDEO_9f545c1e-22ff-4f41-bd9e-24ea39c5908b.mp4",
    "DIA-006": "working_assets/e22_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-006-VIDEO_c0ef21a1-e0f8-4142-906f-4fe6c64ada0a.mp4",
    "DIA-014": "working_assets/e22_v4_dia014_failed_only_repair_20260719/candidates/E22_E22-DIA-014-VIDEO-R1_676fcccd-d46d-450c-b42c-b0132ddea11c.mp4",
    "DIA-015": "working_assets/e22_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-015-VIDEO_10e74664-ac01-47a9-8c02-9f716e14cbcc.mp4",
    "DIA-018": "working_assets/e22_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-018-VIDEO_1e270951-9652-4fd6-ac54-544516642a01.mp4",
    "DIA-019": "working_assets/e22_v4_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-019-VIDEO_a9807a4f-0159-42cc-8093-8cdc6f5e3950.mp4",
    "DIA-026": "working_assets/e22_v4_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-026-VIDEO_37b132d1-7285-49d2-bf88-4fa670b4cac0.mp4",
    "DIA-027": "working_assets/e22_v4_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-027-VIDEO_d87f5cca-e777-491f-9c07-223bb08ce1b4.mp4",
    "DIA-028": "working_assets/e22_v4_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-028-VIDEO_81240400-4bc0-49eb-a4b5-11c9c060a0f1.mp4",
    "DIA-032": "working_assets/e22_v5_failed_only_distinct_coverage_20260719/candidates/E22_E22-DIA-032-VIDEO-R2-DISTINCT_09086ef1-461b-46a2-ba83-1b77ef2e471b.mp4",
    "DIA-033": "working_assets/e22_v4_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-033-VIDEO_1a2082de-d427-43e0-a31e-436ff0b32646.mp4",
    "DIA-035": "working_assets/e22_v4_full_dialogue_parallel_20260719/candidates/E22_E22-DIA-035-VIDEO_f0254c26-74de-40f0-8076-32755948ebd9.mp4",
}


def dialogue_id(clip: dict) -> str | None:
    explicit = clip.get("metadata", {}).get("dialogue_id") or clip.get("dialogue_id")
    if explicit:
        return explicit
    clip_id = clip.get("id", "")
    for candidate in REPLACEMENTS:
        if candidate in clip_id:
            return candidate
    return None


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    replaced_by_group: dict[str, list[str]] = {}

    for track_group in ("videoTracks", "audioTracks"):
        replaced: set[str] = set()
        for track in project["timeline"][track_group]:
            for clip in track.get("clips", []):
                current_id = dialogue_id(clip)
                replacement = REPLACEMENTS.get(current_id)
                if not replacement:
                    continue
                replacement_path = ROOT / replacement
                if not replacement_path.is_file():
                    raise SystemExit(f"Missing replacement for {current_id}: {replacement_path}")
                clip["source"] = str(replacement_path)
                clip.setdefault("metadata", {})["v14_existing_motion_source"] = True
                clip["metadata"]["v14_replacement_source"] = replacement
                clip["metadata"]["v14_repair_reason"] = "Reduce V13 whole-film near-duplicate ratio using an existing source-QA-passing candidate"
                replaced.add(current_id)
        if replaced != set(REPLACEMENTS):
            raise SystemExit(
                f"{track_group} did not replace exactly the planned clips; "
                f"missing={sorted(set(REPLACEMENTS) - replaced)} extra={sorted(replaced - set(REPLACEMENTS))}"
            )
        replaced_by_group[track_group] = sorted(replaced)

    project["metadata"].update(
        {
            "status": "V14_EXISTING_MOTION_SOURCES_NOT_FINAL",
            "version": "E22_AGENTCUT_V14_EXISTING_MOTION_SOURCES",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Replace video and native audio sources for 13 V13 near-duplicate contributors with already-generated source-QA-passing candidates; preserve starts, durations, subtitles, and all other clips",
            "replacement_dialogue_ids": sorted(REPLACEMENTS),
            "source_failure_evidence": "qa/e22_agentcut_v13_sentence_tail_repair_20260719/E22_REGRESSION_CI_V13_REPORT_ONLY_DIAGNOSTICS.json",
            "source_cadence_evidence": "qa/e22_v13_remaining_near_duplicate_source_cadence_20260719",
            "rollback": str(BASE.relative_to(ROOT)),
        }
    )
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.parent.mkdir(parents=True, exist_ok=True)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    OUT_TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    OUT_TIMELINE.write_text(
        json.dumps(
            {
                "schema": "qingshan.final_timeline_shots.v1",
                "episode": "E22",
                "version": "V14",
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
                "task_id": "E22_AGENTCUT_V14_EXISTING_MOTION_SOURCES_20260719",
                "episode": "E22",
                "status": "PROJECT_BUILT_PENDING_RENDER",
                "project": str(OUT_PROJECT),
                "output": str(OUT_VIDEO),
                "replacement_count": len(REPLACEMENTS),
                "replacement_dialogue_ids": sorted(REPLACEMENTS),
                "source_policy": "EXISTING_SOURCE_QA_PASS_ONLY_NO_EXTERNAL_REROLL",
                "rollback": str(BASE),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "project": str(OUT_PROJECT),
                "timeline": str(OUT_TIMELINE),
                "receipt": str(OUT_RECEIPT),
                "output": str(OUT_VIDEO),
                "replaced_by_group": replaced_by_group,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
