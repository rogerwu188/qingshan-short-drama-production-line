#!/usr/bin/env python3
"""Deterministically compile structured generation contracts into prompts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


BEGIN = "【自动优化契约开始】"
END = "【自动优化契约结束】"
ROOT = Path(__file__).resolve().parents[1]


def _without_previous_block(prompt: str) -> str:
    if BEGIN not in prompt:
        return prompt.rstrip()
    before, remainder = prompt.split(BEGIN, 1)
    if END not in remainder:
        return before.rstrip()
    _, after = remainder.split(END, 1)
    return (before.rstrip() + "\n" + after.lstrip()).rstrip()


def _percent(value: Any) -> int:
    return round(float(value) * 100)


def _action_signature(task: dict[str, Any]) -> str:
    beats = (task.get("performance_spec") or {}).get("motion_beats") or []
    if not beats:
        return ""
    beat = beats[0]
    return "|".join(str(beat.get(key) or "").strip() for key in ("subject", "action", "contact_point", "direction", "end_state"))


def _prompt_contract_failures(task: dict[str, Any], prompt: str) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    key = str(task.get("task_key") or task.get("source_id") or "unknown")
    prop = task.get("action_prop_function_contract") or {}
    if prop:
        required_class = str(prop.get("required_function_class") or "")
        forbidden_classes = [str(value) for value in prop.get("forbidden_function_classes") or []]
        for term in prop.get("required_prompt_terms") or []:
            if str(term) not in prompt:
                failures.append({"task_key": key, "code": "PROP_FUNCTION_REQUIRED_TERM_MISSING", "term": str(term)})
        for term in prop.get("forbidden_prompt_terms") or []:
            if str(term) in prompt:
                failures.append({"task_key": key, "code": "PROP_FUNCTION_CLASS_REWRITTEN", "term": str(term)})
        if not required_class:
            failures.append({"task_key": key, "code": "PROP_FUNCTION_CLASS_MISSING"})
        if not forbidden_classes:
            failures.append({"task_key": key, "code": "PROP_FUNCTION_FORBIDDEN_CLASSES_MISSING"})
    causality = task.get("action_causality_contract") or {}
    if causality:
        phases = [str(value) for value in causality.get("visible_phases") or []]
        if not phases or len(phases) > int(causality.get("maximum_phases_per_shot", 1)):
            failures.append({"task_key": key, "code": "ACTION_PHASE_BUDGET_EXCEEDED"})
        for term in causality.get("required_prompt_terms") or []:
            if str(term) not in prompt:
                failures.append({"task_key": key, "code": "ACTION_CAUSALITY_TERM_MISSING", "term": str(term)})
    scale = task.get("action_scale_contract") or {}
    if scale:
        for term in scale.get("required_relational_terms") or []:
            if str(term) not in prompt:
                failures.append({"task_key": key, "code": "RELATIONAL_SCALE_TERM_MISSING", "term": str(term)})
        if scale.get("frame_ratio_is_secondary_check") is not True:
            failures.append({"task_key": key, "code": "FRAME_RATIO_USED_WITHOUT_RELATIONAL_SCALE"})
    lanes = task.get("action_movement_lane_contract") or {}
    if lanes:
        if len(lanes.get("lanes") or []) < 2:
            failures.append({"task_key": key, "code": "MULTI_ACTOR_MOVEMENT_LANES_MISSING"})
        if not lanes.get("minimum_lateral_clearance"):
            failures.append({"task_key": key, "code": "MOVEMENT_LANE_CLEARANCE_MISSING"})
        for term in lanes.get("required_prompt_terms") or []:
            if str(term) not in prompt:
                failures.append({"task_key": key, "code": "MOVEMENT_LANE_TERM_MISSING", "term": str(term)})
        for term in lanes.get("forbidden_prompt_terms") or []:
            if str(term) in prompt:
                failures.append({"task_key": key, "code": "MOVEMENT_LANE_OVERLAP_AUTHORED", "term": str(term)})
    support = task.get("action_terminal_support_contract") or {}
    if support:
        if support.get("result_hold_requires_stable_support") is not True:
            failures.append({"task_key": key, "code": "TERMINAL_STABLE_SUPPORT_NOT_REQUIRED"})
        for term in support.get("required_prompt_terms") or []:
            if str(term) not in prompt:
                failures.append({"task_key": key, "code": "TERMINAL_SUPPORT_TERM_MISSING", "term": str(term)})
        for term in support.get("forbidden_prompt_terms") or []:
            if str(term) in prompt:
                failures.append({"task_key": key, "code": "SUSPENDED_TERMINAL_POSE_AUTHORED", "term": str(term)})
    return failures


def optimize_prompt(task: dict[str, Any], prompt: str, prior_tasks: list[dict[str, Any]] | None = None) -> tuple[str, dict[str, Any]]:
    """Return an idempotently optimized prompt and auditable rule receipt."""
    base = _without_previous_block(prompt)
    clauses: list[str] = []
    applied_rules: list[str] = []
    prior_tasks = prior_tasks or []
    tempo = task.get("performance_tempo_contract") or {}
    if tempo:
        clauses.append(
            f"【PF-004实时动作】动作以REAL_TIME_1X完成，主接触最迟在{tempo.get('primary_action_complete_by_seconds')}秒完成，"
            f"终态只读{tempo.get('result_hold_seconds')}秒；不得慢放、复位、重演或靠运镜填时长。"
        )
        applied_rules.append("PF-004")
    sequence = task.get("action_sequence_contract") or {}
    if sequence:
        clauses.append(
            f"【PF-008/PF-009因果交接】首帧严格为入口状态{sequence.get('entry_state_token')}；只完成一个主接触；"
            f"尾帧严格落在{sequence.get('exit_state_token')}，且可直接作为下一镜首帧，不得复位或偷跑下一事件。"
        )
        applied_rules.extend(["PF-008", "PF-009"])
    ownership = task.get("action_actor_ownership_contract") or {}
    if ownership:
        forbidden = "、".join(ownership.get("forbidden_foreground_actions") or [])
        clauses.append(
            f"【PF-010能力归属】唯一动作所有者为{ownership.get('ability_owner')}；"
            f"继承前景人物{ownership.get('inherited_foreground_actor')}不得{forbidden}；特效必须从所有者可见接触点起始。"
        )
        applied_rules.append("PF-010")
    spatial = task.get("action_spatial_feasibility_contract") or {}
    if spatial:
        corridor = spatial["collision_corridor"]
        effect = spatial["effect_geometry"]
        effect_label = str(effect.get("label") or "动作主体")
        clauses.append(
            "【PF-011首尾帧动作空间】开放碰撞通道为画幅"
            f"横向{_percent(corridor['x_min'])}%至{_percent(corridor['x_max'])}%、纵向{_percent(corridor['y_min'])}%至{_percent(corridor['y_max'])}%；"
            "保护道具和非接触肢体不得进入通道。"
            f"特效位于{effect.get('depth_order')}深度层，平面方向{effect.get('plane_orientation')}，"
            f"{effect_label}宽不超过画幅{_percent(effect['max_width_ratio'])}%，{effect_label}高不超过画幅{_percent(effect['max_height_ratio'])}%，"
            f"人物遮挡不超过{_percent(spatial['maximum_subject_occlusion_ratio'])}%。"
            "先发生唯一身体接触，再出现裂纹、白汽或其他反馈；尾帧保留保护道具、明确人物落点，并保持下一镜可执行姿态。"
        )
        applied_rules.append("PF-011")
    prop = task.get("action_prop_function_contract") or {}
    if prop:
        clauses.append(
            f"【PF-013道具功能类别】本镜道具必须保持{prop.get('required_function_class')}；"
            f"禁止改写成{'、'.join(str(value) for value in prop.get('forbidden_function_classes') or [])}。"
            "尺寸修正只能在原功能类别内完成，不得以缩小、四边显形或手持化偷换道具类别。"
        )
        applied_rules.append("PF-013")
    causality = task.get("action_causality_contract") or {}
    if causality:
        clauses.append(
            "【PF-014动作相位】本镜只表现"
            + "、".join(str(value) for value in causality.get("visible_phases") or [])
            + "；不得把后续接触、受力或结果提前塞入本镜，尾帧必须为下一相位提供可执行姿态。"
        )
        applied_rules.append("PF-014")
    scale = task.get("action_scale_contract") or {}
    if scale:
        clauses.append(
            "【PF-015关系尺度】先按"
            + "、".join(str(value) for value in scale.get("required_relational_terms") or [])
            + "建立真实人体与建筑尺度；画幅比例仅作二次验算，不能覆盖道具的空间功能。"
        )
        applied_rules.append("PF-015")
    lanes = task.get("action_movement_lane_contract") or {}
    if lanes:
        lane_text = "；".join(
            f"{row.get('actor')}只沿{row.get('corridor')}"
            for row in lanes.get("lanes") or []
        )
        clauses.append(
            f"【PF-016运动走廊】{lane_text}；全程保持{lanes.get('minimum_lateral_clearance')}。"
            "人物躯干轮廓不得交叠、穿模或融合；若通道相交，必须先拆成不同生成镜头。"
        )
        applied_rules.append("PF-016")
    support = task.get("action_terminal_support_contract") or {}
    if support:
        clauses.append(
            "【PF-017终态支撑】结果停留必须落在"
            + "、".join(str(value) for value in support.get("required_support_points") or [])
            + "的重力稳定姿态；禁止把迈步、腾空或单脚悬空的过渡姿态拉长为尾态。"
        )
        applied_rules.append("PF-017")
    prior_action_tasks = [row for row in prior_tasks if row.get("action_sequence_contract")]
    if task.get("action_sequence_contract") and prior_action_tasks:
        completed = [str((row.get("action_sequence_contract") or {}).get("exit_state_token") or "") for row in prior_action_tasks]
        clauses.append("【PF-012历史动作去重】已完成的关联动作画面为：" + "、".join(completed) + "。本镜不得重演这些接触、反馈或终态，只能从最近尾帧继续当前唯一动作。")
        applied_rules.append("PF-012")
    optimized = base
    if clauses:
        optimized += "\n" + BEGIN + "\n" + "\n".join(clauses) + "\n" + END + "\n"
    before_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    after_sha = hashlib.sha256(optimized.encode("utf-8")).hexdigest()
    return optimized, {
        "schema": "qingshan.generation_prompt_optimizer_receipt.v1",
        "task_key": task.get("task_key"),
        "status": "PASS",
        "applied_failure_memory_rules": list(dict.fromkeys(applied_rules)),
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        "changed": before_sha != after_sha,
        "idempotent_block": True,
        "prior_action_task_keys": [row.get("task_key") for row in prior_action_tasks],
        "action_signature": _action_signature(task),
    }


def validate_batch(tasks: list[dict[str, Any]], prompts: dict[str, str]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    seen_signatures: dict[str, str] = {}
    prior_action_keys: list[str] = []
    for task in tasks:
        if task.get("prompt_optimizer_required") is not True:
            continue
        key = str(task.get("task_key") or task.get("source_id") or "unknown")
        receipt = task.get("prompt_optimizer_receipt") or {}
        prompt = prompts.get(key, "")
        actual_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if receipt.get("status") != "PASS":
            failures.append({"task_key": key, "code": "PROMPT_OPTIMIZER_NOT_RUN"})
        if receipt.get("after_sha256") != actual_sha:
            failures.append({"task_key": key, "code": "OPTIMIZED_PROMPT_SHA_MISMATCH"})
        expected = {"PF-004", "PF-008", "PF-009"} if task.get("action_sequence_contract") else set()
        if task.get("action_actor_ownership_contract"):
            expected.add("PF-010")
        if task.get("action_spatial_feasibility_contract"):
            expected.add("PF-011")
        if task.get("action_prop_function_contract"):
            expected.add("PF-013")
        if task.get("action_causality_contract"):
            expected.add("PF-014")
        if task.get("action_scale_contract"):
            expected.add("PF-015")
        if task.get("action_movement_lane_contract"):
            expected.add("PF-016")
        if task.get("action_terminal_support_contract"):
            expected.add("PF-017")
        if task.get("action_sequence_contract") and prior_action_keys:
            expected.add("PF-012")
        actual = set(receipt.get("applied_failure_memory_rules") or [])
        if not expected.issubset(actual):
            failures.append({"task_key": key, "code": "REQUIRED_OPTIMIZATION_RULE_MISSING"})
        if expected and (BEGIN not in prompt or END not in prompt):
            failures.append({"task_key": key, "code": "OPTIMIZED_CONTRACT_BLOCK_MISSING"})
        failures.extend(_prompt_contract_failures(task, prompt))
        material = task.get("period_entity_material_contract") or {}
        if material:
            if material.get("status") != "PASS_PRECOMPILED" or material.get("hard_fail_override") is not True:
                failures.append({"task_key": key, "code": "PERIOD_ENTITY_MATERIAL_CONTRACT_NOT_LOCKED"})
            for term in material.get("required_prompt_terms") or []:
                if str(term) not in prompt:
                    failures.append({"task_key": key, "code": "PERIOD_ENTITY_POSITIVE_TERM_MISSING", "term": str(term)})
            for term in material.get("required_negative_prompt_terms") or []:
                if str(term) not in prompt:
                    failures.append({"task_key": key, "code": "PERIOD_ENTITY_NEGATIVE_TERM_MISSING", "term": str(term)})
            reference = ROOT / str(material.get("terminal_reference") or "")
            expected_reference_sha = str(material.get("terminal_reference_sha256") or "")
            if not reference.is_file() or not expected_reference_sha:
                failures.append({"task_key": key, "code": "PERIOD_ENTITY_REFERENCE_MISSING"})
            elif hashlib.sha256(reference.read_bytes()).hexdigest() != expected_reference_sha:
                failures.append({"task_key": key, "code": "PERIOD_ENTITY_REFERENCE_SHA_MISMATCH"})
        signature = _action_signature(task)
        if signature and signature in seen_signatures:
            failures.append({"task_key": key, "code": "ACTION_VISUAL_DUPLICATES_PRIOR_SHOT"})
        if signature:
            seen_signatures[signature] = key
        if task.get("action_sequence_contract"):
            if receipt.get("prior_action_task_keys") != prior_action_keys:
                failures.append({"task_key": key, "code": "PRIOR_ACTION_PROMPTS_NOT_FULLY_READ"})
            prior_action_keys.append(key)
    return {"schema": "qingshan.generation_prompt_optimizer_gate.v1", "status": "PASS" if not failures else "FAIL", "fail_closed": True, "failures": failures}
