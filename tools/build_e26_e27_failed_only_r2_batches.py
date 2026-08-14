#!/usr/bin/env python3
"""Build object-free, failed-only retry batches for E26 and E27."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_failed_only_retry(
    *,
    episode: str,
    source_config: str,
    source_receipt: str,
    retry_label: str,
    output_config: str,
    prompt_dir: str,
    output_dir: str,
    qa_dir: str,
    preserved_passes: list[str],
    exclude_keys: set[str] | None = None,
) -> Path:
    source = read_json(source_config)
    receipt = read_json(source_receipt)
    failed_keys = {
        task["task_key"]
        for task in receipt["tasks"]
        if task.get("status") == "qa_failed_terminal"
    }
    failed_keys.difference_update(exclude_keys or set())
    tasks = []
    for original in source["tasks"]:
        if original["task_key"] not in failed_keys:
            continue
        task = copy.deepcopy(original)
        old_key = task["task_key"]
        new_key = f"{old_key}-{retry_label}"
        task["task_key"] = new_key
        base_prompt = (ROOT / task["prompt_file"]).read_text(encoding="utf-8").rstrip()
        hard_repair = (
            "\n\n失败项专用硬修复：保留原剧本人物、地点、时段、天气、对白、事件顺序和镜头时长。"
            "画面中禁止出现任何可书写或可显示文字的正面载体：不要牌匾、告示、卷轴、纸页、账册内页、"
            "印章正面、门牌、布幡、屏幕、标签、表格、格线、字母、数字、汉字或伪文字。"
            "若剧情涉及令牌、文书、名单或证物，只能表现为折叠封闭、素面无标记的背面或布包侧边，"
            "并始终背向镜头；用人物动作、表情和对白传达信息。背景墙、门窗、器物和服饰均保持无纹字素面。"
            "不得新增角色、复制身体、改变场景或改写对白。"
        )
        prompt_path = ROOT / prompt_dir / f"{new_key}.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(base_prompt + hard_repair + "\n", encoding="utf-8")
        task["prompt_file"] = str(prompt_path.relative_to(ROOT))
        task.setdefault("metadata", {})["retry_reason"] = "PERSISTENT_OCR_TEXT_CONTAMINATION"
        task["metadata"]["rollback"] = (
            "Preserve all prior candidates and passed tasks; replace only this failed task after QA PASS."
        )
        tasks.append(task)

    out = ROOT / output_config
    write_json(
        out,
        {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": episode,
            "scene_contract_ref": source.get("scene_contract_ref"),
            "script_readiness_report": source.get("script_readiness_report"),
            "status": "READY_TO_SUBMIT_CONCURRENTLY",
            "parallel_submission": True,
            "concurrency": len(tasks),
            "max_retries": 0,
            "output_dir": output_dir,
            "qa_dir": qa_dir,
            "base_batch_note": (
                f"{retry_label} retries only OCR-failed tasks concurrently; every prior pass is preserved."
            ),
            "preserved_passes": preserved_passes,
            "tasks": tasks,
        },
    )
    return out


def main() -> int:
    outputs = [
        build_failed_only_retry(
            episode="E26",
            source_config="configs/E26_standard_storyboard_failed_only_r1_textsafe_20260719.json",
            source_receipt="workflow/tasks/E26_STANDARD_STORYBOARD_FAILED_ONLY_R1_TEXTSAFE_RECEIPT_20260719.json",
            retry_label="R2-OBJECT-FREE",
            output_config="configs/E26_standard_storyboard_failed_only_r2_object_free_20260719.json",
            prompt_dir="workflow/prompts/e26_standard_storyboard_failed_only_r2_object_free_20260719",
            output_dir="working_assets/e26_standard_storyboard_failed_only_r2_object_free_20260719/candidates",
            qa_dir="qa/e26_standard_storyboard_failed_only_r2_object_free_20260719",
            preserved_passes=["E26-B02-R2", "E26-B03-R1", "E26-B05-V1", "E26-B06-V1"],
            exclude_keys={"E26-B02-STANDARD-STORYBOARD-R1-TEXTSAFE"},
        ),
        build_failed_only_retry(
            episode="E27",
            source_config="configs/E27_standard_storyboard_v1_20260719.json",
            source_receipt="workflow/tasks/E27_STANDARD_STORYBOARD_V1_RECEIPT_20260719.json",
            retry_label="R1-OBJECT-FREE",
            output_config="configs/E27_standard_storyboard_failed_only_r1_object_free_20260719.json",
            prompt_dir="workflow/prompts/e27_standard_storyboard_failed_only_r1_object_free_20260719",
            output_dir="working_assets/e27_standard_storyboard_failed_only_r1_object_free_20260719/candidates",
            qa_dir="qa/e27_standard_storyboard_failed_only_r1_object_free_20260719",
            preserved_passes=[
                "E27-B01-P2-V1",
                "E27-B04-P1-V1",
                "E27-B04-P2-V1",
                "E27-B05-P1-V1",
                "E27-B06-P1-V1",
                "E27-B06-P2-V1",
            ],
        ),
    ]
    print(json.dumps({"status": "PASS", "outputs": [str(path) for path in outputs]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
