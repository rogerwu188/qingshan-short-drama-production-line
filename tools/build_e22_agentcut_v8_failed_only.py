#!/usr/bin/env python3
"""Build E22 AgentCut V8 by replacing only DIA-006 and DIA-028."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e22_agentcut_project_v7_shot_specific_boundaries_20260719.json"
RECEIPT = ROOT / "workflow/tasks/E22_v8_failed_only_video_parallel_receipt_20260719.json"
OUT = ROOT / "configs/e22_agentcut_project_v8_failed_only_20260719.json"
QA_DIR = ROOT / "qa/e22_agentcut_v8_failed_only_20260719"
TIMELINE_OUT = QA_DIR / "E22_FINAL_TIMELINE_SHOTS_V8.json"
EXPECTED = {"DIA-006", "DIA-028"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def admitted_sources() -> dict[str, dict]:
    payload = load(RECEIPT)
    if payload.get("status") != "BATCH_COMPLETE":
        raise SystemExit(f"V8 receipt is not complete: {payload.get('status')}")
    sources: dict[str, dict] = {}
    for row in payload.get("tasks", []):
        dia_id = row.get("dialogue_id") or row.get("dia_id") or row.get("source_id")
        if dia_id not in EXPECTED or row.get("state") != "qa_pass":
            continue
        source = Path(row["output_path"]).resolve()
        if not source.is_file():
            raise SystemExit(f"admitted source missing: {source}")
        sources[dia_id] = {
            "path": str(source),
            "sha256": row.get("sha256") or hashlib.sha256(source.read_bytes()).hexdigest(),
            "task_id": row.get("task_id"),
        }
    if set(sources) != EXPECTED:
        raise SystemExit(f"V8 requires two QA-passed replacements; found={sorted(sources)}")
    return sources


def main() -> int:
    project = load(BASE)
    sources = admitted_sources()
    video_replaced: set[str] = set()
    audio_replaced: set[str] = set()
    for track in project["timeline"]["videoTracks"]:
        for clip in track.get("clips", []):
            dia_id = (clip.get("metadata") or {}).get("dialogue_id")
            if dia_id not in sources:
                continue
            clip["source"] = sources[dia_id]["path"]
            clip.setdefault("metadata", {}).update({
                "source_qa": "PASS_EDIT_ADMISSION_V8_FAILED_ONLY",
                "v8_source_sha256": sources[dia_id]["sha256"],
                "v8_task_id": sources[dia_id]["task_id"],
            })
            video_replaced.add(dia_id)
    for track in project["timeline"]["audioTracks"]:
        for clip in track.get("clips", []):
            dia_id = clip.get("id", "").removeprefix("E22-").removesuffix("-AUDIO")
            if dia_id not in sources:
                continue
            clip["source"] = sources[dia_id]["path"]
            audio_replaced.add(dia_id)
    if video_replaced != EXPECTED or audio_replaced != EXPECTED:
        raise SystemExit(f"V8 replacement mismatch video={sorted(video_replaced)} audio={sorted(audio_replaced)}")

    project["metadata"].update({
        "status": "FAILED_ONLY_SOURCE_REPAIR_V8_NOT_FINAL",
        "parent_project": str(BASE.relative_to(ROOT)),
        "failed_only_receipt": str(RECEIPT.relative_to(ROOT)),
        "failed_only_replacements": sorted(EXPECTED),
        "rollback": str(BASE.relative_to(ROOT)),
    })
    project["output"]["path"] = str(
        ROOT / "exports/e22/agentcut_v8_failed_only_20260719/E22_AGENTCUT_V8_FAILED_ONLY_NOT_FINAL.mp4"
    )
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows = []
    for track in project["timeline"]["videoTracks"]:
        for clip in track.get("clips", []):
            start = float(clip["start"])
            rows.append({
                "shot_id": clip["id"],
                "scene_id": (clip.get("metadata") or {}).get("scene_id"),
                "start": start,
                "end": start + float(clip["duration"]),
            })
    rows.sort(key=lambda row: row["start"])
    QA_DIR.mkdir(parents=True, exist_ok=True)
    TIMELINE_OUT.write_text(json.dumps({"shots": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "project": str(OUT),
        "timeline": str(TIMELINE_OUT),
        "video_replacements": len(video_replaced),
        "audio_replacements": len(audio_replaced),
        "output": project["output"]["path"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
