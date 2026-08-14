#!/usr/bin/env python3
"""Build E21 AgentCut V5 from the 20 admitted boundary-repair sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v4_us_drama_rewrite_20260719.json"
RECEIPTS = [
    ROOT / "workflow/tasks/E21_v5_boundary_video_parallel_receipt_20260719.json",
    ROOT / "workflow/tasks/E21_v5_dia012_failed_only_r4_receipt_20260719.json",
    ROOT / "workflow/tasks/E21_v5_dia007_duration_repair_r2_receipt_20260719.json",
]
OUT = ROOT / "configs/e21_agentcut_project_v5_boundary_repair_20260719.json"
QA_DIR = ROOT / "qa/e21_agentcut_v5_boundary_repair_20260719"
TIMELINE_OUT = QA_DIR / "E21_FINAL_TIMELINE_SHOTS_V5.json"
EXPECTED = {
    "DIA-002", "DIA-003", "DIA-004", "DIA-007", "DIA-011", "DIA-012",
    "DIA-013", "DIA-014", "DIA-016", "DIA-020", "DIA-021", "DIA-024",
    "DIA-026", "DIA-027", "DIA-028", "DIA-029", "DIA-031", "DIA-033",
    "DIA-036", "DIA-037",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def admitted_sources() -> dict[str, dict]:
    sources: dict[str, dict] = {}
    for receipt in RECEIPTS:
        payload = load(receipt)
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
                "receipt": str(receipt.relative_to(ROOT)),
            }
    if set(sources) != EXPECTED:
        raise SystemExit(f"V5 requires 20 QA-passed replacements; missing={sorted(EXPECTED - set(sources))}")
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
            source = sources[dia_id]
            clip["source"] = source["path"]
            clip.setdefault("metadata", {}).update({
                "source_qa": "PASS_EDIT_ADMISSION_V5_BOUNDARY_REPAIR",
                "v5_source_sha256": source["sha256"],
                "v5_task_id": source["task_id"],
                "v5_receipt": source["receipt"],
            })
            video_replaced.add(dia_id)

    for track in project["timeline"]["audioTracks"]:
        for clip in track.get("clips", []):
            dia_id = clip.get("id", "").removeprefix("E21-").removesuffix("-AUDIO")
            if dia_id not in sources:
                continue
            clip["source"] = sources[dia_id]["path"]
            audio_replaced.add(dia_id)

    if video_replaced != EXPECTED or audio_replaced != EXPECTED:
        raise SystemExit(
            f"V5 replacement mismatch video={sorted(video_replaced)} audio={sorted(audio_replaced)}"
        )

    project["metadata"].update({
        "status": "BOUNDARY_REPAIR_V5_NOT_FINAL",
        "parent_project": str(BASE.relative_to(ROOT)),
        "boundary_repair_receipts": [str(path.relative_to(ROOT)) for path in RECEIPTS],
        "boundary_repair_count": len(EXPECTED),
        "rollback": str(BASE.relative_to(ROOT)),
    })
    project["output"]["path"] = str(
        ROOT / "exports/e21/agentcut_v5_boundary_repair_20260719/E21_AGENTCUT_V5_BOUNDARY_REPAIR_NOT_FINAL.mp4"
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
