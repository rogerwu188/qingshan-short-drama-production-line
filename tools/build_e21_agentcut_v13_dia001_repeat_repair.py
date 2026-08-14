#!/usr/bin/env python3
"""Build E21 V13 by replacing only the CI-isolated DIA-001 repeat source."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v12_dia007_audio_tail_repair_20260719.json"
SOURCE = ROOT / "working_assets/e21_v12_dia001_repeat_failed_only_r1_20260719/candidates/E21_E21-DIA-001-VIDEO-V12-REPEAT-R1_aa8f3638-3888-49a6-9ab3-2a62ba4b386f.mp4"
SOURCE_QA = ROOT / "qa/e21_v12_dia001_repeat_failed_only_r1_20260719/E21_DIA001_SOURCE_ADMISSION_QA_R2.json"
OUT_PROJECT = ROOT / "configs/e21_agentcut_project_v13_dia001_repeat_repair_20260719.json"
OUT_TIMELINE = ROOT / "qa/e21_agentcut_v13_dia001_repeat_repair_20260719/E21_FINAL_TIMELINE_SHOTS_V13.json"
OUT_RECEIPT = ROOT / "workflow/tasks/E21_AGENTCUT_V13_DIA001_REPEAT_REPAIR_20260719.json"
OUT_VIDEO = ROOT / "exports/e21/agentcut_v13_dia001_repeat_repair_20260719/E21_AGENTCUT_V13_DIA001_REPEAT_REPAIR_NOT_FINAL.mp4"


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    qa = json.loads(SOURCE_QA.read_text(encoding="utf-8"))
    source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if qa.get("status") != "PASS" or qa.get("candidate_sha256") != source_sha:
        raise SystemExit("DIA-001 candidate lacks matching PASS source-admission evidence")

    replacements = []
    for track_group in ("videoTracks", "audioTracks"):
        matches = []
        for track in project["timeline"][track_group]:
            for clip in track.get("clips", []):
                if "DIA-001" not in clip.get("id", ""):
                    continue
                clip["source"] = str(SOURCE)
                metadata = clip.setdefault("metadata", {})
                metadata["v13_dia001_repeat_repair"] = True
                metadata["v13_source_sha256"] = source_sha
                metadata["v13_source_task_id"] = qa["remote_task_id"]
                metadata["v13_source_asr"] = qa["asr_transcript"]
                metadata["v13_source_motion_mean"] = qa["motion_mean"]
                metadata["v13_source_near_duplicate_ratio"] = qa["near_duplicate_ratio"]
                metadata["source_qa"] = "PASS_DIA001_ASR_CADENCE_OCR_V13"
                matches.append(clip["id"])
        if len(matches) != 1:
            raise SystemExit(f"Expected one DIA-001 clip in {track_group}, got {matches}")
        replacements.extend(matches)

    project["metadata"].update(
        {
            "status": "V13_DIA001_REPEAT_REPAIR_NOT_FINAL",
            "version": "E21_AGENTCUT_V13_DIA001_REPEAT_REPAIR",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Replace only DIA-001 after frozen-threshold CI isolated its adjacent and nonadjacent repeat clusters",
            "failed_only_repair": ["DIA-001"],
            "source_qa_evidence": str(SOURCE_QA.relative_to(ROOT)),
            "rollback": str(BASE.relative_to(ROOT)),
        }
    )
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    clips = project["timeline"]["videoTracks"][0]["clips"]
    OUT_TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    OUT_TIMELINE.write_text(
        json.dumps(
            {
                "schema": "qingshan.final_timeline_shots.v1",
                "episode": "E21",
                "version": "V13",
                "shots": [
                    {
                        "shot_id": clip["id"],
                        "scene_id": clip.get("metadata", {}).get("scene_id"),
                        "start": clip["start"],
                        "end": round(float(clip["start"]) + float(clip["duration"]), 6),
                    }
                    for clip in clips
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
                "task_id": "E21_AGENTCUT_V13_DIA001_REPEAT_REPAIR_20260719",
                "episode": "E21",
                "status": "PROJECT_BUILT_PENDING_RENDER",
                "project": str(OUT_PROJECT),
                "output": str(OUT_VIDEO),
                "failed_only_repair": ["DIA-001"],
                "replacement_source_sha256": source_sha,
                "source_qa": str(SOURCE_QA),
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
