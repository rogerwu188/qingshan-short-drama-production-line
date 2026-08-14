#!/usr/bin/env python3
"""Build E26 B02 object-free retry and E27 six-image review batches."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_e26_b02() -> Path:
    source = json.loads((ROOT / "configs/E26_standard_storyboard_rework_v1_20260719.json").read_text(encoding="utf-8"))
    task = next(json.loads(json.dumps(row, ensure_ascii=False)) for row in source["tasks"] if row["source_id"] == "B02")
    task["task_key"] = "E26-B02-STANDARD-STORYBOARD-R2-OBJECT-FREE"
    prompt_path = ROOT / "workflow/prompts/e26_standard_storyboard_b02_r2_object_free_20260719/E26-B02-STANDARD-STORYBOARD-R2-OBJECT-FREE.txt"
    base = (ROOT / task["prompt_file"]).read_text(encoding="utf-8").rstrip()
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(base + (
        "\n\nR2硬修复：任何时刻都不展示纸页、账册内页、表格、格线、名单、封皮正面、牌匾或文字载体。"
        "陈迹只从火中抢出一个完全闭合、烧黑、素面、无标记的布包册，镜头始终只见焦黑侧边和素面背面；"
        "不得翻开，不得让书脊或表面朝向镜头。对白与剧情结论保持不变，用人物动作和反应表达，"
        "绝不生成可读文字、伪文字、笔画、字母、数字或规则网格。"
    ) + "\n", encoding="utf-8")
    task["prompt_file"] = str(prompt_path.relative_to(ROOT))
    task["metadata"]["retry_reason"] = "PERSISTENT_VISIBLE_WRITING_ON_BURNED_LEDGER"
    task["metadata"]["rollback"] = "Preserve the original B02 and R1 candidates as failed evidence; do not alter B05-B06 passes."
    out = ROOT / "configs/E26_b02_standard_storyboard_r2_object_free_20260719.json"
    write_json(out, {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E26",
        "scene_contract_ref": source["scene_contract_ref"],
        "script_readiness_report": source["script_readiness_report"],
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "parallel_submission": True,
        "concurrency": 1,
        "max_retries": 0,
        "output_dir": "working_assets/e26_b02_standard_storyboard_r2_object_free_20260719/candidates",
        "qa_dir": "qa/e26_b02_standard_storyboard_r2_object_free_20260719",
        "base_batch_note": "R2 repairs only the still-failed B02 visible writing; preserve every other E26 result.",
        "tasks": [task],
    })
    return out


def build_e27_review() -> Path:
    receipt = json.loads((ROOT / "workflow/tasks/E27_V1_SIX_IMAGES_RECEIPT_20260719.json").read_text(encoding="utf-8"))
    qa_dir = ROOT / "qa/e27_v1_six_images_ai_review_20260719"
    items = []
    for task in receipt["tasks"]:
        path = Path(task["output_path"])
        beat = task["beat_id"]
        items.append({
            "path": str(path),
            "scope": "shot",
            "kind": "image",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": f"E27-{beat}-KEYFRAME",
            "metadata": {
                "episode": "E27",
                "beat_id": beat,
                "candidate_sha256": sha(path),
                "review_focus": [
                    "single continuous frame, not collage",
                    "canonical identity continuity",
                    "script-locked location, time and weather",
                    "clear story action",
                    "no readable or pseudo-readable text",
                    "no extra people or duplicated bodies"
                ]
            },
            "required_capabilities": ["image_analysis", "ocr"],
            "run_regression_ci": True,
            "use_existing_tools": True,
        })
    request = qa_dir / "E27_SIX_IMAGE_AI_REVIEW_REQUEST.json"
    write_json(request, {"items": items})
    out = ROOT / "configs/E27_v1_six_images_ai_review_batch_20260719.json"
    write_json(out, {
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E27",
        "scene_contract_ref": "configs/e27_scene_state_v1_script_locked_20260719.json",
        "script_readiness_report": "qa/e27_preproduction_20260719/E27_SCRIPT_READINESS_GATE_V3.json",
        "qa_dir": str(qa_dir.relative_to(ROOT)),
        "output_dir": str(qa_dir.relative_to(ROOT)),
        "max_retries": 0,
        "base_batch_note": "Review all six E27 script-locked keyframes in one batch before 36-way video fan-out.",
        "tasks": [{
            "task_key": "E27-V1-SIX-IMAGE-AI-REVIEW",
            "tool_type": "ai_review",
            "scene_id": "E27-S01-TAIPING-CLINIC-FALSE-WARRANT",
            "visual_zone": "SIX_IMAGE_SOURCE_GATE",
            "prompt_file": "workflow/prompts/e27_parallel_v3_readiness_pass_20260719/images/B01.txt",
            "video": str(Path(items[0]["path"]).relative_to(ROOT)),
            "command": [".ai_review_env/bin/qingshan-review", "review-many", str(request.relative_to(ROOT))],
            "report": str((qa_dir / "E27_SIX_IMAGE_AI_REVIEW_WRAPPER.json").relative_to(ROOT)),
        }],
    })
    return out


def main() -> int:
    outputs = [build_e26_b02(), build_e27_review()]
    print(json.dumps({"status": "PASS", "outputs": [str(path) for path in outputs]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
