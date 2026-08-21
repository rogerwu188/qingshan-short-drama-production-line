#!/usr/bin/env python3
"""Compile video prompts from one structured blocking/trajectory fact source."""

from __future__ import annotations

import json
from typing import Any


CONTRACT_VERSION = "1.0.0"


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
    return (
        "以输入图片作为不可改写的第一帧。"
        f"空间继承链={task['space_chain_id']}；固定机位={task.get('camera_contract') or '保持首帧机位与轴线'}。"
        f"起始状态={json.dumps(task['blocking'], ensure_ascii=False, separators=(',', ':'))}；"
        f"动作轨迹={trajectory_text}；"
        f"动作终态={json.dumps(task['action_end_blocking'], ensure_ascii=False, separators=(',', ':'))}。"
        f"按真实1倍速度执行：{windows}。"
        "动作必须遵守起点、路径、接触、物理后果和终态的唯一因果，不得用气氛、慢动作或镜头切换替代动作。"
        f"严格禁止：{forbidden or '新增或复制人物和道具、身份漂移、空间跳变、字幕、文字、LOGO、水印'}。"
    )
