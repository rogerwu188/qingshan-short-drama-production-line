#!/usr/bin/env python3
"""Build E21 V8 from V7 with three admitted speech sources and the proven tail trim."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v7_missing_boundary_repair_20260719.json"
R1_RECEIPT = ROOT / "workflow/tasks/E21_v8_failed_speech_r1_receipt_20260719.json"
R3_RECEIPT = ROOT / "workflow/tasks/E21_v8_dia037_failed_only_r3_video_receipt_20260719.json"
DIA020_ADJUDICATION = ROOT / "qa/e21_v8_failed_speech_r1_20260719/E21_DIA020_OCR_MACHINE_ADJUDICATION_V8.json"
OUT_PROJECT = ROOT / "configs/e21_agentcut_project_v8_failed_speech_repair_20260719.json"
OUT_TIMELINE = ROOT / "qa/e21_agentcut_v8_failed_speech_repair_20260719/E21_FINAL_TIMELINE_SHOTS_V8.json"
OUT_VIDEO = ROOT / "exports/e21/agentcut_v8_failed_speech_repair_20260719/E21_AGENTCUT_V8_FAILED_SPEECH_REPAIR_NOT_FINAL.mp4"
REQUIRED = {"DIA-020", "DIA-021", "DIA-037"}
TAIL_DIALOGUE_ID = "DIA-026"
TAIL_DURATION = 5.208333


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def admitted_sources() -> dict[str, dict]:
    r1 = json.loads(R1_RECEIPT.read_text(encoding="utf-8"))
    r3 = json.loads(R3_RECEIPT.read_text(encoding="utf-8"))
    adjudication = json.loads(DIA020_ADJUDICATION.read_text(encoding="utf-8"))
    if adjudication.get("status") != "PASS" or adjudication.get("dialogue_id") != "DIA-020":
        raise SystemExit("DIA-020 requires the exact-frame OCR machine adjudication PASS")
    admitted: dict[str, dict] = {}
    for task in r1.get("tasks", []):
        dialogue_id = task.get("dialogue_id")
        if dialogue_id == "DIA-020" and task.get("output_path") == adjudication.get("candidate"):
            admitted[dialogue_id] = {**task, "receipt": str(R1_RECEIPT.relative_to(ROOT)), "adjudication": str(DIA020_ADJUDICATION.relative_to(ROOT))}
        elif dialogue_id == "DIA-021" and task.get("state") == "qa_pass":
            admitted[dialogue_id] = {**task, "receipt": str(R1_RECEIPT.relative_to(ROOT))}
    for task in r3.get("tasks", []):
        if task.get("dialogue_id") == "DIA-037" and task.get("state") == "qa_pass":
            admitted["DIA-037"] = {**task, "receipt": str(R3_RECEIPT.relative_to(ROOT))}
    return admitted


def dialogue_id(clip: dict) -> str | None:
    value = clip.get("metadata", {}).get("dialogue_id")
    if value:
        return value
    return clip.get("id", "").replace("E21-", "").replace("-VIDEO", "").replace("-AUDIO", "")


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    admitted = admitted_sources()
    if set(admitted) != REQUIRED:
        raise SystemExit(f"V8 requires exactly {sorted(REQUIRED)}; admitted={sorted(admitted)}")

    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    audio_clips = project["timeline"]["audioTracks"][0]["clips"]
    subtitle_clips = project["timeline"]["subtitleTracks"][0]["clips"]
    replacements = {"video": 0, "audio": 0}
    for clips, label in ((video_clips, "video"), (audio_clips, "audio")):
        for clip in clips:
            dia_id = dialogue_id(clip)
            task = admitted.get(dia_id)
            if not task:
                continue
            source = Path(task["output_path"])
            clip["source"] = str(source)
            metadata = clip.setdefault("metadata", {})
            metadata["source_qa"] = "PASS_EDIT_ADMISSION_V8_FAILED_SPEECH_REPAIR"
            metadata["v8_source_sha256"] = task.get("sha256") or sha256(source)
            metadata["v8_task_id"] = task.get("task_id")
            metadata["v8_receipt"] = task["receipt"]
            if task.get("adjudication"):
                metadata["v8_ocr_adjudication"] = task["adjudication"]
            replacements[label] += 1

    if replacements != {"video": 3, "audio": 3}:
        raise SystemExit(f"unexpected replacement counts: {replacements}")

    trim_video = next(clip for clip in video_clips if dialogue_id(clip) == TAIL_DIALOGUE_ID)
    old_tail_duration = float(trim_video["duration"])
    removed = old_tail_duration - TAIL_DURATION
    if removed <= 0:
        raise SystemExit("DIA-026 trim must remove the V7 short-freeze tail")
    trim_start = float(trim_video["start"])

    for clips in (video_clips, audio_clips, subtitle_clips):
        for clip in clips:
            dia_id = dialogue_id(clip) if clips is not subtitle_clips else clip.get("dialogue_id")
            if dia_id == TAIL_DIALOGUE_ID:
                clip["duration"] = round(min(float(clip["duration"]), TAIL_DURATION), 6)
                if clips is video_clips:
                    clip.setdefault("metadata", {})["v8_tail_trim"] = {
                        "old_duration": old_tail_duration,
                        "new_duration": TAIL_DURATION,
                        "removed_seconds": round(removed, 6),
                        "reason": "V7 whole-film cadence localized an unmotivated freeze from 170.667s through the DIA-026 tail",
                    }
            elif float(clip.get("start", 0.0)) > trim_start:
                clip["start"] = round(float(clip["start"]) - removed, 6)

    runtime = round(float(project["metadata"].get("runtime_seconds", 174.833345)) - removed, 6)
    project["metadata"].update(
        {
            "status": "V8_FAILED_SPEECH_REPAIR_NOT_FINAL",
            "version": "E21_AGENTCUT_V8_FAILED_SPEECH_REPAIR",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Replace only DIA-020/021/037 and trim the proven DIA-026 freeze tail; no new cuts, inserts, retime, padding or BGM",
            "runtime_seconds": runtime,
            "v8_receipts": [str(R1_RECEIPT.relative_to(ROOT)), str(R3_RECEIPT.relative_to(ROOT))],
            "rollback": str(BASE.relative_to(ROOT)),
        }
    )
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    OUT_TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    OUT_TIMELINE.write_text(
        json.dumps(
            {
                "schema": "qingshan.final_timeline_shots.v1",
                "episode": "E21",
                "version": "V8",
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
    print(json.dumps({"status": "PASS", "project": str(OUT_PROJECT), "timeline": str(OUT_TIMELINE), "replacements": replacements, "tail_removed_seconds": round(removed, 6), "runtime_seconds": runtime, "output": str(OUT_VIDEO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
