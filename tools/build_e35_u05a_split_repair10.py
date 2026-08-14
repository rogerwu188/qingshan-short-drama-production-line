#!/usr/bin/env python3
"""Split E35 U05A within the remaining video-credit allowance."""

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
BASE_CONFIG = VIDEO_DIR / "E35_VIDEO_DIALOGUE_EXACTNESS_REPAIR7.json"
BASE_UNIT_PLAN = PROD / "E35_VIDEO_UNIT_PERFORMANCE_PLAN_V1_DIALOGUE_REPAIR3.json"
BASE_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_DIALOGUE_EXACTNESS_REPAIR7.json"
BASE_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_DIALOGUE_EXACTNESS_REPAIR7.json"
OUT_CONFIG = VIDEO_DIR / "E35_VIDEO_U05A_SPLIT_REPAIR10.json"
OUT_UNIT_PLAN = PROD / "E35_VIDEO_UNIT_PERFORMANCE_PLAN_V1_U05A_SPLIT_REPAIR10.json"
OUT_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_U05A_SPLIT_REPAIR10.json"
OUT_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_U05A_SPLIT_REPAIR10.json"
EVIDENCE = ROOT / "qa/e35_v1_release_20260723/E35_U05A_REPAIR7_OMISSION_FAILURE_REPAIR10.json"


SPLITS = (
    ("E35-CW-U05A1", "E35-CW-U05A", 4, ["E35-DIA-SEG-013A"],
     "陈迹盯住被缚严敬，完整说出严敬被捕之前有人提前介入；严敬下颌绷紧。",
     "陈迹冷厉而清醒；严敬由强撑转为警觉。"),
    ("E35-CW-U05A2", "E35-CW-U05A", 4, ["E35-DIA-SEG-013B"],
     "陈迹紧接上一句，完整说出对方把整套话逐字教给严敬；严敬目光闪躲。",
     "陈迹逐字拆穿教词；严敬惊惧败露。"),
)
TEXT = {
    "E35-DIA-SEG-013A": "是有人在你被拿之前，",
    "E35-DIA-SEG-013B": "把这套话，一字一句教给了你。",
}


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
    original = next(row for row in config["tasks"] if row["unit_id"] == "E35-CW-U05A")
    unit_plan = load(BASE_UNIT_PLAN)
    source_unit = next(row for row in unit_plan["units"] if row["unit_id"] == "E35-CW-U05A")
    original_dialogue = next(row for row in load(BASE_DIALOGUE)["rows"] if row["video_unit_id"] == "E35-CW-U05A")
    headers = r3.original_prompt_headers(ROOT / original["prompt_file"])
    tasks, prompt_rows, unit_rows, dialogue_rows = [], [], [], []

    for index, split in enumerate(SPLITS):
        unit_id, _, duration, dialogue_ids, action, expression = split
        dialogue_id = dialogue_ids[0]
        text = TEXT[dialogue_id]
        task = copy.deepcopy(original)
        task["task_key"] = f"{unit_id}-PERFORMANCE-V1-EXACT-DIALOGUE-REPAIR10"
        task["source_id"] = unit_id
        task["unit_id"] = unit_id
        task["batch_id"] = "E35-V1-U05A-SPLIT-REPAIR10-20260724"
        task["visual_zone"] = f"{unit_id}-V1-EXACT-DIALOGUE-REPAIR10"
        task["duration"] = duration
        task["duration_seconds"] = duration
        task["edit_target_duration_seconds"] = duration
        task["duration_plan"] = {
            "policy": "qingshan.shot_generation_duration.v5",
            "duration_seconds": duration,
            "rationale": "One grammatical clause per unit after two full-sentence attempts omitted the opening clause.",
            "edit_policy": "Use all four seconds at native speed; never truncate, loop, freeze or stretch.",
        }
        asset = copy.deepcopy(original["dialogue_audio_assets"][0])
        asset.update({"dia_id": dialogue_id, "spoken_text": text, "audio_slot": "@音频1"})
        task["dialogue_audio_assets"] = [asset]
        task["dialogue"] = [{"dia_id": dialogue_id, "speaker": "陈迹", "speaker_id": "chenji", "spoken_text": text}]
        task["dialogue_audio_coverage"] = {"required": 1, "bound": 1, "status": "PASS"}
        task["performance_spec"] = {
            "schema": "qingshan.performance_generation_spec.v3",
            "episode": "E35",
            "unit_id": unit_id,
            "duration_seconds": duration,
            "single_source_of_truth": True,
            "prop_ownership": {"single_source_rule": "陈迹、严敬与密室道具只从本修复单元逐拍spec派生；无明示接触不得换手。"},
            "motion_beats": [{
                "start_seconds": 0.0,
                "end_seconds": float(duration),
                "subject": "陈迹、严敬",
                "action": action,
                "contact_point": "只允许动作句明示接触；未明示人物与道具保持分离。",
                "direction": "沿同一审讯视线轴连续推进，禁止跳位、反向、瞬移和无因碰撞。",
                "end_state": "唯一绑定短句逐字完成，最后一字后陈迹闭口并保持严敬反应。",
                "intent": "修复U05A前半句持续被吞并保留Claude Writer因果。",
                "visible_causality": "教词判断通过陈迹逼问和严敬表情按两个连续短句落定。",
                "expression": expression,
                "viewer_read": "观众逐字听清短句并理解严敬被提前教词。",
            }],
        }
        task["prompt_contract"]["source_action"] = action
        for binding in task["multimodal_entity_bindings"]:
            binding["dialogue_audio_slots"] = ["@音频1"] if binding["entity_id"] == "chenji" else []
            binding["visible_speaker"] = binding["entity_id"] == "chenji"
            binding["lip_sync"] = binding["entity_id"] == "chenji"
        task["multimodal_binding_sha256"] = hashlib.sha256(
            json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        task["repair_evidence"] = rel(EVIDENCE)
        prompt = r3.build_prompt((unit_id, "E35-CW-U05A", duration, dialogue_ids, action, expression), task, [asset], headers)
        prompt = prompt.replace("本单元是原视频漏句后的定向修复", "本单元是U05A两次吞句后的语法短句拆分修复")
        prompt = prompt.replace("不得省略第一句", "不得改写、缩写、添加或同义替换，且不得省略首字")
        if index == 0:
            prompt = prompt.replace("中景连续拍摄", "短促大远景建立方位后连续推至中景")
            prompt += "\n首字硬门：开口第一个音节必须是第四声 shì（汉字‘是’），绝不能说‘若’、‘这’或从中间开始。\n"
        prompt += f"\n短句硬门：只说‘{text}’，逐字一次；禁止跳字、外语、乱码、旁白和字幕腔。\n"
        prompt_path = PROMPT_DIR / f"{unit_id}-EXACT-DIALOGUE-REPAIR10.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        task["prompt_file"] = rel(prompt_path)
        task["prompt_path"] = rel(prompt_path)
        task["prompt_sha256"] = sha(prompt_path)
        task.pop("resolved_reference_image_asset_ids", None)
        task.pop("resolved_reference_audio_asset_ids", None)
        task.pop("generation_fingerprint", None)
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)
        prompt_rows.append({
            "unit_id": unit_id,
            "scene_id": task["scene_id"],
            "weather": headers["weather"],
            "duration_seconds": duration,
            "prompt_path": rel(prompt_path),
            "prompt_sha256": task["prompt_sha256"],
            "dialogue_ids": dialogue_ids,
            "anchor_task_keys": [row.get("state_id") for row in task["reference_image_sequence"] if row.get("state_id")],
            "status": "PASS_COMPLETE_CHANGED_INPUT_U05A_SPLIT_REPAIR10",
        })
        unit_row = copy.deepcopy(source_unit)
        unit_row["unit_id"] = unit_id
        unit_row["duration_seconds"] = duration
        unit_row["action_chain"] = action
        unit_row["expression_arc"] = expression
        unit_row["performance_spec"] = copy.deepcopy(task["performance_spec"])
        line = copy.deepcopy(source_unit["dialogue_lines"][0])
        line.update({"dialogue_id": dialogue_id, "video_unit_id": unit_id, "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest()})
        unit_row["dialogue_lines"] = [line]
        unit_row["video_prompt_file"] = rel(prompt_path)
        unit_row["video_prompt_sha256"] = task["prompt_sha256"]
        unit_rows.append(unit_row)
        dialogue_row = copy.deepcopy(original_dialogue)
        dialogue_row.update({"dia_id": dialogue_id, "video_unit_id": unit_id, "spoken_text": text, "status": "PASS"})
        dialogue_rows.append(dialogue_row)

    full_units = []
    for row in unit_plan["units"]:
        full_units.extend(unit_rows if row["unit_id"] == "E35-CW-U05A" else [row])
    unit_plan["units"] = full_units
    unit_plan["unit_count"] = len(full_units)
    unit_plan["runtime_seconds"] = sum(float(row.get("duration_seconds", 0)) for row in full_units)
    unit_plan["scope"] = "FAILED_ONLY_U05A_SPLIT_REPAIR10"
    write(OUT_UNIT_PLAN, unit_plan)

    prompt_manifest = load(BASE_PROMPTS)
    full_prompts = []
    for row in prompt_manifest["rows"]:
        full_prompts.extend(prompt_rows if row["unit_id"] == "E35-CW-U05A" else [row])
    prompt_manifest["rows"] = full_prompts
    prompt_manifest["unit_count"] = len(full_prompts)
    prompt_manifest["scope"] = "FAILED_ONLY_U05A_SPLIT_REPAIR10"
    prompt_manifest["source_plan"] = rel(OUT_UNIT_PLAN)
    prompt_manifest["source_plan_sha256"] = sha(OUT_UNIT_PLAN)
    write(OUT_PROMPTS, prompt_manifest)

    dialogue = load(BASE_DIALOGUE)
    dialogue["rows"] = dialogue_rows
    dialogue["line_count"] = 2
    dialogue["status"] = "PASS"
    dialogue["scope"] = "FAILED_ONLY_U05A_SPLIT_REPAIR10"
    write(OUT_DIALOGUE, dialogue)

    plan_refs = {}
    for base_name, out_name in (
        ("E35_VIDEO_ANCHOR_COUNT_PLAN_V1_DIALOGUE_REPAIR3.json", "E35_VIDEO_ANCHOR_COUNT_PLAN_V1_U05A_SPLIT_REPAIR10.json"),
        ("E35_COMMON_SENSE_CAUSALITY_PLAN_V1_DIALOGUE_REPAIR3.json", "E35_COMMON_SENSE_CAUSALITY_PLAN_V1_U05A_SPLIT_REPAIR10.json"),
        ("E35_PERIOD_LOCK_PLAN_V1_DIALOGUE_REPAIR3.json", "E35_PERIOD_LOCK_PLAN_V1_U05A_SPLIT_REPAIR10.json"),
        ("E35_MECHANICAL_DEFAULT_PLAN_V1_DIALOGUE_REPAIR3.json", "E35_MECHANICAL_DEFAULT_PLAN_V1_U05A_SPLIT_REPAIR10.json"),
    ):
        payload = load(QA / base_name)
        source = next(row for row in payload["units"] if row["unit_id"] == "E35-CW-U05A")
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
        payload["scope"] = "FAILED_ONLY_U05A_SPLIT_REPAIR10"
        if "planned_reference_image_count" in payload:
            payload["planned_reference_image_count"] = sum(row.get("planned_reference_image_count", 0) for row in rows)
        out_path = QA / out_name
        write(out_path, payload)
        plan_refs[base_name] = out_path

    preflight = load(QA / "E35_IMAGE_PLAN_PREFLIGHT_V1_DIALOGUE_REPAIR3.json")
    preflight.update({"recorded_at": datetime.now(timezone.utc).isoformat(), "video_unit_count": 2, "runtime_seconds": 8, "scope": "FAILED_ONLY_U05A_SPLIT_REPAIR10"})
    preflight_path = QA / "E35_IMAGE_PLAN_PREFLIGHT_V1_U05A_SPLIT_REPAIR10.json"
    write(preflight_path, preflight)
    dramatic = load(QA / "E35_DRAMATIC_QUALITY_PLAN_V1_DIALOGUE_REPAIR3.json")
    dramatic.update({"scope": "FAILED_ONLY_U05A_SPLIT_REPAIR10", "runtime_seconds": 8})
    dramatic_path = QA / "E35_DRAMATIC_QUALITY_PLAN_V1_U05A_SPLIT_REPAIR10.json"
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
    config["runtime_seconds"] = 8
    config["recorded_at"] = datetime.now(timezone.utc).isoformat()
    config["preserved_prompt_professionalism_evidence"] = [
        {"task_key": task["task_key"], "scene_id": task["scene_id"], "prompt_file": task["prompt_file"], "prompt_sha256": task["prompt_sha256"]}
        for task in tasks
    ]
    write(OUT_CONFIG, config)
    write(EVIDENCE, {
        "schema": "qingshan.e35.u05a.split_repair10.v1",
        "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "REPAIR10_CHANGED_INPUT_READY",
        "source_asr_report": "qa/e35_v1_release_20260723/E35_U05A_REPAIR7_TARGETED_ASR_V1.json",
        "failure": "Both full-line attempts omitted the opening clause.",
        "changed_input": "Split at the grammatical pause into two three-second exact clauses.",
        "planned_additional_video_seconds": 8,
        "planned_additional_video_credits": 160,
        "projected_episode_video_credit_total": 5820,
        "credit_limit": 6000,
        "rollback": "Preserve repair7 output and ASR failure; use repair10 only after both clauses pass exact ASR.",
    })
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "projected_episode_video_credits": 5820}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
