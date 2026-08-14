#!/usr/bin/env python3
"""Build AgentCut v15 by replacing only E27 N08 and N19 with R2 sources."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
BASE_PROJECT = ROOT / "configs/e27_agentcut_project_v14_writer_agent_v040_20260720.json"
R2_RECEIPT = ROOT / "workflow/tasks/E27_WRITER_AGENT_V040_VIDEO_NATIVE_TEXT_R2_RECEIPT_20260720.json"
PROJECT = ROOT / "configs/e27_agentcut_project_v15_writer_agent_v040_native_text_r2_20260720.json"
OUTPUT = ROOT / "exports/e27/agentcut_v15_writer_agent_v040_native_text_r2_20260720/E27_AGENTCUT_V15_WRITER_AGENT_V040_NATIVE_TEXT_R2_NOT_FINAL.mp4"
BUILD_RECEIPT = ROOT / "workflow/tasks/E27_AGENTCUT_V15_WRITER_AGENT_V040_BUILD_RECEIPT_20260720.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    base = json.loads(BASE_PROJECT.read_text(encoding="utf-8"))
    receipt = json.loads(R2_RECEIPT.read_text(encoding="utf-8"))
    if receipt.get("status") != "BATCH_COMPLETE":
        raise SystemExit(f"R2 batch is not complete: {receipt.get('status')}")
    tasks = {row["shot_id"]: row for row in receipt.get("tasks", [])}
    replacements = {}
    for shot_id in ("E27-N08", "E27-N19"):
        task = tasks.get(shot_id)
        if not task or task.get("state") != "qa_pass":
            raise SystemExit(f"{shot_id} is not qa_pass")
        path = Path(task["output_path"])
        actual_sha = sha256(path)
        if actual_sha != task.get("sha256"):
            raise SystemExit(f"{shot_id} SHA drift: {actual_sha} != {task.get('sha256')}")
        replacements[shot_id] = {
            "path": path,
            "sha256": actual_sha,
            "task_id": task["task_id"],
            "credit_attempts": task.get("credit_attempts", []),
        }

    replaced = []
    for track_kind in ("videoTracks", "audioTracks"):
        for track in base["timeline"][track_kind]:
            for clip in track["clips"]:
                shot_id = clip["metadata"]["shot_id"]
                replacement = replacements.get(shot_id)
                if not replacement:
                    continue
                clip["source"] = str(replacement["path"])
                clip["metadata"]["source_sha256"] = replacement["sha256"]
                clip["metadata"]["source_variant"] = "V040_NATIVE_TEXT_R2"
                clip["metadata"]["source_admission"] = "PASS_OBJECTIVE_OCR_AND_CADENCE"
                clip["metadata"]["source_admission_confidence"] = 0.95
                clip["metadata"]["replacement_task_id"] = replacement["task_id"]
                clip["metadata"]["replacement_reason"] = "FULL_CUT_OCR_NATIVE_TEXT_FAILED_ONLY_R2"
                replaced.append(f"{track_kind}:{shot_id}")
    expected_replacements = {
        "videoTracks:E27-N08",
        "videoTracks:E27-N19",
        "audioTracks:E27-N08",
        "audioTracks:E27-N19",
    }
    if set(replaced) != expected_replacements:
        raise SystemExit(f"unexpected replacements: {replaced}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    base["output"]["path"] = str(OUTPUT)
    base["metadata"].update(
        {
            "status": "AGENTCUT_V15_NATIVE_TEXT_R2_NOT_FINAL_FULL_QA_PENDING",
            "base_project": str(BASE_PROJECT),
            "base_project_sha256": sha256(BASE_PROJECT),
            "native_text_r2_receipt": str(R2_RECEIPT),
            "native_text_r2_receipt_sha256": sha256(R2_RECEIPT),
            "replacement_shots": ["E27-N08", "E27-N19"],
            "preserved_shots": 22,
        }
    )
    PROJECT.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build = {
        "schema": "qingshan.agentcut_build_receipt.v1",
        "episode": "E27",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_VALIDATE_COMPILE_RENDER",
        "agentcut_runtime_required": "0.9.7",
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "output": str(OUTPUT),
        "replacement_shots": ["E27-N08", "E27-N19"],
        "replacement_sources": {
            shot_id: {
                "path": str(row["path"]),
                "sha256": row["sha256"],
                "task_id": row["task_id"],
                "credit_attempts": row["credit_attempts"],
            }
            for shot_id, row in replacements.items()
        },
        "preserved_shots": 22,
    }
    BUILD_RECEIPT.write_text(json.dumps(build, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
