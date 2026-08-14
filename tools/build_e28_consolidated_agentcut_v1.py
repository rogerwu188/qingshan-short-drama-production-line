#!/usr/bin/env python3
"""Consolidate the 36 admitted E28 dialogue sources and build AgentCut V1."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from build_parallel_dialogue_agentcut_project import build_project


ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = [
    ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_VIDEO_BATCH_RECEIPT_20260720.json",
    ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R1_RECEIPT_20260720.json",
    ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R2_RECEIPT_20260720.json",
    ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R3_RECEIPT_20260720.json",
    ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R4_REFCAP3_RECEIPT_20260720.json",
    ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R5_PROMPTREPAIR_RECEIPT_20260720.json",
    ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R6_REMOTE_RETRY_RECEIPT_20260720.json",
    ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R7_SINGLE_REFERENCE_RECEIPT_20260720.json",
    ROOT / "workflow/tasks/E28_STANDARD_STORYBOARD_V1_SHEETBOUND_FAILED_ONLY_R8_DIA013_MOTION_REPAIR_RECEIPT_20260720.json",
]
SCENE_STATE = ROOT / "configs/e28_scene_state_v1_script_locked_20260719.json"
CONSOLIDATED = ROOT / "workflow/tasks/E28_CONSOLIDATED_36_SOURCE_ADMISSION_RECEIPT_20260720.json"
PROJECT = ROOT / "configs/e28_agentcut_project_v1_consolidated_36_20260720.json"
OUTPUT = ROOT / "exports/e28/agentcut_v1_consolidated_36_20260720/E28_AGENTCUT_V1_CONSOLIDATED_36_NOT_FINAL.mp4"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dialogue_index(task: dict) -> int:
    dialogue_id = task.get("dialogue_id") or task.get("dia_id")
    match = re.fullmatch(r"DIA-(\d{3})", str(dialogue_id))
    if not match:
        raise ValueError(f"invalid dialogue id: {dialogue_id}")
    return int(match.group(1))


def main() -> int:
    admitted: dict[str, dict] = {}
    for receipt_path in RECEIPTS:
        receipt = load(receipt_path)
        for source_task in receipt.get("tasks", []):
            if source_task.get("state") != "qa_pass" and source_task.get("status") != "qa_pass":
                continue
            task = dict(source_task)
            path = Path(task["output_path"])
            if not path.is_file():
                raise FileNotFoundError(path)
            task["status"] = "qa_pass"
            task["state"] = "qa_pass"
            task["sha256"] = sha256(path)
            task["admission_receipt"] = str(receipt_path)
            admitted[task["task_key"]] = task
    tasks = sorted(admitted.values(), key=dialogue_index)
    expected_ids = [f"DIA-{index:03d}" for index in range(1, 37)]
    actual_ids = [task.get("dialogue_id") or task.get("dia_id") for task in tasks]
    if actual_ids != expected_ids:
        raise SystemExit(f"expected 36 ordered dialogue IDs, got {actual_ids}")
    recorded_at = datetime.now().astimezone().isoformat(timespec="seconds")
    receipt = {
        "schema": "qingshan.consolidated_source_admission.v1",
        "episode": "E28",
        "status": "BATCH_COMPLETE",
        "source_count": 36,
        "expected_source_count": 36,
        "selection_policy": "latest QA-passed source per dialogue task; preserve passes and exclude every failed candidate",
        "source_receipts": [str(path) for path in RECEIPTS],
        "scene_contract_ref": str(SCENE_STATE),
        "tasks": tasks,
        "recorded_at": recorded_at,
    }
    CONSOLIDATED.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scene_state = load(SCENE_STATE)
    project = build_project(receipt, scene_state, OUTPUT)
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps({
        "status": "PASS",
        "sources": len(tasks),
        "runtime_seconds": project["metadata"]["runtime_seconds"],
        "receipt": str(CONSOLIDATED),
        "project": str(PROJECT),
        "output": str(OUTPUT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
