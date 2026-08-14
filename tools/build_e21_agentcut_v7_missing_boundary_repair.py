#!/usr/bin/env python3
"""Build E21 V7 from all admitted missing-boundary video sources."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v6_tail_trim_20260719.json"
MAIN_RECEIPT = ROOT / "workflow/tasks/E21_v7_missing_boundary_videos_receipt_20260719.json"
R2_RECEIPT = ROOT / "workflow/tasks/E21_v7_failed_only_r2_receipt_20260719.json"
RECONCILIATION = ROOT / "qa/e21_agentcut_v6_tail_trim_20260719/E21_V6_VISUAL_BOUNDARY_RECONCILIATION.json"
OUT_PROJECT = ROOT / "configs/e21_agentcut_project_v7_missing_boundary_repair_20260719.json"
OUT_TIMELINE = ROOT / "qa/e21_agentcut_v7_missing_boundary_repair_20260719/E21_FINAL_TIMELINE_SHOTS_V7.json"
OUT_VIDEO = ROOT / "exports/e21/agentcut_v7_missing_boundary_repair_20260719/E21_AGENTCUT_V7_MISSING_BOUNDARY_REPAIR_NOT_FINAL.mp4"
FPS = 24.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def video_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=duration", "-of", "default=nw=1:nk=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = float(result.stdout.strip())
    return math.floor((raw + 1e-6) * FPS) / FPS


def admitted_sources(path: Path) -> dict[str, dict]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    return {
        task["dialogue_id"]: task
        for task in receipt["tasks"]
        if task.get("status") == "qa_pass" and task.get("output_path")
    }


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    reconciliation = json.loads(RECONCILIATION.read_text(encoding="utf-8"))
    targets = set(reconciliation["missing_dialogue_ids"])
    admitted = admitted_sources(MAIN_RECEIPT)
    admitted.update(admitted_sources(R2_RECEIPT))
    admitted = {key: value for key, value in admitted.items() if key in targets}
    if set(admitted) != targets:
        missing = sorted(targets - set(admitted))
        raise SystemExit(f"missing admitted V7 sources: {missing}")

    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    audio_clips = project["timeline"]["audioTracks"][0]["clips"]
    subtitle_clips = project["timeline"]["subtitleTracks"][0]["clips"]
    audio_by_dialogue = {
        clip["id"].replace("E21-", "").replace("-AUDIO", ""): clip for clip in audio_clips
    }
    subtitle_by_dialogue = {clip["dialogue_id"]: clip for clip in subtitle_clips}

    cursor = 0.0
    duration_changes = []
    for clip in video_clips:
        dialogue_id = clip["metadata"]["dialogue_id"]
        old_duration = float(clip["duration"])
        if dialogue_id in admitted:
            task = admitted[dialogue_id]
            source = Path(task["output_path"])
            safe_duration = video_duration(source)
            new_duration = min(old_duration, safe_duration)
            clip["source"] = str(source)
            clip["metadata"].update({
                "source_qa": "PASS_EDIT_ADMISSION_V7_MISSING_BOUNDARY",
                "v7_source_sha256": task.get("sha256") or sha256(source),
                "v7_task_id": task["task_id"],
                "v7_receipt": str((R2_RECEIPT if dialogue_id in admitted_sources(R2_RECEIPT) else MAIN_RECEIPT).relative_to(ROOT)),
            })
            audio_by_dialogue[dialogue_id]["source"] = str(source)
            if new_duration < old_duration - 1e-6:
                duration_changes.append({
                    "dialogue_id": dialogue_id,
                    "old_duration": old_duration,
                    "new_duration": new_duration,
                    "removed_seconds": round(old_duration - new_duration, 6),
                    "reason": "replacement source shorter than inherited edit window",
                })
            clip["duration"] = round(new_duration, 6)
            audio_by_dialogue[dialogue_id]["duration"] = round(new_duration, 6)
        clip["start"] = round(cursor, 6)
        audio_clip = audio_by_dialogue[dialogue_id]
        audio_clip["start"] = round(cursor, 6)
        subtitle = subtitle_by_dialogue[dialogue_id]
        subtitle["start"] = round(cursor + 0.12, 6)
        subtitle["duration"] = round(min(float(subtitle["duration"]), float(clip["duration"]) - 0.24), 6)
        cursor += float(clip["duration"])

    project["metadata"].update({
        "status": "V7_MISSING_BOUNDARY_REPAIR_NOT_FINAL",
        "version": "E21_AGENTCUT_V7_MISSING_BOUNDARY_REPAIR",
        "source_project": str(BASE),
        "change_scope": "replace exactly the 16 V6 missing visual boundaries with admitted V7 sources",
        "v7_main_receipt": str(MAIN_RECEIPT.relative_to(ROOT)),
        "v7_r2_receipt": str(R2_RECEIPT.relative_to(ROOT)),
        "duration_changes": duration_changes,
        "runtime_seconds": round(cursor, 6),
        "rollback": str(BASE.relative_to(ROOT)),
    })
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shots = [
        {
            "shot_id": clip["id"],
            "scene_id": clip["metadata"].get("scene_id"),
            "start": clip["start"],
            "end": round(float(clip["start"]) + float(clip["duration"]), 6),
        }
        for clip in video_clips
    ]
    OUT_TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    OUT_TIMELINE.write_text(json.dumps({"shots": shots}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "project": str(OUT_PROJECT),
        "timeline": str(OUT_TIMELINE),
        "replacements": len(admitted),
        "duration_changes": duration_changes,
        "runtime_seconds": round(cursor, 6),
        "output": str(OUT_VIDEO),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
