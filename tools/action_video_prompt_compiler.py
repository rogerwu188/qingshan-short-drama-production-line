#!/usr/bin/env python3
"""Compile video prompts from one structured blocking/trajectory fact source."""

from __future__ import annotations

import json
from typing import Any


CONTRACT_VERSION = "2.0.0"
COMBAT_TYPES = {"COMBAT", "FIGHT", "ACTION_COMBAT"}


def _shot_type(task: dict[str, Any]) -> str:
    return str(task.get("shot_type") or task.get("shot_class") or "GENERAL").upper()


def _number(value: Any, default: float = 999.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _validate_combat_contract(task: dict[str, Any], failures: list[str]) -> None:
    tempo = task.get("performance_tempo_contract") or {}
    duration = task.get("duration_seconds") or task.get("duration")
    if not isinstance(duration, (int, float)) or not 8 <= float(duration) <= 15:
        failures.append("COMBAT_GENERATION_DURATION_MUST_BE_8_TO_15_SECONDS")
    if _number(tempo.get("contact_by_seconds")) > 0.2:
        failures.append("COMBAT_CONTACT_MUST_BEGIN_BY_0P2_SECONDS")
    if _number(tempo.get("primary_exchange_complete_by_seconds")) > 1.5:
        failures.append("COMBAT_PRIMARY_EXCHANGE_MUST_COMPLETE_BY_1P5_SECONDS")
    if tempo.get("aftermath_in_same_edit_shot") is not False:
        failures.append("COMBAT_AFTERMATH_HOLD_FORBIDDEN_IN_SAME_EDIT_SHOT")
    exchanges = tempo.get("exchange_plan") or []
    if not 3 <= len(exchanges) <= 4:
        failures.append("COMBAT_GENERATION_REQUIRES_3_TO_4_EXCHANGES")
    cut_plan = task.get("cut_plan") or []
    if not 4 <= len(cut_plan) <= 6:
        failures.append("COMBAT_GENERATION_REQUIRES_4_TO_6_EDITORIAL_CUTS")
    breathing = task.get("fight_scene_breathing_contract") or {}
    rounds = breathing.get("rounds") or []
    if len(rounds) < 3:
        failures.append("FIGHT_BREATHING_STRUCTURE_REQUIRES_3_ROUNDS")
    for index, row in enumerate(rounds):
        burst = row.get("burst_seconds")
        buildup = row.get("buildup_seconds")
        if not isinstance(burst, (int, float)) or not 2 <= float(burst) <= 4:
            failures.append(f"FIGHT_BURST_DURATION_INVALID:{index}")
        if not isinstance(buildup, (int, float)) or not 1 <= float(buildup) <= 2:
            failures.append(f"FIGHT_BUILDUP_DURATION_INVALID:{index}")
        if _number(row.get("burst_motion_per_second"), 0) < 10:
            failures.append(f"FIGHT_BURST_MOTION_BELOW_10:{index}")


def _ids(block: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for row in block.get("characters") or []:
        if row.get("character_id"):
            values.add(str(row["character_id"]))
    for row in block.get("props") or []:
        if row.get("prop_id"):
            values.add(str(row["prop_id"]))
    return values


def validate_action_contract(task: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    start = task.get("blocking") or {}
    end = task.get("action_end_blocking") or {}
    trajectories = task.get("trajectory_overlays") or []
    if not start:
        failures.append("ACTION_START_BLOCKING_MISSING")
    if not end:
        failures.append("ACTION_END_BLOCKING_MISSING")
    if not trajectories:
        failures.append("ACTION_TRAJECTORY_MISSING")
    canonical = {
        *map(str, task.get("canonical_characters") or []),
        *map(str, task.get("canonical_props") or []),
    }
    represented = _ids(start) | _ids(end)
    missing = sorted(canonical - represented)
    if missing:
        failures.append("CANONICAL_ENTITY_ABSENT_FROM_ACTION_STATE:" + ",".join(missing))
    for index, row in enumerate(trajectories):
        entity_id = str(row.get("entity_id") or "")
        if not entity_id:
            failures.append(f"TRAJECTORY_ENTITY_MISSING:{index}")
        elif entity_id not in canonical:
            failures.append(f"TRAJECTORY_ENTITY_NOT_CANONICAL:{entity_id}")
        for field in ("from", "to", "action", "visible_consequence"):
            if not row.get(field):
                failures.append(f"TRAJECTORY_FIELD_MISSING:{index}:{field}")
    chain = str(task.get("space_chain_id") or "")
    if chain.count("->") < 2:
        failures.append("SPACE_CHAIN_INCOMPLETE")
    windows = (task.get("performance_tempo_contract") or {}).get("atomic_action_windows") or []
    if not windows:
        failures.append("ACTION_TIME_WINDOWS_MISSING")
    if _shot_type(task) in COMBAT_TYPES:
        _validate_combat_contract(task, failures)
    return failures


def compile_action_video_prompt(task: dict[str, Any]) -> str:
    failures = validate_action_contract(task)
    if failures:
        raise ValueError(";".join(failures))
    tempo = task["performance_tempo_contract"]
    windows = "；".join(
        f"{row['start_seconds']:.1f}—{row['end_seconds']:.1f}秒：{row['action']}"
        for row in tempo["atomic_action_windows"]
    )
    trajectory_text = "；".join(
        f"{row['entity_id']}从{row['from']}到{row['to']}，{row['action']}，可见后果={row['visible_consequence']}"
        for row in task["trajectory_overlays"]
    )
    forbidden = "、".join(map(str, task.get("forbidden_generation") or []))
    combat = ""
    if _shot_type(task) in COMBAT_TYPES:
        exchanges = "；".join(str(row.get("action") or row) for row in tempo["exchange_plan"])
        combat = (
            "本单元是供剪辑拆分的连续打斗表演，不是一个慢镜头：0.2秒内发生接触，"
            "1.5秒内完成第一回合并在动作击中瞬间切点；随后连续编排3至4个攻防回合，"
            f"回合={exchanges}；成片从本段拆成4至6个短镜，余震交给下一镜，不在同一剪辑镜头停站喘气。"
        )
    return (
        "以输入图片作为不可改写的第一帧。"
        f"空间继承链={task['space_chain_id']}；固定机位={task.get('camera_contract') or '保持首帧机位与轴线'}。"
        f"起始状态={json.dumps(task['blocking'], ensure_ascii=False, separators=(',', ':'))}；"
        f"动作轨迹={trajectory_text}；"
        f"动作终态={json.dumps(task['action_end_blocking'], ensure_ascii=False, separators=(',', ':'))}。"
        f"按真实1倍速度执行：{windows}。"
        f"{combat}"
        "动作必须遵守起点、路径、接触、物理后果和终态的唯一因果，不得用气氛、慢动作或镜头切换替代动作。"
        f"严格禁止：{forbidden or '新增或复制人物和道具、身份漂移、空间跳变、字幕、文字、LOGO、水印'}。"
    )
