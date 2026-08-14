#!/usr/bin/env python3
"""Build E22 V11 from V10 with two audible sources and one frozen-tail trim."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e22_agentcut_project_v10_repeat_repair_20260719.json"
RECEIPT = ROOT / "workflow/tasks/E22_v11_failed_dialogue_repairs_receipt_20260719.json"
OUT_PROJECT = ROOT / "configs/e22_agentcut_project_v11_audio_tail_repair_20260719.json"
OUT_TIMELINE = ROOT / "qa/e22_agentcut_v11_audio_tail_repair_20260719/E22_FINAL_TIMELINE_SHOTS_V11.json"
OUT_VIDEO = ROOT / "exports/e22/agentcut_v11_audio_tail_repair_20260719/E22_AGENTCUT_V11_AUDIO_TAIL_REPAIR_NOT_FINAL.mp4"
TRIM_DIALOGUE_ID = "DIA-025"
TRIMMED_DURATION = 4.333333


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    admitted = {
        task["dialogue_id"]: task
        for task in receipt["tasks"]
        if task.get("status") == "qa_pass" and task.get("output_path")
    }
    if set(admitted) != {"DIA-026", "DIA-034"}:
        raise SystemExit("V11 requires admitted DIA-026 and DIA-034 sources")

    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    trim_clip = next(clip for clip in video_clips if clip.get("metadata", {}).get("dialogue_id") == TRIM_DIALOGUE_ID)
    old_duration = float(trim_clip["duration"])
    trim_start = float(trim_clip["start"])
    delta = old_duration - TRIMMED_DURATION
    if delta <= 0:
        raise SystemExit("trim duration must be shorter than the V10 source window")

    replacements = 0
    for track_kind in ("videoTracks", "audioTracks"):
        for track in project["timeline"][track_kind]:
            for clip in track.get("clips", []):
                dialogue_id = clip.get("metadata", {}).get("dialogue_id")
                if dialogue_id is None:
                    dialogue_id = clip.get("id", "").replace("E22-", "").replace("-VIDEO", "").replace("-AUDIO", "")
                if dialogue_id in admitted:
                    task = admitted[dialogue_id]
                    clip["source"] = task["output_path"]
                    if track_kind == "videoTracks":
                        metadata = clip.setdefault("metadata", {})
                        metadata["source_qa"] = "PASS_EDIT_ADMISSION_V11_AUDIBLE_DIALOGUE"
                        metadata["v11_source_sha256"] = task.get("sha256") or sha256(Path(task["output_path"]))
                        metadata["v11_task_id"] = task["task_id"]
                        metadata["v11_receipt"] = str(RECEIPT.relative_to(ROOT))
                    replacements += 1
                if dialogue_id == TRIM_DIALOGUE_ID:
                    clip["duration"] = TRIMMED_DURATION
                    if track_kind == "videoTracks":
                        metadata = clip.setdefault("metadata", {})
                        metadata["v11_tail_trim"] = {
                            "old_duration": old_duration,
                            "new_duration": TRIMMED_DURATION,
                            "removed_seconds": round(delta, 6),
                            "reason": "V10 final cadence freeze begins at source/timeline local 4.417s after dialogue completed by 2.0s",
                        }
                elif float(clip.get("start", 0.0)) > trim_start:
                    clip["start"] = round(float(clip["start"]) - delta, 6)

    for track in project["timeline"]["subtitleTracks"]:
        for clip in track.get("clips", []):
            dialogue_id = clip.get("dialogue_id")
            if dialogue_id == TRIM_DIALOGUE_ID:
                clip["duration"] = round(TRIMMED_DURATION - 0.24, 6)
            elif float(clip.get("start", 0.0)) > trim_start:
                clip["start"] = round(float(clip["start"]) - delta, 6)

    project["metadata"].update({
        "status": "V11_AUDIO_TAIL_REPAIR_NOT_FINAL",
        "version": "E22_AGENTCUT_V11_AUDIO_TAIL_REPAIR",
        "source_project": str(BASE),
        "change_scope": "DIA-026/DIA-034 audible native sources plus DIA-025 frozen-tail trim only",
        "v11_receipt": str(RECEIPT.relative_to(ROOT)),
        "rollback": str(BASE.relative_to(ROOT)),
    })
    if "runtime_seconds" in project["metadata"]:
        project["metadata"]["runtime_seconds"] = round(float(project["metadata"]["runtime_seconds"]) - delta, 6)
    project["output"]["path"] = str(OUT_VIDEO)

    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shots = [
        {
            "shot_id": clip["id"],
            "scene_id": clip.get("metadata", {}).get("scene_id"),
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
        "video_replacements": replacements // 2,
        "audio_replacements": replacements // 2,
        "trim_dialogue_id": TRIM_DIALOGUE_ID,
        "removed_seconds": round(delta, 6),
        "output": str(OUT_VIDEO),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
