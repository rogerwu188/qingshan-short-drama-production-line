#!/usr/bin/env python3
"""Build one six-item AI review batch for E27 professional-script keyframes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "workflow/tasks/E27_PRO_SCRIPT_KEYFRAME_IMAGE_BATCH_V1_RECEIPT_20260720.json"
SCENE_STATE = ROOT / "configs/e27_pro_script_scene_state_v1_20260720.json"
QA_DIR = ROOT / "qa/e27_pro_script_keyframes_v1_ai_review_20260720"
REQUEST = QA_DIR / "E27_PRO_SCRIPT_KEYFRAME_AI_REVIEW_REQUEST.json"
CONFIG = ROOT / "configs/E27_pro_script_keyframe_ai_review_batch_v1_20260720.json"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    receipt = read(RECEIPT)
    scene_rows = read(SCENE_STATE)["scene_state"]
    scenes = {row["scene_id"]: row for row in scene_rows}
    tasks = receipt.get("tasks") or []
    if receipt.get("status") != "BATCH_COMPLETE" or len(tasks) != 6:
        raise SystemExit("E27 professional keyframe batch is not complete with six tasks")

    items = []
    for task in tasks:
        if task.get("state") != "image_pass":
            raise SystemExit(f"keyframe not passed: {task.get('task_key')}")
        path = Path(task["output_path"])
        scene = scenes[task["scene_id"]]
        digest = sha256(path)
        if digest != task.get("sha256"):
            raise SystemExit(f"SHA mismatch: {task.get('task_key')}")
        items.append({
            "path": str(path),
            "scope": "shot",
            "kind": "image",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": task["task_key"],
            "metadata": {
                "episode": "E27",
                "scene_id": task["scene_id"],
                "scene_no": task["scene_no"],
                "candidate_sha256": digest,
                "source_script_sha256": receipt.get("source_script_sha256") or "6a3825ebc84e38534ae4f59a4dcdf6b308fe9aec7e2bf8a8cbc69c9a267adfa6",
                "review_focus": [
                    f"location must read as {scene['location']}",
                    f"time of day must read as {scene['time_of_day']}",
                    f"weather/environment must read as {scene['weather']}",
                    f"story action must clearly depict: {scene['event_summary']}",
                    "canonical character identity and wardrobe continuity",
                    "single continuous frame with readable physical action",
                    "no readable or pseudo-readable text, watermark, logo, duplicated identity, fused limbs or extra people",
                ],
            },
            "required_capabilities": ["image_analysis", "ocr"],
            "run_regression_ci": True,
            "use_existing_tools": True,
        })

    write(REQUEST, {"items": items, "workers": 6})
    write(CONFIG, {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E27",
        "scene_contract_ref": str(SCENE_STATE.relative_to(ROOT)),
        "status": "READY_TO_SUBMIT_AI_REVIEW_BATCH",
        "parallel_submission": True,
        "concurrency": 1,
        "max_retries": 0,
        "qa_dir": str(QA_DIR.relative_to(ROOT)),
        "output_dir": str(QA_DIR.relative_to(ROOT)),
        "base_batch_note": "Review all six professional-script keyframes in one six-worker batch; preserve passes and retry failed scenes only.",
        "tasks": [{
            "task_key": "E27-PRO-SCRIPT-KEYFRAMES-V1-AI-REVIEW",
            "tool_type": "ai_review",
            "scene_id": tasks[0]["scene_id"],
            "visual_zone": "SIX_PRO_SCRIPT_KEYFRAME_REVIEW",
            "prompt_file": tasks[0]["prompt_file"],
            "video": str(Path(tasks[0]["output_path"]).relative_to(ROOT)),
            "command": [
                ".ai_review_env/bin/qingshan-review",
                "review-many",
                str(REQUEST.relative_to(ROOT)),
            ],
            "report": str((QA_DIR / "E27_PRO_SCRIPT_KEYFRAME_AI_REVIEW_WRAPPER.json").relative_to(ROOT)),
        }],
    })
    return {"status": "PASS", "item_count": len(items), "request": str(REQUEST), "config": str(CONFIG)}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
