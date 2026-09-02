#!/usr/bin/env python3
"""Compact Seedance 2 provider renderer over the shared execution-plan IR."""

from __future__ import annotations

from typing import Any
import re

try:
    from tools.grouped_camera_contract import compile_camera_prompt
    from tools.prompt_budget_observability import measure_prompt
    from tools.provider_semantic_coverage import build_semantic_coverage_receipt
    from tools.provider_contract_boundary import validate_provider_prompt_boundary
except ModuleNotFoundError:
    from grouped_camera_contract import compile_camera_prompt
    from prompt_budget_observability import measure_prompt
    from provider_semantic_coverage import build_semantic_coverage_receipt
    from provider_contract_boundary import validate_provider_prompt_boundary


SCHEMA = "qingshan.seedance2_provider_renderer.v1_shared_execution_ir"


def _dialogue(beat: dict[str, Any]) -> str:
    raw = str(beat.get("dialogue") or "").strip()
    if not raw:
        return ""
    speaker, separator, words = raw.partition("：")
    if not separator or not speaker.strip() or not words.strip():
        raise ValueError(f"DIALOGUE_SPEAKER_BINDING_INVALID:{raw}")
    return f"；{speaker.strip()}只说一次：“{words.strip()}”，其余人物闭口"


def _beat_line(beat: dict[str, Any]) -> str:
    primary = str(beat["primary_action"])
    dialogue_words = str(beat.get("dialogue") or "").partition("：")[2].strip()
    if dialogue_words and re.sub(r"\W", "", primary) == re.sub(r"\W", "", dialogue_words):
        primary = "按起态、表演和身体同步完成本拍对白"
    line = (
        f"{beat['start_seconds']:g}–{beat['end_seconds']:g}秒：从{beat['entry_state']}开始，"
        f"力源={beat['force_origin']}；{primary}"
    )
    interaction_mode = str(beat.get("interaction_mode") or "NONE")
    interaction_label = {
        "CONTACT": "真实接触",
        "EVASION": "明确闪避",
        "THREAT_THRESHOLD": "威胁临界点",
    }.get(interaction_mode, "无人物交互")
    if beat.get("contact_time_seconds") is not None:
        line += (
            f"；交互类型={interaction_label}；{float(beat['contact_time_seconds']):g}秒到达"
            f"{beat.get('contact_point') or interaction_label}"
        )
    elif beat.get("contact_point"):
        line += f"；交互类型={interaction_label}；交互位置={beat['contact_point']}"
    if beat.get("primary_feedback"):
        line += f"；主反馈={beat['primary_feedback']}"
    if beat.get("secondary_feedback"):
        line += f"；次反馈={beat['secondary_feedback'][0]}"
    line += f"；最后到达{beat['exit_state']}"
    line += _dialogue(beat)
    if beat.get("performance_cue"):
        line += f"；表演={beat['performance_cue']}"
    if beat.get("microexpression_cue"):
        line += f"；微表情={beat['microexpression_cue']}"
    if beat.get("body_sync_cue"):
        line += f"；身体同步={beat['body_sync_cue']}"
    if beat.get("internal_transition_after"):
        line += f"；拍后衔接={beat['internal_transition_after']}"
    return line + "。"


def render_sd2_prompt(unit: dict[str, Any], plan: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    uid = str(plan["unit_id"])
    camera = compile_camera_prompt(plan.get("camera_plan"), source_id=uid)
    transition = plan.get("transition") or {}
    timeline = []
    if transition.get("incoming"):
        timeline.append(f"开场承接：{transition['incoming']}，从该结果继续，不复位不重演。")
    action_beats = (plan.get("action_ir") or {}).get("causal_chains") or plan["beats"]
    timeline.extend(_beat_line(beat) for beat in action_beats)
    if transition.get("outgoing"):
        timeline.append(f"结尾交棒：完成{transition['outgoing']}后保留自然微动和现场声尾，不另起动作。")
    sound_parts = []
    for key in ("ambience", "foley", "action_sound"):
        sound_parts.extend(plan.get("sounds", {}).get(key) or [])
    sound = "；".join(sound_parts) or "保留同任务原生环境声、拟音、动作声与已声明对白"
    environment_rows = plan.get("environment_motion") or []
    environment = "；".join(environment_rows)
    voice_rows = [
        f"{row['speaker']}使用{row['audio_slot']}固定声线" if row.get("audio_slot") else f"{row['speaker']}使用已登记固定声线"
        for row in plan.get("voice_bindings") or []
    ]
    voices = "；".join(voice_rows)
    negatives = list(plan.get("negative_constraints") or [])
    negatives.extend([
        "无字幕、水印、可读文字或界面",
        "人物身份、服装、道具归属、地图、天气和光向不得漂移",
        "不用冻结、循环、慢动作或变速补时",
    ])
    physical_rules = []
    if plan.get("interaction_topology_required"):
        physical_rules.append(
            "肢体归属唯一且肩—臂—腕—手连续可追溯；不得孤立手臂、多肢、断肢、反关节、穿透固定物或交换主人"
        )
    if plan.get("combat_execution_required"):
        physical_rules.append(
            "打斗按起势与位移→唯一接触或明确闪避→受力反馈→新站位的实时物理链完成；不摆拍、不太极推手、不用静帧插值"
        )
    text = "\n".join([
        f"【任务】{plan['duration_seconds']:g}秒，9:16，{unit.get('resolution') or '720p'}，seedance-2.0-pro，真人实拍电影质感。",
        f"【锚点】{plan['identity_prop_fact']}；{plan['space_weather_fact']}。",
        "【时间轴】\n" + "\n".join(timeline),
        "【摄影】" + camera,
        "【环境】" + (environment or "背景与群众只按剧情因果保持真实微动，不得冻结成静态图") + "。",
        "【声音】" + sound + (f"；{voices}" if voices else "") + "；禁止外加默认BGM，除非结构化音频模式明确绑定。",
        "【物理】" + "；".join(physical_rules) + "。" if physical_rules else "【物理】按时间轴完成真实动作因果。",
        "【限制】" + "；".join(dict.fromkeys(value.strip().rstrip("。；") for value in negatives if value.strip())) + "。",
    ]) + "\n"
    boundary = validate_provider_prompt_boundary(text, source_id=uid, model_family="SEEDANCE_2")
    if boundary["status"] != "PASS":
        raise ValueError(";".join(boundary["failures"]))
    clause_evidence = {
        "ANCHOR.IDENTITY_PROP": plan["identity_prop_fact"],
        "ANCHOR.SPACE_WEATHER": plan["space_weather_fact"],
        "CAMERA.PLAN": camera,
    }
    if plan.get("interaction_topology_required"):
        clause_evidence["PHYSICAL.INTERACTION_TOPOLOGY"] = physical_rules[0]
    if plan.get("combat_execution_required"):
        clause_evidence["COMBAT.EXECUTION_RULE"] = physical_rules[-1]
    if transition.get("incoming"):
        clause_evidence["TRANSITION.INCOMING"] = transition["incoming"]
    if transition.get("outgoing"):
        clause_evidence["TRANSITION.OUTGOING"] = transition["outgoing"]
    for index, beat in enumerate(action_beats, 1):
        prefix = f"BEAT.{index}"
        clause_evidence[f"{prefix}.ENTRY"] = beat["entry_state"]
        dialogue_words = str(beat.get("dialogue") or "").partition("：")[2].strip()
        clause_evidence[f"{prefix}.ACTION"] = (
            dialogue_words
            if dialogue_words and re.sub(r"\W", "", str(beat["primary_action"])) == re.sub(r"\W", "", dialogue_words)
            else beat["primary_action"]
        )
        clause_evidence[f"{prefix}.FORCE_ORIGIN"] = beat["force_origin"]
        clause_evidence[f"{prefix}.INTERACTION_MODE"] = {
            "CONTACT": "真实接触",
            "EVASION": "明确闪避",
            "THREAT_THRESHOLD": "威胁临界点",
        }.get(str(beat.get("interaction_mode") or "NONE"), "无人物交互")
        clause_evidence[f"{prefix}.EXIT"] = beat["exit_state"]
        if beat.get("contact_time_seconds") is not None:
            clause_evidence[f"{prefix}.CONTACT_TIME"] = f"{float(beat['contact_time_seconds']):g}秒"
        if beat.get("contact_point"):
            clause_evidence[f"{prefix}.CONTACT_POINT"] = beat["contact_point"]
        if beat.get("primary_feedback"):
            clause_evidence[f"{prefix}.PRIMARY_FEEDBACK"] = beat["primary_feedback"]
        for secondary_index, value in enumerate(beat.get("secondary_feedback") or [], 1):
            clause_evidence[f"{prefix}.SECONDARY_FEEDBACK.{secondary_index}"] = value
        if beat.get("dialogue"):
            clause_evidence[f"{prefix}.DIALOGUE"] = beat["dialogue"].partition("：")[2]
        if beat.get("microexpression_cue"):
            clause_evidence[f"{prefix}.MICROEXPRESSION"] = beat["microexpression_cue"]
        if beat.get("body_sync_cue"):
            clause_evidence[f"{prefix}.BODY_SYNC"] = beat["body_sync_cue"]
        if beat.get("internal_transition_after"):
            clause_evidence[f"{prefix}.INTERNAL_TRANSITION_AFTER"] = beat["internal_transition_after"]
    for key in ("ambience", "foley", "action_sound"):
        for index, value in enumerate((plan.get("sounds") or {}).get(key) or [], 1):
            clause_evidence[f"SOUND.{key.upper()}.{index}"] = value
    for index, value in enumerate(environment_rows, 1):
        clause_evidence[f"ENVIRONMENT_MOTION.{index}"] = value
    for index, value in enumerate(voice_rows, 1):
        clause_evidence[f"VOICE_BINDING.{index}"] = value
    coverage = build_semantic_coverage_receipt(
        plan=plan,
        prompt_text=text,
        model_family="SEEDANCE_2",
        clause_evidence=clause_evidence,
    )
    if coverage["status"] != "PASS":
        raise ValueError(";".join(coverage["failures"]))
    return text, {
        "schema": SCHEMA,
        "status": "PASS",
        "unit_id": uid,
        "model_family": "SEEDANCE_2",
        "immutable_contract_sha256": plan["immutable_contract_sha256"],
        "execution_semantics_sha256": plan["execution_semantics_sha256"],
        "camera_language_selection": plan["camera_language_selection"],
        "motion_density_gate": plan["motion_density_gate"],
        "provider_semantic_coverage_receipt": coverage,
        "provider_boundary": boundary,
        "prompt_budget": measure_prompt(text, source_id=uid, model_family="SEEDANCE_2"),
    }
