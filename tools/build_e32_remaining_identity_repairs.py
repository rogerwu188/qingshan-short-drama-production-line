#!/usr/bin/env python3
"""Build changed-input identity/subject-count repairs for remaining E32 anchors."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722"
SOURCE = PROD / "E32_IMAGE_BATCH_PERFORMANCE_A1_V1.json"
OUT = PROD / "E32_IMAGE_BATCH_REMAINING_IDENTITY_REPAIR_R3.json"
PROMPTS = PROD / "image_prompts_performance_r3"
REFS = {
    "chenji": ROOT / "working_assets/e32_reference_single_subject_20260723/chenji_front_single.jpg",
    "jiaotu": ROOT / "working_assets/e32_reference_single_subject_20260723/jiaotu_front_single.jpg",
    "yunyang": ROOT / "working_assets/e32_reference_single_subject_20260723/yunyang_front_single.jpg",
    "yao_taiyi": ROOT / "working_assets/e32_reference_single_subject_20260723/yao_taiyi_front_single.jpg",
}
UNITS = {"U08", "U10", "U11", "U14", "U15"}
STRICT = {
    "U08": "画面严格只有陈迹、齐三、巡检司杀手三个人类和乌云一只纯黑猫；不得增加第四个人类、第二名杀手、路人、倒影人或背景人脸。",
    "U10": "A1严格只有陈迹、云羊、齐三、巡检司杀手四个人类；不得增加第五个人、复制角色、路人、倒影人或背景人脸。此图只承担动作起始空间，半枚铜牌仍在杀手袖口，不得提前到陈迹手中。",
    "U11": "画面严格只有陈迹、姚太医两个人类，另有一只通体漆黑的大乌鸦落在案头；不得出现第三个人类、黑猫、侍从、倒影人或背景人脸。",
    "U14": "画面严格只有陈迹、姚太医两个人类和一只通体漆黑的大乌鸦；乌云当前是剧本声明的通灵乌鸦形态，不画成猫；不得出现第三个人类、第二只鸟、路人或背景人脸。",
    "U15": "画面严格只有陈迹和人形皎兔两个人类；皎兔是黑衣年轻女性，不是兔子、兽人、兔耳人或动物；不得出现第三个人类、路人、倒影人或背景人脸。",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    source = json.loads(SOURCE.read_text())
    PROMPTS.mkdir(parents=True, exist_ok=True)
    tasks = []
    for original in source["tasks"]:
        short = original["task_key"].split("-")[2]
        if short not in UNITS:
            continue
        task = copy.deepcopy(original)
        task["task_key"] = original["task_key"].replace("-V1", "-R3-IDENTITY")
        task["shot_id"] = f"E32-CW-{short}-A1-R3"
        task["beat_id"] = f"E32-CW-{short}-R3"
        task["status"] = "READY_FOR_PARALLEL_SUBMIT"
        bindings = []
        for binding in task["reference_bindings"]:
            binding = dict(binding)
            entity = binding["entity_id"]
            if short == "U14" and entity == "wuyun":
                continue
            crop = REFS.get(entity)
            if crop:
                binding.update({
                    "path": rel(crop), "sha256": sha(crop), "qa_status": "PASS",
                    "qa_report": "workflow/tasks/E32_REMAINING_SINGLE_SUBJECT_REFERENCE_REPAIR_R3.json",
                })
            bindings.append(binding)
        task["reference_bindings"] = bindings
        task["reference_images"] = [row["path"] for row in bindings]
        contract = task["prompt_contract"]
        contract["shot_id"] = task["shot_id"]
        contract["reference_bindings"] = copy.deepcopy(bindings)
        contract["visible_characters"] = [row["entity_id"] for row in bindings if row["role"] == "character"]
        contract["source_action"] = contract["source_action"] + "；定向修复：" + STRICT[short]
        contract["source_action_sha256"] = hashlib.sha256(contract["source_action"].encode()).hexdigest()
        prompt = (
            (ROOT / original["prompt_file"]).read_text()
            + "\n【R3 changed-input identity and subject-count repair】\n"
            + STRICT[short]
            + "\n身份参考只锁同名的一个主体，不得把参考图当作新增人物。"
            + "\n源动作 R3（必须逐字绑定）：" + contract["source_action"] + "\n"
        )
        prompt_path = PROMPTS / f"E32-CW-{short}-A1-R3-IDENTITY.txt"
        prompt_path.write_text(prompt)
        task["prompt_file"] = rel(prompt_path)
        task["prompt_sha256"] = sha(prompt_path)
        tasks.append(task)
    payload = {key: copy.deepcopy(value) for key, value in source.items() if key != "tasks"}
    payload.update({
        "status": "READY_CHANGED_INPUT_REPAIR",
        "output_dir": "working_assets/e32_performance_stills_20260722/repairs_remaining_r3",
        "qa_dir": "qa/e32_performance_stills_20260722/repairs_remaining_r3",
        "repair_reason": "Replace multi-view/subtitled identity cards with single-subject crops and enforce exact human/creature counts.",
        "tasks": tasks,
    })
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    receipt = ROOT / "workflow/tasks/E32_REMAINING_SINGLE_SUBJECT_REFERENCE_REPAIR_R3.json"
    receipt.write_text(json.dumps({
        "schema": "qingshan.reference_repair_receipt.v1", "episode": "E32",
        "status": "READY_CHANGED_INPUT", "source_manifest": rel(SOURCE), "repair_manifest": rel(OUT),
        "single_subject_references": [
            {"entity_id": entity, "path": rel(path), "sha256": sha(path)} for entity, path in REFS.items()
        ],
        "changed_units": sorted(UNITS), "prior_failures_preserved": True,
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"manifest": rel(OUT), "tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
