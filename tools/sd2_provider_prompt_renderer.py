#!/usr/bin/env python3
"""Compact Seedance 2 provider renderer over the shared execution-plan IR."""

from __future__ import annotations

from typing import Any
import re

try:
    from tools.editorial_pacing_contract import delivery_clause, content_window_clause
    from tools.grouped_camera_contract import compile_camera_prompt
    from tools.prompt_budget_observability import measure_prompt
    from tools.provider_semantic_coverage import build_semantic_coverage_receipt
    from tools.provider_contract_boundary import validate_provider_prompt_boundary
    from tools.visual_culture_contract import prompt_block_zh as visual_culture_prompt_block
    from tools.event_boundary_continuity_contract import (
        provider_shot_state_lock_texts, provider_state_lock_text,
    )
except ModuleNotFoundError:
    from editorial_pacing_contract import delivery_clause, content_window_clause
    from grouped_camera_contract import compile_camera_prompt
    from prompt_budget_observability import measure_prompt
    from provider_semantic_coverage import build_semantic_coverage_receipt
    from provider_contract_boundary import validate_provider_prompt_boundary
    from visual_culture_contract import prompt_block_zh as visual_culture_prompt_block
    from event_boundary_continuity_contract import (
        provider_shot_state_lock_texts, provider_state_lock_text,
    )


SCHEMA = "qingshan.seedance2_provider_renderer.v1_shared_execution_ir"


def _sanitize_provider_ids(value: str) -> str:
    """Translate internal map/space IDs to provider-safe natural language."""
    value = re.sub(r"\bGLOBAL-SPACE-[A-Z0-9-]+", "已锁定的同一全局空间", value, flags=re.IGNORECASE)
    value = re.sub(r"\bLOC-[A-Z0-9-]+", "已锁定的同一地点", value, flags=re.IGNORECASE)
    return re.sub(r"\bSUB(?:SPACE)?-[A-Z0-9-]+", "已锁定的同一子空间", value, flags=re.IGNORECASE)


def _dialogue(beat: dict[str, Any]) -> str:
    raw = str(beat.get("dialogue") or "").strip()
    if not raw:
        return ""
    speaker, separator, words = raw.partition("：")
    if not separator or not speaker.strip() or not words.strip():
        raise ValueError(f"DIALOGUE_SPEAKER_BINDING_INVALID:{raw}")
    pace = delivery_clause(beat)
    return f"；{speaker.strip()}只说一次：“{words.strip()}”，其余人物闭口" + (f"；{pace}" if pace else "")


def _beat_line(beat: dict[str, Any]) -> str:
    primary = str(beat["primary_action"])
    dialogue_words = str(beat.get("dialogue") or "").partition("：")[2].strip()
    if dialogue_words and re.sub(r"\W", "", primary) == re.sub(r"\W", "", dialogue_words):
        primary = "按起态、表演和身体同步完成本拍对白"
    line = (
        f"{beat['start_seconds']:g}–{beat['end_seconds']:g}秒：从{beat['entry_state']}开始，"
        f"力源={beat['force_origin']}；{primary}"
    )
    ownership = beat.get("entry_state_ownership") or {}
    owner = str(ownership.get("actor") or "").strip()
    patient = str(ownership.get("patient") or "").strip()
    if owner:
        line += f"；起态动作、肢体与道具主人={owner}"
        if patient:
            line += f"；起态唯一承受者={patient}"
        line += "；不得把起态肢体、武器或受力部位嫁接给本拍其他人物"
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


def _role_line(row: dict[str, Any]) -> str:
    actor = str(row.get("primary_actor") or "场景环境")
    speaker = str(row.get("dialogue_speaker") or "")
    listener = str(row.get("dialogue_listener") or "")
    patient = str(row.get("action_patient") or "")
    silent_id = str(row.get('silent_visual_speaker_id') or '')
    silent_name = (row.get('entity_names') or {}).get(silent_id)
    if silent_id and (not silent_name or speaker):
        raise ValueError('SILENT_VISUAL_SPEECH_BINDING_CONFLICT')
    pieces = [f"{row.get('shot_id') or '本拍'}：{actor}执行本拍主动作；其余人物仅执行各自明确声明的动作与反应"]
    if patient:
        pieces.append(f"{patient}是唯一动作承受者")
    if speaker:
        pieces.append(f"只有{speaker}开口")
        declared_names = set((row.get("entity_names") or {}).values())
        if listener and (not row.get("entity_names") or listener in declared_names):
            pieces.append(f"{listener}闭口聆听")
        else:
            pieces.append("其余已声明人物不代说对白，不因听者称呼增加入画人物")
    elif silent_id:
        pieces.append(f"只有{silent_name}呈现口述的可见嘴部动作；本拍是无可辨人声的视觉蒙太奇，不生成、不重复任何对白；其余人物闭口")
    else:
        pieces.append("本拍无对白，不生成可辨人声；嘴部仅随已声明的非对白动作活动")
    pieces.append("不得交换人物、肢体、武器、动作或声音")
    for cid, state in (row.get("entity_states") or {}).items():
        name = (row.get("entity_names") or {}).get(cid, cid)
        visibility = (row.get("entity_face_visibility") or {}).get(cid) or (row.get("entity_presence") or {}).get(cid)
        pieces.append(f"{name}的独立状态：{state}" + (f"；入画约束={visibility}" if visibility else ""))
    return "，".join(pieces) + "。"


def _vc_prompt_block_for_unit(unit: dict[str, Any]) -> str:
    """The visual-culture prose belongs to the episodes its contract governs.

    Below ``visual_culture_contract.ACTIVE_FROM_EPISODE`` a line carries its own locked profile
    and its own prompt language, so the qingshan block is not rendered (it used to be absent
    because those units carried no contract at all).
    """
    try:
        from tools.visual_culture_contract import ACTIVE_FROM_EPISODE
    except ImportError:  # pragma: no cover - direct-script import path
        from visual_culture_contract import ACTIVE_FROM_EPISODE
    match = re.search(r"(?:^|[^A-Z])E(\d+)", str(unit.get("episode") or unit.get("unit_id") or "").upper())
    if not match or int(match.group(1)) < ACTIVE_FROM_EPISODE:
        return ""
    return visual_culture_prompt_block(unit.get("visual_culture_contract"))


def scoped_transition_text(plan: dict[str, Any]) -> dict[str, str]:
    """Keep neighbouring-shot action text out of this provider request.

    Full bridges remain in the machine contract. Rendering their two sides as
    an instruction to 'complete' the bridge leaks a successor's performance.
    """
    original = plan.get("transition") or {}
    beats = plan.get("beats") or []
    result = {}
    for side, index, field in (("incoming", 0, "entry_state"), ("outgoing", -1, "exit_state")):
        if not original.get(side):
            continue
        state = str(beats[index].get(field) or "").strip() if beats else ""
        if not state:
            raise ValueError(f"TRANSITION_LOCAL_ENDPOINT_MISSING:{plan.get('unit_id')}:{side}")
        result[side] = state
    return result


def scoped_camera_prompt(plan: dict[str, Any]) -> str:
    uid = str(plan['unit_id'])
    if plan.get('camera_scope_policy') != 'PER_SHOT_EXPLICIT':
        return compile_camera_prompt(plan.get('camera_plan'), source_id=uid)
    cameras = plan.get('per_shot_camera_plans') or []
    beats = plan.get('beats') or []
    if not cameras or len(cameras) != len(beats):
        raise ValueError(f'PER_SHOT_CAMERA_BEAT_COUNT_MISMATCH:{uid}')
    from tools.sd2_shot_camera_adapter import render_shot_cameras
    return '按时间轴逐拍执行各自机位，不将任一拍的运镜扩展到整段。\n' + render_shot_cameras(cameras)


def render_sd2_prompt(unit: dict[str, Any], plan: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    uid = str(plan["unit_id"])
    camera = scoped_camera_prompt(plan)
    transition = scoped_transition_text(plan)
    timeline = []
    content_window = content_window_clause(plan)
    if content_window:
        timeline.append(content_window)
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
    state_lock = provider_state_lock_text(plan, language="ZH") if plan.get("persistent_state_contract") else ""
    shot_state_locks = provider_shot_state_lock_texts(plan, language="ZH")
    voice_rows = [
        f"{row['speaker']}使用{row['audio_slot']}固定声线" if row.get("audio_slot") else f"{row['speaker']}使用已登记固定声线"
        for row in plan.get("voice_bindings") or []
    ]
    voices = "；".join(voice_rows)
    role_rows = [_role_line(row) for row in plan.get("role_bindings") or []]
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
    wuxia_profile = plan.get("wuxia_combat_profile_selection") or {}
    if wuxia_profile.get("status") == "SELECTED":
        physical_rules.append(
            "武侠动作镜头原型[INFERRED_RECONSTRUCTED_NOT_ORIGINAL]："
            + str(wuxia_profile.get("prompt_module_zh") or "")
            + "；该原型只翻译既有Action-IR，不新增招式、命中、伤势、效果、胜负或剧情结果"
        )
        negatives.extend(wuxia_profile.get("negative_constraints_zh") or [])
    reroll_directive = str(unit.get("reroll_performance_directive") or plan.get("reroll_performance_directive") or "").strip()
    text = "\n".join([
        f"【任务】{plan['duration_seconds']:g}秒，9:16，{unit.get('resolution') or '720p'}，seedance-2.0-pro，真人实拍电影质感。",
        f"【锚点】{plan['identity_prop_fact']}；{plan['space_weather_fact']}。",
        # 2026-09-20 (nalu line): prompt_block_zh spells the qingshan profile's own prose
        # (北宋武侠、札甲/山文甲/兜鍪).  compile_grouped_seedance_manifest.py began attaching a
        # visual_culture_contract to every compiled unit today, which would inject that armour
        # prose into 夜无疆's village drama under its own profile id — wrong content, and a text
        # change that would re-fingerprint 13 already-paid in-flight video tasks.  The block
        # belongs to the episodes its contract governs (>= visual_culture_contract.ACTIVE_FROM_EPISODE).
        _vc_prompt_block_for_unit(unit),
        *(["【连续事件硬合同】" + state_lock + "。"] if state_lock else []),
        *(["【逐镜状态与机位硬合同】\n" + "\n".join(shot_state_locks)] if shot_state_locks else []),
        "【角色】\n" + "\n".join(role_rows),
        *( ["【失败后全量表演重写】" + reroll_directive + "；只改变本次重试的动作节拍、可见运动和对白演绎，不改变身份、服装、地图、天气、镜头类型、时长或对白文字。"] if reroll_directive else [] ),
        "【时间轴】\n" + "\n".join(timeline),
        "【摄影】" + camera,
        "【环境】" + (environment or "背景与群众只按剧情因果保持真实微动，不得冻结成静态图") + "。",
        "【声音】" + sound + (f"；{voices}" if voices else "") + "；禁止外加默认BGM，除非结构化音频模式明确绑定。",
        "【物理】" + "；".join(physical_rules) + "。" if physical_rules else "【物理】按时间轴完成真实动作因果。",
        "【限制】" + "；".join(dict.fromkeys(value.strip().rstrip("。；") for value in negatives if value.strip())) + "。",
    ]) + "\n"
    # Provider prose must not receive internal map/space identifiers.  Keep
    # those IDs in the structured execution contract and replace only their
    # human-facing prompt occurrences with scoped natural-language labels.
    text = _sanitize_provider_ids(text)
    boundary = validate_provider_prompt_boundary(text, source_id=uid, model_family="SEEDANCE_2")
    if boundary["status"] != "PASS":
        raise ValueError(";".join(boundary["failures"]))
    clause_evidence = {
        "ANCHOR.IDENTITY_PROP": _sanitize_provider_ids(plan["identity_prop_fact"]),
        "ANCHOR.SPACE_WEATHER": _sanitize_provider_ids(plan["space_weather_fact"]),
        "CAMERA.PLAN": camera,
    }
    if state_lock:
        clause_evidence["CONTINUITY.PERSISTENT_STATE"] = state_lock
    if content_window:
        clause_evidence["PACING.CONTENT_WINDOW"] = content_window
    for index, value in enumerate(shot_state_locks, 1):
        clause_evidence[f"CONTINUITY.SHOT_STATE.{index}"] = value
    if plan.get("interaction_topology_required"):
        clause_evidence["PHYSICAL.INTERACTION_TOPOLOGY"] = physical_rules[0]
    if plan.get("combat_execution_required"):
        clause_evidence["COMBAT.EXECUTION_RULE"] = next(
            value for value in physical_rules if value.startswith("打斗按起势与位移")
        )
    if wuxia_profile.get("status") == "SELECTED":
        clause_evidence["COMBAT.WUXIA_PROFILE_MODULE"] = next(
            value for value in physical_rules if value.startswith("武侠动作镜头原型")
        )
    if transition.get("incoming"):
        clause_evidence["TRANSITION.INCOMING"] = transition["incoming"]
    if transition.get("outgoing"):
        clause_evidence["TRANSITION.OUTGOING"] = transition["outgoing"]
    if reroll_directive:
        clause_evidence["REROLL.PERFORMANCE_REWRITE"] = reroll_directive
    for index, beat in enumerate(action_beats, 1):
        prefix = f"BEAT.{index}"
        pace = delivery_clause(beat)
        if pace:
            clause_evidence[f"{prefix}.DIALOGUE_DELIVERY"] = pace
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
    for index, value in enumerate(role_rows, 1):
        clause_evidence[f"ROLE_BINDING.{index}"] = value
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
        "wuxia_combat_profile_selection": wuxia_profile,
        "motion_density_gate": plan["motion_density_gate"],
        "provider_semantic_coverage_receipt": coverage,
        "provider_boundary": boundary,
        "prompt_budget": measure_prompt(text, source_id=uid, model_family="SEEDANCE_2"),
    }
