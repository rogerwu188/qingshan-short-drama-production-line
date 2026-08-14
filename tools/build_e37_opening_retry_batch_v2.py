#!/usr/bin/env python3
"""Build a failed-only, materially changed retry for E37 opening O02-O04."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from multimodal_character_binding_guard import binding_digest


ROOT = Path(__file__).resolve().parents[1]
BASE = Path("workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/opening_replacement_v1")
OUT = Path("workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/opening_replacement_v2")
PROMPTS = Path("working_assets/e37_opening_replacement_v2_20260803/compiled_prompts")


def sha(path: str | Path) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    config = json.loads((ROOT / BASE / "E37_OPENING_REPLACEMENT_BATCH_V1.json").read_text(encoding="utf-8"))
    tasks = {row["unit_id"]: deepcopy(row) for row in config["tasks"]}
    changes = {
        "E37-R-O02": {
            "anchor": "working_assets/e37_opening_replacement_v2_20260803/anchors/E37_R_O02_LOCKED_PROFILE_ANCHOR_V2.png",
            "motion": "陈迹食指沿唯一账目由右向左缓慢划过，左手把松动封皮合拢一寸；说到每月时下颌抬起，说到看守银时目光转向画外同伴",
            "result": "银字落下后闭口，食指离页并停在胸前，目光已抬起，保持自然呼吸0.45秒",
            "contract": "left-profile anchor replaces the table-wide composition; hand trace, cover movement and gaze lift create three non-repeating internal changes"
        },
        "E37-R-O03": {
            "anchor": "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U03-A2-STILL-V2_ZERO_CREDIT_ALT.png",
            "motion": "皎兔阴神从后景门洞快速归入眉心，皎兔立刻向陈迹迈近一步；第一句时右手指向里屋，第二句时收手按住腰侧并锁住陈迹视线，陈迹只在句间转头",
            "result": "来了二字完整落下后闭口，皎兔停在前一步的新位置，陈迹已转头看她，保持自然呼吸0.45秒",
            "contract": "return, one forward step, doorway point, hand withdrawal and Chenji head turn replace the static two-person hold"
        },
        "E37-R-O04": {
            "anchor": "working_assets/e37_opening_replacement_v2_20260803/anchors/E37_R_O04_LOCKED_REACTION_ANCHOR_V2.png",
            "motion": "陈迹先吸气停顿，眼神从画面下方账页抬到正前方；右手从画面底部缓慢收回胸前并握紧，冷白呼气在最后半句清楚散开",
            "result": "过字落下后闭口，拳已握紧、指节发白，冷雾散尽，极远怔然保持0.45秒",
            "contract": "frontal identity anchor removes the repeated table composition; gaze lift, hand withdrawal, fist closure and breath plume carry the reaction"
        },
    }
    retry_tasks = []
    prompt_manifest = json.loads((ROOT / BASE / "E37_OPENING_COMPLETE_PROMPT_MANIFEST_V1.json").read_text(encoding="utf-8"))
    rows = {row["unit_id"]: row for row in prompt_manifest["rows"]}
    for unit_id, change in changes.items():
        task = tasks[unit_id]
        old_prompt = (ROOT / task["prompt_path"]).read_text(encoding="utf-8")
        lines = old_prompt.splitlines()
        marker = lines[0]
        entities = lines[1]
        weather = lines[2]
        spoken = "{无对白}"
        if task["dialogue"]:
            spoken = "".join(f"{{{row['speaker']}用视频模型原生自然普通话说：‘{row['spoken_text']}’；可见口型、气息、表情与起止时序同步}}" for row in task["dialogue"])
        prompt = (
            f"{marker}\n{entities}\n{weather}\n"
            f"镜头1【{'左侧脸近景' if unit_id.endswith('O02') else '越肩中近景' if unit_id.endswith('O03') else '正面反应特写'} 固定机位，全程锁死三脚架，禁止摇镜、横移、环绕、推拉、变焦】"
            f"首帧已经在动作中。先完成：{change['motion']}；再完成：对白与动作在同一自然呼吸组内收束；动作结果：{change['result']}。"
            f"{spoken} <衣料摩擦、轻微翻页、呼吸与孤灯灯芯同期声>。\n"
            f"【materially changed provider input】{change['contract']}。固定机位不等于静止表演；每个内部变化只发生一次，不复位、不重演、不慢放。\n"
            "色彩与动机光：室内墨蓝阴影、画外陶制油碟暖光、窗外冷月边光；脸、手与动作变化始终清楚。力量作用环境：发丝、衣袖、冷雾和门帘只响应人物动作，背景保持微弱环境生命。\n"
            "时代/OCR硬锁：架空古代中国；禁玻璃罩煤油灯、禁现代物件；任何纸页只许抽象墨迹，不生成可读汉字、数字、印章、字幕或水印。\n"
            "NEGATIVE_PROMPT: camera shake, handheld, pan, orbit, zoom, dolly, static talking head, repeated composition, repeated action, reset, replay, slow motion, frozen pose, glass kerosene lamp, readable text, subtitle, watermark, modern object, duplicate person.\n"
        )
        prompt_path = PROMPTS / f"{unit_id}_V2.txt"
        target = ROOT / prompt_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(prompt, encoding="utf-8")

        identity_rows = [row for row in task["reference_image_sequence"] if row.get("identity_reference") is True]
        temporal = {"asset_label": "@图片1", "role": "MATERIALLY_CHANGED_DISTINCT_COMPOSITION_START_ANCHOR", "path": change["anchor"], "sha256": sha(change["anchor"]), "identity_reference": False}
        sequence = [temporal]
        refs = [change["anchor"]]
        slot_map = {}
        for index, row in enumerate(identity_rows, 2):
            updated = dict(row)
            updated["asset_label"] = f"@图片{index}"
            sequence.append(updated)
            refs.append(updated["path"])
            slot_map[str(updated.get("entity_id") or "")] = updated["asset_label"]
        task["reference_image_sequence"] = sequence
        task["reference_images"] = refs
        task["planned_reference_image_count"] = 1
        task["state_reference_minimum"] = 1
        task["keyframe_interpolation_gate"] = {"status": "PASS", "checked_adjacent_pairs": 0, "adjacent_pairs_checked": 0, "reason": "One materially changed start anchor drives one continuous fixed-camera performance."}
        for binding in task["multimodal_entity_bindings"]:
            binding["identity_image_slot"] = slot_map[binding["entity_id"]]
        task["multimodal_binding_sha256"] = binding_digest(task["multimodal_entity_bindings"])
        task["performance_spec"]["motion_beats"][0]["action"] = change["motion"]
        task["performance_spec"]["motion_beats"][0]["end_state"] = change["result"]
        task["task_key"] = f"{unit_id}-OPENING-MATERIAL-CHANGE-RETRY-V2"
        task["batch_id"] = "E37-OPENING-FAILED-ONLY-RETRY-V2-20260803"
        task["prompt_file"] = str(prompt_path)
        task["prompt_path"] = str(prompt_path)
        task["prompt_sha256"] = sha(prompt_path)
        task["changed_input_repair"] = True
        task["unchanged_retry"] = False
        task["replaces_parent_task_id"] = {
            "E37-R-O02": "df92e260-a539-4188-aad8-7ddf577b3be0",
            "E37-R-O03": "688ce8f0-c43d-425b-8cd4-5b3b562e982b",
            "E37-R-O04": "14a01466-33f9-4c0e-b27a-0a11cb2ba345",
        }[unit_id]
        retry_tasks.append(task)
        rows[unit_id].update({"prompt_path": str(prompt_path), "prompt_sha256": sha(prompt_path)})

    prompt_manifest["rows"] = [rows[f"E37-R-O{i:02d}"] for i in range(1, 5)]
    anchor_plan = json.loads((ROOT / BASE / "E37_OPENING_ANCHOR_PLAN_V1.json").read_text(encoding="utf-8"))
    for unit in anchor_plan["units"]:
        if unit["unit_id"] not in changes:
            continue
        unit["planned_reference_image_count"] = 1
        unit["reference_image_task_keys"] = [f"{unit['unit_id']}-MATERIAL-CHANGE-START-V2"]
        unit["anchor_count_decision"].update({
            "planned_reference_image_count": 1,
            "reason": "The materially changed composition anchor independently supplies identity, axis and start motion for one continuous fixed-camera performance.",
            "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False},
            "anchor_roles": ["MATERIALLY_CHANGED_START_STATE"],
        })
        unit["keyframe_interpolation_gate"] = {"status": "PASS", "adjacent_pairs_checked": 0}
    anchor_plan["planned_reference_image_count"] = sum(row["planned_reference_image_count"] for row in anchor_plan["units"])
    anchor_path = OUT / "E37_OPENING_ANCHOR_PLAN_V2.json"
    write_json(anchor_path, anchor_plan)
    prompt_manifest["source_plan"] = str(anchor_path)
    prompt_manifest["source_plan_sha256"] = sha(anchor_path)
    complete_path = OUT / "E37_OPENING_COMPLETE_PROMPT_MANIFEST_V2.json"
    write_json(complete_path, prompt_manifest)
    config.update({"status": "READY_FOR_FAILED_ONLY_OPENING_RETRY_V2", "concurrency": 3, "max_retries": 0, "output_dir": "working_assets/e37_opening_replacement_v2_20260803/outputs", "qa_dir": "qa/e37_opening_replacement_v2_20260803", "anchor_count_plan_ref": str(anchor_path), "complete_video_prompt_manifest_ref": str(complete_path), "tasks": retry_tasks})
    config_path = OUT / "E37_OPENING_FAILED_ONLY_RETRY_BATCH_V2.json"
    write_json(config_path, config)
    print(json.dumps({"status": "BUILT", "config": str(config_path), "tasks": len(retry_tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
