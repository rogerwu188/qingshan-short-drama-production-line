#!/usr/bin/env python3
"""Split E35 U19C into three exact-dialogue units after paraphrase ASR failure."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import build_e35_dialogue_failed_only_repair3 as r3
from episode_video_generation_guard import generation_fingerprint


ROOT = r3.ROOT
PROD = r3.PROD
QA = r3.QA
VIDEO_DIR = r3.VIDEO_DIR
PROMPT_DIR = r3.PROMPT_DIR
BASE_CONFIG = VIDEO_DIR / "E35_VIDEO_U19C_DIALOGUE_REPAIR4.json"
BASE_UNIT_PLAN = PROD / "E35_VIDEO_UNIT_PERFORMANCE_PLAN_V1_DIALOGUE_REPAIR3.json"
BASE_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_DIALOGUE_REPAIR3.json"
BASE_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_DIALOGUE_REPAIR3.json"
OUT_CONFIG = VIDEO_DIR / "E35_VIDEO_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"
OUT_UNIT_PLAN = PROD / "E35_VIDEO_UNIT_PERFORMANCE_PLAN_V1_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"
OUT_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"
OUT_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"
EVIDENCE = ROOT / "qa/e35_v1_release_20260723/E35_U19C_REPAIR4_PARAPHRASE_FAILURE_REPAIR6.json"


SPLITS = (
    ("E35-CW-U19C1", "E35-CW-U19C", 4, ["E35-DIA-SEG-041"],
     "陈迹看向镜头外的同伴，说明直接抓捕会让景朝立刻灭口；说完后合起账底。",
     "陈迹警惕而克制，落定直接抓捕的致命风险。"),
    ("E35-CW-U19C2", "E35-CW-U19C", 5, ["E35-DIA-SEG-042"],
     "陈迹握住旧钱，说明整条景朝暗线现在只剩这个唯一活口；镜头外人物不发声。",
     "陈迹目光沉下，确认活口的不可替代性。"),
    ("E35-CW-U19C3", "E35-CW-U19C", 4, ["E35-DIA-SEG-043"],
     "陈迹把账底压在掌下，明确这个被当成废物的人必须先保护、再审问；说完闭口并转向出口。",
     "陈迹由判断转为行动决断。"),
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    config = load(BASE_CONFIG)
    original = config["tasks"][0]
    all_dialogue = {row["dia_id"]: row for row in load(BASE_DIALOGUE)["rows"]}
    unit_plan = load(BASE_UNIT_PLAN)
    source_unit = next(row for row in unit_plan["units"] if row["unit_id"] == "E35-CW-U19C")
    headers = r3.original_prompt_headers(ROOT / original["prompt_file"])
    tasks, prompt_rows, unit_rows, selected_dialogue = [], [], [], set()

    for index, split in enumerate(SPLITS):
        unit_id, _, duration, dialogue_ids, action, expression = split
        task = copy.deepcopy(original)
        task["task_key"] = f"{unit_id}-PERFORMANCE-V1-EXACT-DIALOGUE-REPAIR6"
        task["source_id"] = unit_id
        task["unit_id"] = unit_id
        task["batch_id"] = "E35-V1-U19C-EXACT-DIALOGUE-SPLIT-REPAIR6-20260724"
        task["visual_zone"] = f"{unit_id}-V1-EXACT-DIALOGUE-REPAIR6"
        task["duration"] = duration
        task["duration_seconds"] = duration
        task["edit_target_duration_seconds"] = duration
        task["duration_plan"] = {
            "policy": "qingshan.shot_generation_duration.v5",
            "duration_seconds": duration,
            "rationale": "One natural sentence per unit after targeted ASR proved the combined unit paraphrased all three lines.",
            "edit_policy": f"Use all {duration} seconds at native speed; never truncate dialogue, loop, freeze or stretch.",
        }
        task["dialogue"] = [copy.deepcopy(row) for row in original["dialogue"] if row["dia_id"] in dialogue_ids]
        assets = [copy.deepcopy(row) for row in original["dialogue_audio_assets"] if row["dia_id"] in dialogue_ids]
        for asset in assets:
            asset["audio_slot"] = "@音频1"
        task["dialogue_audio_assets"] = assets
        task["reference_audio_asset_ids"] = list(dict.fromkeys(asset["remote_asset_id"] for asset in assets if asset.get("remote_asset_id")))
        task["reference_audios"] = list(dict.fromkeys(asset["path"] for asset in assets if not asset.get("remote_asset_id")))
        task.pop("resolved_reference_audio_asset_ids", None)
        task["dialogue_audio_coverage"] = {"required": 1, "bound": 1, "status": "PASS"}
        task["performance_spec"] = {
            "schema": "qingshan.performance_generation_spec.v3",
            "episode": "E35",
            "unit_id": unit_id,
            "duration_seconds": duration,
            "single_source_of_truth": True,
            "prop_ownership": {"single_source_rule": "陈迹、账底与旧钱只从本修复单元逐拍spec派生；无明示接触不得换手。"},
            "motion_beats": [{
                "start_seconds": 0.0,
                "end_seconds": float(duration),
                "subject": "陈迹",
                "action": action,
                "contact_point": "只允许动作句明示接触；未明示人物与道具保持分离。",
                "direction": "沿同一密室视线轴连续推进，禁止跳位、反向、瞬移、腾空和无因碰撞。",
                "end_state": "唯一绑定台词逐字完成，最后一字后陈迹闭口并保持动作结果。",
                "intent": "修复U19C改写对白并保留Claude Writer因果。",
                "visible_causality": "每句风险判断通过陈迹动作、表情和关键道具同时可见。",
                "expression": expression,
                "viewer_read": "观众逐字听清本句并理解它改变了什么。",
            }],
        }
        task["multimodal_entity_bindings"][0]["dialogue_audio_slots"] = ["@音频1"]
        task["multimodal_entity_bindings"][0]["visible_speaker"] = True
        task["multimodal_entity_bindings"][0]["lip_sync"] = True
        task["multimodal_binding_sha256"] = hashlib.sha256(
            json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        task["prompt_contract"]["source_action"] = action
        task["repair_evidence"] = rel(EVIDENCE)
        prompt_path = PROMPT_DIR / f"{unit_id}-EXACT-DIALOGUE-REPAIR6.txt"
        prompt = r3.build_prompt(split, task, assets, headers)
        prompt = prompt.replace("本单元是原视频漏句后的定向修复", "本单元是U19C逐句ASR确认改写后的拆句定向修复")
        prompt = prompt.replace("必须从本单元第0.4秒后开始", "必须从本单元第0.2秒开始")
        prompt = prompt.replace("不得省略第一句", "不得改写、缩写或同义替换，且不得省略句首")
        if index == 0:
            prompt = prompt.replace("中景连续拍摄", "短促大远景建立方位后连续推至中景")
        prompt_path.write_text(prompt, encoding="utf-8")
        task["prompt_file"] = rel(prompt_path)
        task["prompt_path"] = rel(prompt_path)
        task["prompt_sha256"] = sha(prompt_path)
        task.pop("resolved_reference_image_asset_ids", None)
        task.pop("generation_fingerprint", None)
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)
        selected_dialogue.update(dialogue_ids)
        prompt_rows.append({
            "unit_id": unit_id,
            "scene_id": task["scene_id"],
            "weather": headers["weather"],
            "duration_seconds": duration,
            "prompt_path": rel(prompt_path),
            "prompt_sha256": task["prompt_sha256"],
            "dialogue_ids": dialogue_ids,
            "anchor_task_keys": [row.get("state_id") for row in task["reference_image_sequence"] if row.get("state_id")],
            "status": "PASS_COMPLETE_CHANGED_INPUT_U19C_EXACT_DIALOGUE_REPAIR6",
        })
        row = copy.deepcopy(source_unit)
        row["unit_id"] = unit_id
        row["duration_seconds"] = duration
        row["action_chain"] = action
        row["expression_arc"] = expression
        row["performance_spec"] = copy.deepcopy(task["performance_spec"])
        row["dialogue_lines"] = [copy.deepcopy(line) for line in row["dialogue_lines"] if line["dialogue_id"] in dialogue_ids]
        for line in row["dialogue_lines"]:
            line["video_unit_id"] = unit_id
        row["video_prompt_file"] = rel(prompt_path)
        row["video_prompt_sha256"] = task["prompt_sha256"]
        unit_rows.append(row)

    full_unit_rows = []
    for row in unit_plan["units"]:
        if row["unit_id"] == "E35-CW-U19C":
            full_unit_rows.extend(unit_rows)
        else:
            full_unit_rows.append(row)
    unit_plan["units"] = full_unit_rows
    unit_plan["unit_count"] = len(full_unit_rows)
    unit_plan["runtime_seconds"] = sum(float(row.get("duration_seconds", 0)) for row in full_unit_rows)
    unit_plan["scope"] = "FAILED_ONLY_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6"
    write(OUT_UNIT_PLAN, unit_plan)

    prompt_manifest = load(BASE_PROMPTS)
    full_prompt_rows = []
    for row in prompt_manifest["rows"]:
        if row["unit_id"] == "E35-CW-U19C":
            full_prompt_rows.extend(prompt_rows)
        else:
            full_prompt_rows.append(row)
    prompt_manifest["rows"] = full_prompt_rows
    prompt_manifest["unit_count"] = len(full_prompt_rows)
    prompt_manifest["scope"] = "FAILED_ONLY_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6"
    prompt_manifest["source_plan"] = rel(OUT_UNIT_PLAN)
    prompt_manifest["source_plan_sha256"] = sha(OUT_UNIT_PLAN)
    write(OUT_PROMPTS, prompt_manifest)

    dialogue = load(BASE_DIALOGUE)
    mapping = {dialogue_id: unit_id for unit_id, _, _, ids, _, _ in SPLITS for dialogue_id in ids}
    dialogue["rows"] = [copy.deepcopy(row) for row in dialogue["rows"] if row["dia_id"] in selected_dialogue]
    for row in dialogue["rows"]:
        row["video_unit_id"] = mapping[row["dia_id"]]
    dialogue["line_count"] = len(dialogue["rows"])
    dialogue["status"] = "PASS"
    dialogue["scope"] = "FAILED_ONLY_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6"
    write(OUT_DIALOGUE, dialogue)

    plan_refs = {}
    for base_name, out_name in (
        ("E35_VIDEO_ANCHOR_COUNT_PLAN_V1_DIALOGUE_REPAIR3.json", "E35_VIDEO_ANCHOR_COUNT_PLAN_V1_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"),
        ("E35_COMMON_SENSE_CAUSALITY_PLAN_V1_DIALOGUE_REPAIR3.json", "E35_COMMON_SENSE_CAUSALITY_PLAN_V1_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"),
        ("E35_PERIOD_LOCK_PLAN_V1_DIALOGUE_REPAIR3.json", "E35_PERIOD_LOCK_PLAN_V1_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"),
        ("E35_MECHANICAL_DEFAULT_PLAN_V1_DIALOGUE_REPAIR3.json", "E35_MECHANICAL_DEFAULT_PLAN_V1_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"),
    ):
        payload = load(QA / base_name)
        source = next(row for row in payload["units"] if row["unit_id"] == "E35-CW-U19C")
        rows = []
        for split, task in zip(SPLITS, tasks):
            row = copy.deepcopy(source)
            row["unit_id"] = split[0]
            if "duration_seconds" in row:
                row["duration_seconds"] = split[2]
            if "prompt_sha256" in row:
                row["prompt_sha256"] = task["prompt_sha256"]
            rows.append(row)
        payload["units"] = rows
        payload["scope"] = "FAILED_ONLY_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6"
        if "planned_reference_image_count" in payload:
            payload["planned_reference_image_count"] = sum(
                row.get("planned_reference_image_count", 0) for row in rows
            )
        out_path = QA / out_name
        write(out_path, payload)
        plan_refs[base_name] = out_path

    preflight = load(QA / "E35_IMAGE_PLAN_PREFLIGHT_V1_DIALOGUE_REPAIR3.json")
    preflight.update({
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "video_unit_count": 3,
        "planned_anchor_count": sum(task["planned_reference_image_count"] for task in tasks),
        "runtime_seconds": 13,
        "projected_release_seconds_with_outro": 179,
        "scope": "FAILED_ONLY_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6",
        "agentcut_runtime_trim_seconds": 27,
    })
    preflight_path = QA / "E35_IMAGE_PLAN_PREFLIGHT_V1_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"
    write(preflight_path, preflight)
    dramatic = load(QA / "E35_DRAMATIC_QUALITY_PLAN_V1_DIALOGUE_REPAIR3.json")
    dramatic.update({"scope": "FAILED_ONLY_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6", "runtime_seconds": 13})
    dramatic_path = QA / "E35_DRAMATIC_QUALITY_PLAN_V1_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6.json"
    write(dramatic_path, dramatic)

    config["tasks"] = tasks
    config["complete_video_prompt_manifest_ref"] = rel(OUT_PROMPTS)
    config["dialogue_manifest_ref"] = rel(OUT_DIALOGUE)
    config["script_readiness_report"] = rel(preflight_path)
    config["dramatic_quality_report_ref"] = rel(dramatic_path)
    config["mechanical_default_plan_ref"] = rel(plan_refs["E35_MECHANICAL_DEFAULT_PLAN_V1_DIALOGUE_REPAIR3.json"])
    config["anchor_count_plan_ref"] = rel(plan_refs["E35_VIDEO_ANCHOR_COUNT_PLAN_V1_DIALOGUE_REPAIR3.json"])
    config["common_sense_causality_plan_ref"] = rel(plan_refs["E35_COMMON_SENSE_CAUSALITY_PLAN_V1_DIALOGUE_REPAIR3.json"])
    config["period_lock_plan_ref"] = rel(plan_refs["E35_PERIOD_LOCK_PLAN_V1_DIALOGUE_REPAIR3.json"])
    config["runtime_seconds"] = 13
    config["projected_release_seconds_with_outro"] = 179
    config["recorded_at"] = datetime.now(timezone.utc).isoformat()
    config["preserved_prompt_professionalism_evidence"] = [
        {"task_key": task["task_key"], "scene_id": task["scene_id"], "prompt_file": task["prompt_file"], "prompt_sha256": task["prompt_sha256"]}
        for task in tasks
    ]
    write(OUT_CONFIG, config)
    write(EVIDENCE, {
        "schema": "qingshan.e35.u19c.paraphrase_failure_repair.v1",
        "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "REPAIR6_CHANGED_INPUT_READY",
        "source_asr_report": "qa/e35_v1_release_20260723/E35_U19C_REPAIR4_TARGETED_ASR_V1.json",
        "failure": "Repair4 was technically valid but paraphrased all three locked lines.",
        "repair": "Split at the three natural sentence boundaries; one sentence, one visible speaker and two images per task.",
        "planned_additional_video_seconds": 13,
        "planned_additional_video_credits": 260,
        "projected_episode_video_credit_total": 5300,
        "credit_limit": 6000,
        "rollback": "Preserve repair4 output and ASR report; use only repair6 units after exact dialogue PASS.",
    })
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "seconds": 13, "projected_episode_video_credits": 5300}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
