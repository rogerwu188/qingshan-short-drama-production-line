#!/usr/bin/env python3
"""Model-neutral physical continuity and combat prompt contracts.

These rules sit before the H3/Seedance serializers.  They prevent a grouped
semantic unit from losing its combat classification and make body/prop
ownership explicit whenever an action crosses an occlusion boundary.
"""

from __future__ import annotations

from typing import Any

try:
    from tools.combat_action_library import compile_binding_prompt, validate_binding
except ModuleNotFoundError:
    from combat_action_library import compile_binding_prompt, validate_binding


COMBAT_CUES = (
    "fight", "combat", "attack", "strike", "lunge", "stab", "slash", "grapple",
    "counter", "parry", "block", "choke", "knife", "blade", "punch", "kick",
    "打斗", "战斗", "交手", "袭击", "攻击", "搏斗", "短刀", "刀尖", "刀刃",
    "直刺", "斩", "劈", "挥刀", "格挡", "拦截", "反击", "擒拿", "掐喉",
    "锁喉", "捏住", "夺刀", "拳", "踢", "踹", "扑向", "压制", "制服",
)
CONTACT_CUES = (
    "hand", "finger", "wrist", "arm", "elbow", "shoulder", "foot", "leg",
    "grip", "touch", "press", "push", "pull", "hold", "latch", "door", "wall",
    "手", "指", "腕", "臂", "肘", "肩", "脚", "腿", "抓", "握", "按", "推",
    "拉", "抬", "捏", "碰", "接触", "门", "门闩", "门板", "墙", "桌", "柜",
    "刀", "剑", "杯", "碗", "道具",
)


def unit_text(unit: dict[str, Any]) -> str:
    parts = [
        unit.get("shot_purpose"), unit.get("narrative_beat"),
        unit.get("narrative_function"), unit.get("prompt"), unit.get("prompt_text"),
    ]
    for spec in unit.get("ordered_prompt_specs") or []:
        action = spec.get("action") or {}
        parts.extend(action.get(key) for key in (
            "start_state", "primary_action", "completion_state", "contact_point",
        ))
        parts.append(spec.get("dialogue"))
        choreography = spec.get("combat_choreography") or spec.get("combat_choreography_contract")
        parts.append(choreography)
    return " ".join(str(value) for value in parts if value).lower()


def is_combat_unit(unit: dict[str, Any]) -> bool:
    if str(unit.get("combat_classification_override") or "").upper() == "NON_COMBAT_SOURCE_AUTHORITY":
        return False
    explicit = (
        unit.get("fight_or_chase") is True
        or unit.get("combat_or_chase") is True
        or bool(unit.get("combat_choreography_contract"))
        or str(unit.get("action_classification") or "").upper() in {
            "COMBAT", "FIGHT", "ACTION_COMBAT", "SET_PIECE_COMBAT",
        }
        or str(unit.get("shot_type") or "").upper() in {
            "COMBAT", "FIGHT", "ACTION_COMBAT", "SET_PIECE_COMBAT",
        }
    )
    if explicit:
        return True
    # Current structured writers classify every beat.  Once that authority is
    # present, do not let substring heuristics turn ordinary prose such as
    # “劈开的水膜” into combat.  Text cues remain only as a fail-safe for
    # legacy/unclassified manifests.
    action_kinds = [
        str((spec.get("action") or {}).get("action_kind") or "").strip().upper()
        for spec in unit.get("ordered_prompt_specs") or []
    ]
    declared = [value for value in action_kinds if value]
    if declared and len(declared) == len(action_kinds):
        return any(value == "COMBAT" for value in declared)
    return any(cue in unit_text(unit) for cue in COMBAT_CUES)


def requires_interaction_topology(unit: dict[str, Any]) -> bool:
    return is_combat_unit(unit) or any(cue in unit_text(unit) for cue in CONTACT_CUES)


def enrich_unit_contract(unit: dict[str, Any]) -> dict[str, Any]:
    """Attach deterministic classification/locks before either model compiles."""
    combat = is_combat_unit(unit)
    topology = requires_interaction_topology(unit)
    unit["action_classification"] = "COMBAT" if combat else str(
        unit.get("action_classification") or "GENERAL_PERFORMANCE"
    )
    unit["combat_or_chase"] = combat
    unit["fight_or_chase"] = combat
    unit["interaction_topology_contract"] = {
        "schema": "qingshan.interaction_topology_contract.v1",
        "required": topology,
        "continuous_limb_ownership": topology,
        "fixed_surface_penetration_forbidden": topology,
        "single_contact_point_and_force_feedback": topology,
    }
    tempo = unit.setdefault("performance_tempo_contract", {})
    if combat:
        tempo["continuous_real_time_combat"] = True
        tempo["tableau_or_pose_slideshow_forbidden"] = True
        tempo["maximum_result_hold_seconds"] = 0.5
    return unit


def interaction_topology_prompt_block(unit: dict[str, Any]) -> str:
    if not requires_interaction_topology(unit):
        return ""
    return (
        "肢体与接触拓扑硬锁：每一只可见手都必须归属于画面内具名角色，并由该角色的肩→上臂→肘→前臂→腕→手掌→手指"
        "形成连续、自然、数量唯一的解剖链；脚腿同样必须从髋部连续连接。手、脚、武器和道具不得从门板、墙体、桌柜、衣物或"
        "画外凭空长出，不得穿透固定物，不得多肢、断肢、反关节或交换主人。发生接触时必须先看见发力者和运动路径，再发生唯一"
        "接触点，随后出现符合受力方向的反馈与结果；遮挡只能暂时遮住连续肢体，不能改变其主人、侧别、数量或空间路径。只要手掌"
        "仍在画内，主人躯干以及肩到手的完整链条必须同时在构图内可追溯，不得在肩、肘或腕处被画框、门框、柱子、家具、动物或前景"
        "物裁断成孤立手臂；如果镜头切到猫、道具或环境特写，人物手臂必须整体退出画面，不能只留下画外伸入的前臂或手掌。"
    )


def combat_prompt_block(unit: dict[str, Any], *, model_family: str) -> str:
    if not is_combat_unit(unit):
        return ""
    model_clause = (
        "H3只生成一段连续实时动作，不把参考图之间的姿势当作静态幻灯片，也不在每个节拍停住摆姿势"
        if model_family == "minimax-h3"
        else "Seedance按既定打斗镜头语言执行连续实时动作，不用慢动作、定格或姿势插帧替代攻防"
    )
    choreography = unit.get("combat_choreography_contract") or {}
    role_and_force_rows: list[str] = []
    if choreography:
        initiator = str(choreography.get("initiator") or "").strip()
        objective = str(choreography.get("objective") or "").strip()
        spatial_axis = str(choreography.get("spatial_axis") or "").strip()
        if initiator or objective or spatial_axis:
            role_and_force_rows.append(
                f"本场唯一初始发起者={initiator or '按逐拍合同'}；任务动作={objective or '按逐拍合同'}；"
                f"空间与受力轴={spatial_axis or '按逐拍合同'}"
            )
        for index, beat in enumerate(choreography.get("causal_beats") or [], 1):
            role_and_force_rows.append(
                f"物理第{index}拍：发力或攻击={beat.get('attack_intent')}；"
                f"防守或受力反应={beat.get('defense_response')}；"
                f"可见后果={beat.get('visible_consequence')}；新站位={beat.get('end_state')}"
            )
        terminal = choreography.get("terminal_state") or {}
        if terminal:
            role_and_force_rows.append(
                f"终局锁：胜者={terminal.get('winner')}；败者={terminal.get('loser')}；"
                f"物理结果={terminal.get('physical_result')}"
            )
    library_block = compile_binding_prompt(unit, model_family=model_family)
    positive_execution = "。".join(role_and_force_rows)
    return (
        "打斗镜头语言硬合同：每次攻防必须按蓄势/位移→出招轨迹→唯一接触或明确闪避→受力反馈→新站位连续完成；"
        "攻击者、目标、武器主人、左右手、落脚点、力的方向和可见后果逐拍唯一。镜头服务于读清动作因果：优先同轴跟随、短促横移"
        "或由动作触发的明确切镜，不使用无动机慢推、漂移或同方向重复运镜。每拍保持实时1倍速并立即推进下一拍，只有全段末尾可留"
        f"不超过0.5秒的自然呼吸、衣料惯性和环境余波；{model_clause}。同期保留脚步、衣料、兵器破风、接触和环境受力声。"
        + (f"剧情专属物理链：{positive_execution}。" if positive_execution else "")
        + (library_block if library_block else "")
    )


def validate_physical_prompt_binding(
    text: str, unit: dict[str, Any], *, model_family: str
) -> dict[str, Any]:
    failures: list[str] = []
    topology = interaction_topology_prompt_block(unit)
    combat = combat_prompt_block(unit, model_family=model_family)
    if topology and text.count(topology) != 1:
        failures.append("INTERACTION_TOPOLOGY_PROMPT_NOT_EXACTLY_ONCE")
    if combat and text.count(combat) != 1:
        failures.append("COMBAT_CAMERA_LANGUAGE_PROMPT_NOT_EXACTLY_ONCE")
    library_report = validate_binding(unit)
    if combat and library_report["status"] == "NOT_BOUND":
        failures.append("COMBAT_ACTION_LIBRARY_BINDING_REQUIRED")
    elif library_report["status"] == "FAIL":
        failures.extend(library_report["failures"])
    elif library_report["status"] == "PASS":
        library_text = compile_binding_prompt(unit, model_family=model_family)
        if text.count(library_text) != 1:
            failures.append("COMBAT_ACTION_LIBRARY_PROMPT_NOT_EXACTLY_ONCE")
    return {
        "schema": "qingshan.video_physical_continuity_prompt_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "combat_unit": bool(combat),
        "interaction_topology_required": bool(topology),
        "combat_action_library_binding": library_report,
        "failures": failures,
    }
