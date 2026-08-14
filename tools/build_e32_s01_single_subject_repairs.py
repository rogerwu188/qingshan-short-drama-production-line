#!/usr/bin/env python3
"""Build changed-input E32 S01 still repairs from single-subject identity crops."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722"
SOURCE = PROD / "E32_IMAGE_BATCH_PERFORMANCE_A1_V1.json"
OUT = PROD / "E32_IMAGE_BATCH_S01_SINGLE_SUBJECT_REPAIR_R2.json"
PROMPTS = PROD / "image_prompts_performance_r2"
CHENJI = ROOT / "working_assets/e32_reference_single_subject_20260723/chenji_front_single.jpg"
JIAOTU = ROOT / "working_assets/e32_reference_single_subject_20260723/jiaotu_front_single.jpg"
UNITS = {"U01", "U02", "U03", "U04"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    source = json.loads(SOURCE.read_text())
    PROMPTS.mkdir(parents=True, exist_ok=True)
    crops = {"chenji": CHENJI, "jiaotu": JIAOTU}
    tasks = []
    for original in source["tasks"]:
        short = original["task_key"].split("-")[2]
        if short not in UNITS:
            continue
        task = copy.deepcopy(original)
        task["task_key"] = original["task_key"].replace("-V1", "-R2-SINGLE-SUBJECT")
        task["shot_id"] = f"E32-CW-{short}-A1-R2"
        task["beat_id"] = f"E32-CW-{short}-R2"
        task["status"] = "READY_FOR_PARALLEL_SUBMIT"
        new_bindings = []
        for binding in task["reference_bindings"]:
            binding = dict(binding)
            crop = crops.get(binding["entity_id"])
            if crop:
                binding.update({
                    "path": rel(crop), "sha256": sha(crop),
                    "qa_status": "PASS",
                    "qa_report": "workflow/tasks/E32_S01_SINGLE_SUBJECT_REFERENCE_REPAIR_R2.json",
                })
            new_bindings.append(binding)
        task["reference_bindings"] = new_bindings
        task["reference_images"] = [row["path"] for row in new_bindings]
        contract = task["prompt_contract"]
        contract["shot_id"] = task["shot_id"]
        contract["reference_bindings"] = copy.deepcopy(new_bindings)
        strict = (
            "定向修复：人物参考已从多视图拼版改为单人物裁切。画面只允许陈迹与皎兔两名生命主体，"
            "不得把参考图的不同视角解释成额外人物，不得出现第三人、路人、侍从、倒影人或背景人脸。"
        )
        if short == "U04":
            strict += " 本图是阴神分离之前的 A1：只画一具皎兔肉身，不得提前出现阴神、分身、透明人影或第二个皎兔。"
        contract["source_action"] = contract["source_action"] + "；" + strict
        contract["source_action_sha256"] = hashlib.sha256(contract["source_action"].encode()).hexdigest()
        original_prompt = ROOT / original["prompt_file"]
        prompt = (
            original_prompt.read_text()
            + "\n【R2 changed-input identity repair】\n"
            + strict
            + "\n源动作 R2（必须逐字绑定）："
            + contract["source_action"]
            + "\n"
        )
        prompt_path = PROMPTS / f"E32-CW-{short}-A1-R2.txt"
        prompt_path.write_text(prompt)
        task["prompt_file"] = rel(prompt_path)
        task["prompt_sha256"] = sha(prompt_path)
        tasks.append(task)
    payload = {k: copy.deepcopy(v) for k, v in source.items() if k != "tasks"}
    payload.update({
        "status": "READY_CHANGED_INPUT_REPAIR",
        "output_dir": "working_assets/e32_performance_stills_20260722/repairs_s01_r2",
        "qa_dir": "qa/e32_performance_stills_20260722/repairs_s01_r2",
        "repair_reason": "Original multi-view identity cards were interpreted as extra people; R2 uses single-subject crops and exact subject-count constraints.",
        "blocked_tasks": [], "tasks": tasks,
    })
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    receipt = ROOT / "workflow/tasks/E32_S01_SINGLE_SUBJECT_REFERENCE_REPAIR_R2.json"
    receipt.write_text(json.dumps({
        "schema": "qingshan.reference_repair_receipt.v1", "episode": "E32",
        "status": "READY_CHANGED_INPUT", "source_manifest": rel(SOURCE),
        "repair_manifest": rel(OUT), "single_subject_references": [
            {"entity_id": "chenji", "path": rel(CHENJI), "sha256": sha(CHENJI)},
            {"entity_id": "jiaotu", "path": rel(JIAOTU), "sha256": sha(JIAOTU)},
        ], "changed_units": sorted(UNITS), "prior_failures_preserved": True,
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"manifest": rel(OUT), "tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
