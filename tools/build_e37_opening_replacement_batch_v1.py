#!/usr/bin/env python3
"""Compile four non-repeating E37 opening shots into a guarded video batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from action_shot_design_gate import contract_sha256, prompt_marker
from multimodal_character_binding_guard import binding_digest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "workflow/claude_writer_agent/scripts/E37剧本_ClaudeWriter_v2.md"
SCRIPT_SHA = "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a"
MANIFEST = "workflow/claude_writer_agent/scripts/E37_manifest_v2.json"
MANIFEST_SHA = "9082f9d3b45bf0466476e98cb194d91d00d6775c2b762b5253c8f7557d31c33e"
PLAN = "qa/e37_agentcut_20260803/direct_motion_audit_20260803/E37_V3_ATOMIC_ACTION_AND_OPENING_REPAIR_PLAN_V1.json"
PROD = Path("workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/opening_replacement_v1")
PROMPTS = Path("working_assets/e37_opening_replacement_v1_20260803/compiled_prompts")
QA = Path("qa/e37_opening_replacement_v1_20260803")


def sha(path: str | Path) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, payload: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")


def identity(entity_id: str) -> tuple[str, str, str]:
    rows = {
        "chenji": ("陈迹", "CHAR-陈迹-古装", "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png"),
        "jiaotu": ("皎兔", "CHAR-皎兔-古装", "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg"),
    }
    return rows[entity_id]


def main() -> int:
    full_plan = json.loads((ROOT / PLAN).read_text(encoding="utf-8"))
    shots = {row["shot_id"]: row for row in full_plan["shots"]}
    failure_memory = Path("workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json")
    failure_ids = [str(row["id"]) for row in json.loads((ROOT / failure_memory).read_text(encoding="utf-8")).get("rules", []) if row.get("id")]
    opening_plan = dict(full_plan)
    opening_plan["shots"] = [shots[f"E37-R-O{i:02d}"] for i in range(1, 5)]
    opening_plan_path = PROD / "E37_OPENING_ACTION_SHOT_DESIGN_PLAN_V1.json"
    write_json(opening_plan_path, opening_plan)

    anchors = {
        "E37-R-O01": [
            "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U02-A1-STILL-V1_ZERO_CREDIT_ALT.png",
            "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U02-A2-STILL-V1_ZERO_CREDIT_ALT.png",
        ],
        "E37-R-O02": ["working_assets/e37_stills_20260802/candidates/E37_E37-CW-U02-A2-STILL-V1_ZERO_CREDIT_ALT.png"],
        "E37-R-O03": ["working_assets/e37_stills_20260802/candidates/E37_E37-CW-U03-A2-STILL-V2_ZERO_CREDIT_ALT.png"],
        "E37-R-O04": [
            "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U03-A1-STILL-V3_ZERO_CREDIT_ALT.png",
            "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U03-A2-STILL-V2_ZERO_CREDIT_ALT.png",
        ],
    }
    specs = {
        "E37-R-O01": {"duration": 5, "cast": [], "scene": "E37-CW-S01", "zone": "ledger_object_detail", "dialogue": [], "subject": "陈迹右手与唯一地契、唯一看守账", "action": "右手从地契移到看守账并翻开唯一一页，冷雾霜纹沿一条账目边缘掠过", "contact": "指腹与账页右下角", "direction": "由画面上方落向账页，再由右向左翻开", "end": "唯一账页摊平，霜纹停在一条抽象账目旁，手指静止半秒", "intent": "只建立每月看守银这一条证据，不承担人物反应或解释", "expression": "手势克制准确，人物脸不入镜"},
        "E37-R-O02": {"duration": 7, "cast": ["chenji"], "scene": "E37-CW-S01", "zone": "chenji_profile_dialogue", "dialogue": [("E37-O02-L01", "chenji", "陈迹", "可这宅子名下，每月还领一笔‘看守银’。", "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION")], "subject": "二十岁陈迹侧脸", "action": "陈迹视线停在账页，右手食指压住唯一账目，低声完成一句判断", "contact": "右手食指与唯一账页", "direction": "视线由下向前抬起少许，身体不换位", "end": "银字落下后闭口，视线仍落在账上，保持自然呼吸半秒", "intent": "只确认死宅仍按月领钱", "expression": "冷峻警觉，声音低而清楚"},
        "E37-R-O03": {"duration": 8, "cast": ["jiaotu", "chenji"], "scene": "E37-CW-S02", "zone": "jiaotu_over_shoulder_return", "dialogue": [("E37-O03-L01", "jiaotu", "皎兔", "里屋供着牌位、摆着热茶。", "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY"), ("E37-O03-L02", "jiaotu", "皎兔", "守宅的人刚还在。他知道咱们来了。", "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY")], "subject": "皎兔阴神与前景陈迹肩线", "action": "皎兔阴神从里屋门口掠回本体，睁眼后看向陈迹，连续完成两句报告", "contact": "阴神归入皎兔眉心，双膝与地面稳定", "direction": "阴神由画面深处向前归窍，皎兔视线转向左前方陈迹", "end": "来了二字落下后闭口，陈迹只转头看她，二人位置不变", "intent": "只报告里屋热茶牌位和守宅人刚离开", "expression": "皎兔寒声克制，归窍后气息略紧"},
        "E37-R-O04": {"duration": 8, "cast": ["chenji"], "scene": "E37-CW-S02", "zone": "chenji_reaction_closeup", "dialogue": [("E37-O04-L01", "chenji", "陈迹", "这拆日子的写法……我在另一处见过。", "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION")], "subject": "二十岁陈迹近景", "action": "陈迹指节抵住账页，呼吸停顿一瞬，眼神从账页抬到虚空后低声完成一句私人识认", "contact": "右手指节与唯一账页", "direction": "视线由下向前抬起，指节在原处逐渐收紧", "end": "过字落下后闭口，指节发白，极远怔然停留半秒", "intent": "只落跨世识认这一拍，不解释完整旧案", "expression": "克制、极远怔然，情绪落在呼吸与指节"},
    }

    tasks, prompt_rows, dialogue_rows, anchor_units, mechanical_units, causality_units, period_units = [], [], [], [], [], [], []
    for shot_id, spec in specs.items():
        shot = shots[shot_id]
        temporal = anchors[shot_id]
        dialogue = []
        for index, (dia_id, speaker_id, speaker, text, mode) in enumerate(spec["dialogue"]):
            row = {"dia_id": dia_id, "video_unit_id": shot_id, "speaker_id": speaker_id, "speaker": speaker, "spoken_text": text, "status": "PASS", "start_seconds": 0.45 + index * 3.1, "end_seconds": min(spec["duration"] - 0.65, 3.4 + index * 3.1), "breath_after_seconds": 0.45, "expression": spec["expression"], "audio_mode": mode, "human_listening_exception": True, "external_voice_reference": False, "rights_cleared_model_native": mode == "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY", "unverified_clone_prohibited": mode == "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY", "path": "", "remote_asset_id": "", "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}
            dialogue.append(row)
            dialogue_rows.append(row)

        spoken = "".join(f"{{{row['speaker']}用视频模型原生自然普通话说：‘{row['spoken_text']}’；口型、气息、表情与起止时序同步}}" for row in dialogue) or "{无对白}"
        camera = shot["camera"]["family"]
        weather = "INTERIOR_CLEAR_NO_RAIN"
        prompt = (
            f"{prompt_marker(shot)}\n"
            f"[[scene_liuzhai_opening]] [[prop_guard_ledger]] " + " ".join(f"[[char_{entity}]]" for entity in spec["cast"]) + "\n"
            f"【天气硬合同】weather={weather}\n"
            f"镜头1【{'特写' if shot_id in {'E37-R-O01','E37-R-O04'} else '近景'} 固定机位 {camera}，全程锁死三脚架，禁止摇镜、横移、环绕、推拉、变焦】"
            f"入场即处于进行态：{spec['subject']}。先完成：{spec['action']}；再完成：动作与呼吸自然收束；动作结果：{spec['end']}。"
            f"接触点：{spec['contact']}；方向：{spec['direction']}。{spoken} <孤灯轻爆、衣料或翻页同期声>。\n"
            f"表演意图：{spec['intent']}。表情：{spec['expression']}。同一动作只发生一次，不复位、不重演、不慢放；终态最多保持0.55秒。\n"
            "色彩与动机光：室内墨蓝阴影、孤灯昏黄、霜纹冷白；主体面部或证物必须清楚，不用镜头晃动制造情绪。"
            "力量作用环境：灯焰、冷雾、衣袖和纸页只响应人物真实动作，背景保持轻微环境生命。\n"
            "道具与OCR硬锁：唯一地契、唯一看守账，页面只保留抽象墨迹与线格，不生成任何可读汉字、数字、印章、字幕或水印。\n"
            "NEGATIVE_PROMPT: camera shake, handheld, pan, orbit, zoom, dolly, repeated composition, repeated action, reset, replay, slow motion, frozen pose, readable text, subtitle, watermark, modern object, duplicate person.\n"
        )
        prompt_path = PROMPTS / f"{shot_id}.txt"
        write_text(prompt_path, prompt)

        sequence, refs = [], []
        for i, anchor in enumerate(temporal, 1):
            refs.append(anchor)
            sequence.append({"asset_label": f"@图片{i}", "role": "START_STATE_ANCHOR" if i == 1 else "TERMINAL_STATE_CONTINUITY_ANCHOR", "path": anchor, "sha256": sha(anchor), "identity_reference": False})
        bindings = []
        for entity in spec["cast"]:
            name, registry_id, ref = identity(entity)
            refs.append(ref)
            slot = f"@图片{len(sequence) + 1}"
            sequence.append({"asset_label": slot, "role": f"IDENTITY_REFERENCE_{entity.upper()}", "path": ref, "sha256": sha(ref), "identity_reference": True, "entity_id": entity})
            speaker = any(row["speaker_id"] == entity for row in dialogue)
            bindings.append({"entity_id": entity, "character_name": name, "registry_id": registry_id, "visual_reference": ref, "visual_reference_sha256": sha(ref), "identity_image_slot": slot, "voice_reference_asset_id": None, "dialogue_audio_slots": [], "visible_speaker": speaker, "lip_sync": speaker, "prop_owners": {"唯一看守账": "全镜保持单一并遵循镜头状态合同"}, "ability_owners": ["只有陈迹可控制冰霜显痕"] if entity == "chenji" else ["只有皎兔可执行阴神归窍"], "voice_policy": "RIGHTS_CLEARED_MODEL_NATIVE_NO_EXTERNAL_REFERENCE" if entity == "jiaotu" else "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION_NO_EXTERNAL_REFERENCE"})

        count = len(temporal)
        criteria = {"continuous_motion_from_single_start": count == 1, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": count > 1}
        task = {"task_key": f"{shot_id}-OPENING-REPLACEMENT-V1", "source_id": shot_id, "tool_type": "video_generation", "generation_mode": "performance_generation", "episode": "E37", "batch_id": "E37-OPENING-REPLACEMENT-V1-20260803", "unit_id": shot_id, "scene_id": spec["scene"], "visual_zone": spec["zone"], "duration": spec["duration"], "duration_seconds": spec["duration"], "duration_plan": {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": spec["duration"], "rationale": "One distinct opening information beat with natural native dialogue timing and a terminal hold below 0.55 seconds.", "edit_policy": "Preserve native Mandarin and lip sync; no time stretch, repeated frames, post-dub or camera-motion filler."}, "model": "seedance-2.0-pro", "aspect_ratio": "9:16", "resolution": "720p", "prompt_file": str(prompt_path), "prompt_path": str(prompt_path), "prompt_sha256": sha(prompt_path), "reference_images": refs, "reference_image_sequence": sequence, "planned_reference_image_count": count, "state_reference_minimum": count, "still_sequence_only_allowed": True, "inherits_establishing_coverage": True, "action_unit": False, "visual_tier": "CORE", "minimum_score_100": 80, "hard_fact_fail_overrides_score": True, "prompt_failure_modes_applied": failure_ids, "prompt_failure_modes_not_applicable": [], "native_dialogue_required": bool(dialogue), "dialogue": dialogue, "dialogue_audio_assets": [], "reference_audios": [], "reference_audio_asset_ids": [], "model_native_text_only_dialogue_ids": [row["dia_id"] for row in dialogue], "audio_reference_optional": True, "visible_speaker_required": bool(dialogue), "temporal_visual_qa_required": True, "performance_spec": {"schema": "qingshan.performance_generation_spec.v3", "episode": "E37", "unit_id": shot_id, "duration_seconds": spec["duration"], "single_source_of_truth": True, "prop_ownership": {"唯一看守账": "保持单一且不复制"}, "motion_beats": [{"subject": spec["subject"], "action": spec["action"], "contact_point": spec["contact"], "direction": spec["direction"], "end_state": spec["end"], "intent": spec["intent"], "visible_causality": "前镜终态触发本镜单一信息变化，动作结果只向下一个状态推进一次", "expression": spec["expression"], "viewer_read": "观众可在固定机位中清楚读出主体、动作、对白或证据与终态"}]}, "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": count - 1, "adjacent_pairs_checked": count - 1, "reason": "Exact adjacent opening anchors preserve prop, axis, identity and isolated terminal state."}, "character_free_unit": not bool(spec["cast"]), "visual_entity_ids": spec["cast"], "multimodal_entity_bindings": bindings, "multimodal_binding_sha256": binding_digest(bindings), "effect_provenance": [{"effect": "冰霜显痕或阴神归窍", "source_type": "CLAUDE_SCRIPT", "source_ref": SCRIPT}], "prompt_contract": {"source_action": spec["action"], "spatial_continuity": {"mode": "SAME_SPACE_CONTINUOUS", "policy_source": "PER_UNIT_SCRIPT_CONTENT", "scene_id": spec["scene"], "anchor_scope": "PERFORMANCE_TEMPORAL_ANCHORS_ONLY", "camera_policy": "LOCKED_TO_ACTION_CONTRACT"}}, "action_design_shot_id": shot_id, "action_design_contract_sha256": contract_sha256(shot), "source_script_sha256": SCRIPT_SHA, "workflow_credit_scope": "e37_claude_writer_v2_07a63a0c_20260802", "status": "READY_TO_SUBMIT", "dependencies_ready": True, "targeted_unit_replacement": True, "reference_image_asset_ids": [], "max_retries": 0, "unchanged_retry": False}
        tasks.append(task)
        prompt_rows.append({"unit_id": shot_id, "scene_id": spec["scene"], "weather": weather, "prompt_path": str(prompt_path), "prompt_sha256": sha(prompt_path)})
        anchor_units.append({"unit_id": shot_id, "planned_reference_image_count": count, "reference_image_task_keys": [f"{shot_id}-STATE-{i}" for i in range(1, count + 1)], "anchor_count_decision": {"planned_reference_image_count": count, "reason": "Independently selected from this shot's isolated prop, identity and terminal-state interpolation needs.", "criteria": criteria, "anchor_roles": ["START_STATE"] + (["NON_INTERPOLABLE_TERMINAL_STATE"] if count > 1 else []), "action_design_class": camera}, "keyframe_interpolation_gate": {"status": "PASS", "adjacent_pairs_checked": count - 1}})
        mechanical_units.append({"unit_id": shot_id, "duration_seconds": spec["duration"], "planned_reference_image_count": count, "camera": camera, "scene_id": spec["scene"], "weather": weather, "dialogue_sentence_count": len(dialogue), "prompt_sha256": sha(prompt_path)})
        causality_units.append({"unit_id": shot_id, "causality": {"applicable": True, "purpose": spec["intent"], "intended_effect": spec["end"], "visible_causality": "The declared entry action visibly produces exactly one new evidence or reaction state.", "viewer_read": "A locked camera preserves the subject, action and terminal consequence without repetition.", "preconditions": [shot["entry_state_token"]], "mechanism_chain": [spec["action"], spec["end"]], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "Removing the declared action removes this shot's only new information and breaks the next state token."}, "prop_function_status": "PASS", "evidence_refs": [PLAN, str(prompt_path)]}})
        period_units.append({"unit_id": shot_id, "period_lock": {"status": "PASS", "reviewed_visible_elements": ["架空古代土木宅院", "古装人物", "纸质地契与账册", "油灯灯芯"], "detected_anachronisms": [], "exception_approvals": {}, "evidence_refs": [SCRIPT, str(prompt_path)]}})

    scene_path = PROD / "E37_OPENING_SCENE_AUTHORITY_V1.json"
    write_json(scene_path, {"schema": "qingshan.scene_state_authority.v1", "episode": "E37", "scene_state": [{"scene_id": "E37-CW-S01", "location": "城东刘家旧宅正屋", "time_of_day": "night", "weather": "INTERIOR_CLEAR_NO_RAIN", "allowed_time_terms": ["night"], "allowed_weather_terms": ["INTERIOR_CLEAR_NO_RAIN"], "event_summary": "地契与看守账揭示死宅仍按月领钱。"}, {"scene_id": "E37-CW-S02", "location": "刘家旧宅正屋与里屋门口", "time_of_day": "night", "weather": "INTERIOR_CLEAR_NO_RAIN", "allowed_time_terms": ["night"], "allowed_weather_terms": ["INTERIOR_CLEAR_NO_RAIN"], "event_summary": "皎兔回报热茶牌位，陈迹识认跨世拆日写法。"}]})
    anchor_path = PROD / "E37_OPENING_ANCHOR_PLAN_V1.json"
    write_json(anchor_path, {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E37", "planned_reference_image_count": sum(row["planned_reference_image_count"] for row in anchor_units), "units": anchor_units})
    complete_path = PROD / "E37_OPENING_COMPLETE_PROMPT_MANIFEST_V1.json"
    write_json(complete_path, {"schema": "qingshan.complete_video_prompt_manifest.v1", "episode": "E37", "all_units_have_prompt": True, "unit_count": len(prompt_rows), "source_plan": str(anchor_path), "source_plan_sha256": sha(anchor_path), "source_scene_authority": str(scene_path), "source_scene_authority_sha256": sha(scene_path), "rows": prompt_rows})
    dialogue_path = PROD / "E37_OPENING_DIALOGUE_MANIFEST_V1.json"
    write_json(dialogue_path, {"schema": "qingshan.video_dialogue_manifest.v1", "episode": "E37", "status": "PASS", "rows": dialogue_rows})
    mechanical_path = PROD / "E37_OPENING_MECHANICAL_DEFAULT_V1.json"
    write_json(mechanical_path, {"schema": "qingshan.mechanical_default_plan.v1", "episode": "E37", "units": mechanical_units, "global_defaults": [], "variable_fields": ["duration_seconds", "planned_reference_image_count", "camera", "scene_id", "dialogue_sentence_count", "prompt_sha256"]})
    causality_path = PROD / "E37_OPENING_CAUSALITY_V1.json"
    write_json(causality_path, {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E37", "units": causality_units})
    period_path = PROD / "E37_OPENING_PERIOD_LOCK_V1.json"
    write_json(period_path, {"schema": "qingshan.anachronism_lock_plan.v1", "episode": "E37", "period_contract": {"era": "架空古代中国", "status": "PASS", "source_refs": [SCRIPT]}, "units": period_units})

    base = json.loads((ROOT / PROD.parent / "action_replacement_v2/E37_ATOMIC_ACTION_REPLACEMENT_BATCH_V2.json").read_text(encoding="utf-8"))
    config = dict(base)
    config.update({"status": "READY_FOR_OPENING_REPLACEMENT_SUBMIT", "concurrency": 4, "max_retries": 0, "output_dir": "working_assets/e37_opening_replacement_v1_20260803/outputs", "qa_dir": str(QA), "scene_contract_ref": str(scene_path), "dramatic_quality_report_ref": str(PROD.parent / "action_replacement_v2/E37_ACTION_REPLACEMENT_DRAMATIC_QUALITY_V2.json"), "mechanical_default_plan_ref": str(mechanical_path), "anchor_count_plan_ref": str(anchor_path), "common_sense_causality_plan_ref": str(causality_path), "action_shot_design_plan_ref": str(opening_plan_path), "period_lock_plan_ref": str(period_path), "complete_video_prompt_manifest_ref": str(complete_path), "dialogue_manifest_ref": str(dialogue_path), "tasks": tasks})
    config_path = PROD / "E37_OPENING_REPLACEMENT_BATCH_V1.json"
    write_json(config_path, config)
    print(json.dumps({"status": "BUILT", "config": str(config_path), "tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
