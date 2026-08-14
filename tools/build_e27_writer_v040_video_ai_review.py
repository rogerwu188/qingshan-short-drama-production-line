#!/usr/bin/env python3
"""Build the exact-SHA 24-video AI review request for E27 Writer Agent v0.4."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
MAIN_RECEIPT = ROOT / "workflow/tasks/E27_WRITER_AGENT_V040_VIDEO_BATCH_V1_RECEIPT_20260720.json"
RECOVERY_RECEIPT = ROOT / "workflow/tasks/E27_WRITER_AGENT_V040_VIDEO_BATCH_AUDIOFIX_R1_RECEIPT_20260720.json"
COMPILED = Path("/Users/rogerwu/Documents/Codex/2026-07-20/qingshan-professional-writer-agent/outputs/qingshan-writer-agent/examples/e27.agent-native.compiled.json")
OUT_DIR = ROOT / "qa/e27_writer_agent_v040_video_ai_review_20260720"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected_tasks() -> dict[str, dict]:
    selected = {}
    for task in load(MAIN_RECEIPT)["tasks"]:
        if task.get("state") in {"qa_pass", "qa_failed_terminal"} and task.get("output_path"):
            selected[task["shot_id"]] = task
    for task in load(RECOVERY_RECEIPT)["tasks"]:
        if task.get("state") in {"qa_pass", "qa_failed_terminal"} and task.get("output_path"):
            selected[task["shot_id"]] = task
    return selected


def main() -> int:
    selected = selected_tasks()
    if len(selected) != 24:
        raise SystemExit(f"expected 24 harvested candidates, got {len(selected)}: {sorted(selected)}")
    compiled = load(COMPILED)
    shots = {row["shot_id"]: row for row in compiled["shot_contracts"]}
    items = []
    selection = []
    for shot in sorted(shots.values(), key=lambda row: row["global_order"]):
        shot_id = shot["shot_id"]
        task = selected[shot_id]
        video_path = Path(task["output_path"])
        digest = sha256(video_path)
        if digest != task.get("sha256"):
            raise SystemExit(f"candidate SHA drift: {shot_id}")
        objective_status = "PASS" if task["state"] == "qa_pass" else "FAIL_REQUIRES_MACHINE_ADJUDICATION"
        selection.append({
            "shot_id": shot_id,
            "path": str(video_path),
            "sha256": digest,
            "task_id": task.get("task_id"),
            "objective_qa_status": objective_status,
            "objective_qa": task.get("qa"),
        })
        items.append({
            "path": str(video_path),
            "scope": "shot",
            "kind": "video",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": shot_id,
            "metadata": {
                "episode": "E27",
                "scene_id": shot["scene_id"],
                "candidate_sha256": digest,
                "source_script_sha256": sha256(COMPILED),
                "duration_seconds": shot["duration_seconds"],
                "objective_qa_status": objective_status,
                "review_focus": [
                    f"story action must remain exactly: {shot['action']}",
                    f"visual result must remain exactly: {shot['visual']}",
                    f"camera motion must serve the event as {shot['camera_motion']}, never generic push-in filler",
                    f"shot scale and geography must remain {shot['shot_scale']} in {shot['scene_id']}",
                    "canonical character identity, age, gender, costume and prop ownership must remain stable",
                    "Jiaotu must remain female, including her female spirit form with rabbit-ear silhouette motif",
                    "dialogue order, speaker identity, sentence completeness and lip synchronization",
                    "onsite sound must match contact and motion; no external background music",
                    "no readable or pseudo-readable generated text, subtitle, watermark or logo",
                    "no duplicated identity, extra limbs, body fusion, looping filler or time-stretched motion",
                ],
            },
            "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
            "run_regression_ci": True,
            "use_existing_tools": True,
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    request = OUT_DIR / "E27_WRITER_AGENT_V040_24_VIDEO_AI_REVIEW_REQUEST.json"
    selection_path = OUT_DIR / "E27_WRITER_AGENT_V040_24_VIDEO_SELECTION.json"
    request.write_text(json.dumps({"items": items, "workers": 4}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    selection_path.write_text(json.dumps({
        "schema": "qingshan.e27.writer_agent_v040.video_selection.v1",
        "episode": "E27",
        "status": "READY_24_EXACT_SHA_AI_REVIEW",
        "count": len(selection),
        "items": selection,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "count": len(items),
        "request": str(request),
        "request_sha256": sha256(request),
        "selection": str(selection_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
