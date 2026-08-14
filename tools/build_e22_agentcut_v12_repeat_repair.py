#!/usr/bin/env python3
"""Build E22 V12 from V11 by replacing only six admitted repeat-cluster sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e22_agentcut_project_v11_audio_tail_repair_20260719.json"
MAIN_RECEIPT = ROOT / "workflow/tasks/E22_v12_motion_repeat_failed_only_receipt_20260719.json"
DIA025_RECEIPT = ROOT / "workflow/tasks/E22_v12_dia025_failed_only_r2_video_receipt_20260719.json"
OUT_PROJECT = ROOT / "configs/e22_agentcut_project_v12_repeat_repair_20260719.json"
OUT_TIMELINE = ROOT / "qa/e22_agentcut_v12_repeat_repair_20260719/E22_FINAL_TIMELINE_SHOTS_V12.json"
OUT_VIDEO = ROOT / "exports/e22/agentcut_v12_repeat_repair_20260719/E22_AGENTCUT_V12_REPEAT_REPAIR_NOT_FINAL.mp4"
REQUIRED = {"DIA-005", "DIA-007", "DIA-020", "DIA-025", "DIA-029", "DIA-034"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def admitted_sources() -> dict[str, dict]:
    admitted: dict[str, dict] = {}
    for receipt_path in (MAIN_RECEIPT, DIA025_RECEIPT):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        for task in receipt.get("tasks", []):
            if task.get("state") not in {"qa_pass", "image_pass"} and task.get("status") != "qa_pass":
                continue
            dialogue_id = task.get("dialogue_id")
            if dialogue_id in REQUIRED and task.get("output_path"):
                admitted[dialogue_id] = {**task, "receipt": str(receipt_path.relative_to(ROOT))}
    return admitted


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    admitted = admitted_sources()
    if set(admitted) != REQUIRED:
        raise SystemExit(f"V12 requires exactly {sorted(REQUIRED)}; admitted={sorted(admitted)}")

    replacements = {"video": 0, "audio": 0}
    for track_kind, label in (("videoTracks", "video"), ("audioTracks", "audio")):
        for track in project["timeline"][track_kind]:
            for clip in track.get("clips", []):
                dialogue_id = clip.get("metadata", {}).get("dialogue_id")
                if dialogue_id is None:
                    dialogue_id = clip.get("id", "").replace("E22-", "").replace("-VIDEO", "").replace("-AUDIO", "")
                task = admitted.get(dialogue_id)
                if not task:
                    continue
                source = Path(task["output_path"])
                clip["source"] = str(source)
                metadata = clip.setdefault("metadata", {})
                metadata["source_qa"] = "PASS_EDIT_ADMISSION_V12_REPEAT_REPAIR"
                metadata["v12_source_sha256"] = task.get("sha256") or sha256(source)
                metadata["v12_task_id"] = task.get("task_id")
                metadata["v12_receipt"] = task["receipt"]
                replacements[label] += 1

    if replacements != {"video": 6, "audio": 6}:
        raise SystemExit(f"unexpected replacement counts: {replacements}")

    project["metadata"].update(
        {
            "status": "V12_REPEAT_REPAIR_NOT_FINAL",
            "version": "E22_AGENTCUT_V12_REPEAT_REPAIR",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Replace only DIA-005/007/020/025/029/034 with admitted differentiated native-speed sources; no new cuts",
            "v12_receipts": [str(MAIN_RECEIPT.relative_to(ROOT)), str(DIA025_RECEIPT.relative_to(ROOT))],
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
                "version": "V12",
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
    print(
        json.dumps(
            {
                "status": "PASS",
                "project": str(OUT_PROJECT),
                "timeline": str(OUT_TIMELINE),
                "replacements": replacements,
                "output": str(OUT_VIDEO),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
