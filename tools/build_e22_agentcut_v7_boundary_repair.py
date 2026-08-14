#!/usr/bin/env python3
"""Build E22 AgentCut V7 by replacing only the 14 boundary-repair sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e22_agentcut_project_v6_distinct_coverage_repair_20260719.json"
MAIN_RECEIPT = ROOT / "workflow/tasks/E22_v7_boundary_video_parallel_receipt_20260719.json"
REPAIR_RECEIPTS = [
    ROOT / "workflow/tasks/E22_v7_dia003_failed_only_r2_receipt_20260719.json",
    ROOT / "workflow/tasks/E22_v7_dia010_failed_only_r2_receipt_20260719.json",
]
OUT = ROOT / "configs/e22_agentcut_project_v7_shot_specific_boundaries_20260719.json"
TIMELINE_OUT = ROOT / "qa/e22_agentcut_v7_shot_specific_boundaries_20260719/E22_FINAL_TIMELINE_SHOTS_V7.json"
EXPECTED_REPLACEMENTS = {
    "DIA-002", "DIA-003", "DIA-004", "DIA-005", "DIA-006", "DIA-009", "DIA-010",
    "DIA-019", "DIA-020", "DIA-027", "DIA-028", "DIA-029", "DIA-032", "DIA-033",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def admitted_sources() -> dict[str, dict]:
    rows = load(MAIN_RECEIPT).get("tasks", [])
    for receipt in REPAIR_RECEIPTS:
        payload = load(receipt)
        if payload.get("status") != "BATCH_COMPLETE":
            raise SystemExit(f"repair receipt is not complete: {receipt}")
        rows.extend(payload.get("tasks", []))

    sources: dict[str, dict] = {}
    for row in rows:
        dia_id = row.get("dialogue_id") or row.get("dia_id") or row.get("source_id")
        if dia_id not in EXPECTED_REPLACEMENTS or row.get("state") != "qa_pass":
            continue
        source = Path(row["output_path"]).resolve()
        if not source.is_file():
            raise SystemExit(f"admitted source missing: {source}")
        sources[dia_id] = {
            "path": str(source),
            "sha256": row.get("sha256") or hashlib.sha256(source.read_bytes()).hexdigest(),
            "task_id": row.get("task_id"),
            "task_key": row.get("task_key"),
        }

    if set(sources) != EXPECTED_REPLACEMENTS:
        missing = sorted(EXPECTED_REPLACEMENTS - set(sources))
        raise SystemExit(f"V7 requires exactly 14 QA-passed replacements; missing={missing}")
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
                "source_qa": "PASS_EDIT_ADMISSION_V7_SHOT_SPECIFIC_BOUNDARY",
                "v7_source_sha256": sources[dia_id]["sha256"],
                "v7_task_id": sources[dia_id]["task_id"],
            })
            video_replaced.add(dia_id)

    for track in project["timeline"]["audioTracks"]:
        for clip in track.get("clips", []):
            dia_id = clip.get("id", "").removeprefix("E22-").removesuffix("-AUDIO")
            if dia_id not in sources:
                continue
            clip["source"] = sources[dia_id]["path"]
            audio_replaced.add(dia_id)

    if video_replaced != EXPECTED_REPLACEMENTS or audio_replaced != EXPECTED_REPLACEMENTS:
        raise SystemExit(
            "V7 replacement reconciliation failed: "
            f"video={sorted(video_replaced)} audio={sorted(audio_replaced)}"
        )

    project["metadata"].update({
        "status": "SHOT_SPECIFIC_BOUNDARY_REPAIR_V7_NOT_FINAL",
        "parent_project": str(BASE.relative_to(ROOT)),
        "boundary_repair_receipts": [str(MAIN_RECEIPT.relative_to(ROOT))]
        + [str(path.relative_to(ROOT)) for path in REPAIR_RECEIPTS],
        "boundary_repair_count": len(EXPECTED_REPLACEMENTS),
        "rollback": str(BASE.relative_to(ROOT)),
    })
    project["output"]["path"] = str(
        ROOT / "exports/e22/agentcut_v7_shot_specific_boundaries_20260719/E22_AGENTCUT_V7_SHOT_SPECIFIC_BOUNDARIES_NOT_FINAL.mp4"
    )
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    timeline_rows = []
    for track in project["timeline"]["videoTracks"]:
        for clip in track.get("clips", []):
            start = float(clip["start"])
            duration = float(clip["duration"])
            timeline_rows.append({
                "shot_id": clip["id"],
                "scene_id": (clip.get("metadata") or {}).get("scene_id"),
                "start": start,
                "end": start + duration,
            })
    timeline_rows.sort(key=lambda row: row["start"])
    TIMELINE_OUT.parent.mkdir(parents=True, exist_ok=True)
    TIMELINE_OUT.write_text(json.dumps({"shots": timeline_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
