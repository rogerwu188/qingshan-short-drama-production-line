#!/usr/bin/env python3
"""Build E21 V12 by extending only DIA-007's audio admission to match video."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v11_sentence_and_runtime_repair_20260719.json"
QA = ROOT / "qa/e21_agentcut_v11_sentence_and_runtime_repair_20260719/E21_FINAL_SENTENCE_COMPLETENESS_V11.json"
OUT_PROJECT = ROOT / "configs/e21_agentcut_project_v12_dia007_audio_tail_repair_20260719.json"
OUT_TIMELINE = ROOT / "qa/e21_agentcut_v12_dia007_audio_tail_repair_20260719/E21_FINAL_TIMELINE_SHOTS_V12.json"
OUT_RECEIPT = ROOT / "workflow/tasks/E21_AGENTCUT_V12_DIA007_AUDIO_TAIL_REPAIR_20260719.json"
OUT_VIDEO = ROOT / "exports/e21/agentcut_v12_dia007_audio_tail_repair_20260719/E21_AGENTCUT_V12_DIA007_AUDIO_TAIL_REPAIR_NOT_FINAL.mp4"


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    qa = json.loads(QA.read_text(encoding="utf-8"))
    if qa.get("failures") != ["DIA-007"]:
        raise SystemExit(f"Expected isolated DIA-007 failure, got {qa.get('failures')}")

    video = next(
        clip
        for track in project["timeline"]["videoTracks"]
        for clip in track.get("clips", [])
        if "DIA-007" in clip.get("id", "")
    )
    audio = next(
        clip
        for track in project["timeline"]["audioTracks"]
        for clip in track.get("clips", [])
        if "DIA-007" in clip.get("id", "")
    )
    if abs(float(video["duration"]) - 7.041667) > 0.001 or abs(float(audio["duration"]) - 6.041667) > 0.001:
        raise SystemExit(f"Unexpected DIA-007 admission: video={video['duration']} audio={audio['duration']}")
    audio["duration"] = float(video["duration"])
    audio.setdefault("metadata", {})["v12_audio_tail_extension_seconds"] = 1.0
    audio["metadata"]["source_qa"] = "REPAIR_ISOLATED_AUDIO_ADMISSION_TO_MATCH_VIDEO_V12"

    project["metadata"].update(
        {
            "status": "V12_DIA007_AUDIO_TAIL_REPAIR_NOT_FINAL",
            "version": "E21_AGENTCUT_V12_DIA007_AUDIO_TAIL_REPAIR",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Extend only DIA-007 audio admission by one second; timeline starts and video/subtitle admission remain unchanged",
            "failed_only_repair": ["DIA-007"],
            "source_qa_evidence": str(QA.relative_to(ROOT)),
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
                "version": "V12",
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
                "task_id": "E21_AGENTCUT_V12_DIA007_AUDIO_TAIL_REPAIR_20260719",
                "episode": "E21",
                "status": "PROJECT_BUILT_PENDING_RENDER",
                "project": str(OUT_PROJECT),
                "output": str(OUT_VIDEO),
                "failed_only_repair": ["DIA-007"],
                "source_qa": str(QA),
                "source_project_sha256": hashlib.sha256(BASE.read_bytes()).hexdigest(),
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
