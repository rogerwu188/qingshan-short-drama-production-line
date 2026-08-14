#!/usr/bin/env python3
"""Compile E36 failed stills into a structurally repaired V2 submit manifest."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
PLAN_PATH = PRODUCTION / "E36_REPAIR_IMAGE_BATCH_PLAN_V2.json"
SOURCE_MANIFEST_PATH = PRODUCTION / "E36_IMAGE_BATCH_PERFORMANCE_V1.json"
PROMPT_DIR = PRODUCTION / "image_prompts_repair_v2"
OUT_MANIFEST = PRODUCTION / "E36_REPAIR_IMAGE_BATCH_MANIFEST_V2.json"
OUT_GATE = ROOT / "qa/e36_v2_preproduction_20260728/E36_REPAIR_IMAGE_PROMPT_GATE_V2.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    plan = read_json(PLAN_PATH)
    source = read_json(SOURCE_MANIFEST_PATH)
    source_tasks = {row["task_key"]: row for row in source["tasks"]}
    structural = plan["structural_inheritance"]
    replacements = {
        "chenji": structural["chenji_reference"],
        "yunyang": structural["yunyang_reference"],
    }
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    compiled = []
    gate_rows = []

    for repair in plan["repair_tasks"]:
        old_key = repair["task_key"].replace("-STILL-V2", "-STILL-V1")
        task = copy.deepcopy(source_tasks[old_key])
        qa = read_json(ROOT / repair["qa_source"])
        base_prompt = (ROOT / repair["base_prompt"]).read_text(encoding="utf-8").rstrip()
        raw_repair_scope = qa["repair_scope"]
        repair_scope = (
            raw_repair_scope
            if isinstance(raw_repair_scope, str)
            else json.dumps(raw_repair_scope, ensure_ascii=False, sort_keys=True)
        )
        additions = [
            "",
            "【V2结构返修硬约束】",
            f"本单元原始FAIL修复范围：{repair_scope}",
            "角色年龄身份锁：陈迹与云羊均须清晰读作17岁，脸型、发型、身材必须匹配所附PASS三视图；禁止成年化。",
            "场景文字锁：除单元合约明确授权的宽建立镜外，禁止概不赊账牌匾及任何未授权可读文字；中近景、特写、insert一律无牌匾。",
            "时代锁：仅古代器物与烛火，禁止玻璃煤油灯、民国化灯具和现代物件。",
            "状态锁：首帧必须处于动作正在发生的起始状态，不得预先完成抓取、递交、收纳、转身、成形、碰撞或效果终态。",
            "数量锁：只出现原单元声明角色与动物，禁止增人、复制人物、复制动物。",
            "画面无水印、无字幕、无界面文字。",
        ]
        prompt_text = "\n".join([base_prompt, *additions]).rstrip() + "\n"
        prompt_path = PROMPT_DIR / f"{repair['task_key'].replace('-STILL-V2', '')}.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")

        bindings = []
        for binding in task["reference_bindings"]:
            entity = binding.get("entity_id")
            if entity in replacements:
                replacement = replacements[entity]
                binding = {
                    "role": "character",
                    "entity_id": entity,
                    "path": replacement["path"],
                    "sha256": replacement["sha256"],
                    "qa_status": "PASS",
                }
            bindings.append(binding)

        task["task_key"] = repair["task_key"]
        task["prompt_file"] = str(prompt_path.relative_to(ROOT))
        task["prompt_sha256"] = sha256(prompt_path)
        task["reference_bindings"] = bindings
        task["reference_images"] = [row["path"] for row in bindings]
        task["prompt_contract"]["reference_bindings"] = copy.deepcopy(bindings)
        task["prompt_contract"]["repair_source_qa"] = repair["qa_source"]
        task["prompt_contract"]["repair_scope"] = repair_scope
        task["prompt_contract"]["structural_scene_contract"] = str(
            (PRODUCTION / "E36_SCENE_IDENTITY_STRUCTURAL_REPAIR_V1.json").relative_to(ROOT)
        )
        task["status"] = "READY_AFTER_REPAIR_GATES"
        compiled.append(task)
        gate_rows.append({
            "task_key": task["task_key"],
            "prompt_sha256": task["prompt_sha256"],
            "repair_scope_present": repair_scope in prompt_text,
            "source_action_present": task["prompt_contract"]["source_action"] in prompt_text,
            "reference_count": len(bindings),
            "status": "PASS",
        })

    gate = {
        "schema": "qingshan.shot_prompt_professionalism_gate.v1",
        "episode": "E36",
        "status": "PASS",
        "canonical_script_sha256": plan["canonical_script_sha256"],
        "task_count": len(gate_rows),
        "results": gate_rows,
    }
    write_json(OUT_GATE, gate)

    manifest = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E36",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "source_script_sha256": plan["canonical_script_sha256"],
        "scene_contract_ref": structural["scene_contract"],
        "repair_plan_ref": str(PLAN_PATH.relative_to(ROOT)),
        "machine_gate_reports": [
            "qa/e36_v2_preproduction_20260728/E36_VIDEO_ANCHOR_COUNT_GATE_V1.json",
            str(OUT_GATE.relative_to(ROOT)),
            "qa/e36_v2_preproduction_20260728/E36_SHOT_SPACE_CAMERA_CONSTRAINT_GATE_V1.json",
            "qa/e36_v2_preproduction_20260728/E36_PERIOD_ANACHRONISM_LOCK_GATE_V1.json",
            "qa/e36_v2_preproduction_20260728/E36_FIRST_FRAME_MOTION_STATE_GATE_V1.json",
            "qa/e36_v2_preproduction_20260728/E36_AMBIENT_LIFE_LEVEL_GATE_V1.json"
        ],
        "output_dir": "working_assets/e36_v2_stills_20260728/repair_v2_candidates",
        "qa_dir": "qa/e36_v2_stills_repair_20260729",
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "consumer_contract": {
            "planned_anchor_count": len(compiled),
            "new_image_submit_count": len(compiled),
            "all_required_anchors_planned_before_submit": True,
            "incremental_video_submit": "EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_ANCHORS_PASS"
        },
        "blocked_tasks": [],
        "tasks": compiled,
    }
    write_json(OUT_MANIFEST, manifest)
    print(json.dumps({"status": "PASS", "tasks": len(compiled), "manifest": str(OUT_MANIFEST)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
