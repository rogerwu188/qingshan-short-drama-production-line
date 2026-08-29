#!/usr/bin/env python3
"""Prevent atomic actions from being stretched into model-generated slow motion."""

from __future__ import annotations

from pathlib import Path
from typing import Any


ACTION_CUES = (
    "fight", "combat", "attack", "lunge", "intercept", "strike", "punch",
    "kick", "landing", "breach", "chase", "grapple", "restrain",
    "打斗", "战斗", "攻击", "冲刺", "扑击", "拦截", "击打", "拳", "踢",
    "落地", "破门", "追逐", "制服", "擒拿",
)
FIGHT_PURPOSE_CUES = ("fight", "combat", "chase", "breach", "打斗", "战斗", "追逐", "破门")
MAX_FIGHT_ONSET_SECONDS = 0.5
MAX_ATOMIC_BEAT_SECONDS = 2.0
MAX_FIGHT_BEAT_SECONDS = 1.2
MAX_ACTION_IDLE_GAP_SECONDS = 0.25
MAX_GROUPED_EDITORIAL_BEAT_SECONDS = 3.0
COMBAT_TYPES = {"COMBAT", "FIGHT", "ACTION_COMBAT"}
DIALOGUE_TYPES = {"DIALOGUE", "DIALOGUE_PERFORMANCE", "REACTION_DIALOGUE", "EMOTIONAL_DIALOGUE"}


def _prompt_text(task: dict[str, Any]) -> str:
    parts = [task.get("shot_purpose"), task.get("narrative_function"), task.get("prompt"), task.get("prompt_text")]
    prompt_file = task.get("prompt_file")
    if prompt_file:
        path = Path(str(prompt_file))
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return " ".join(str(part) for part in parts if part).lower()


def _looks_like_action(task: dict[str, Any], text: str) -> bool:
    shot_type = str(task.get("shot_type") or "").upper()
    if shot_type in DIALOGUE_TYPES and task.get("action_unit") is not True:
        return False
    if task.get("action_unit") is True:
        return True
    if any(task.get(name) for name in ("combat_choreography_contract", "action_sequence_contract", "action_timeline", "performance_tempo_contract")):
        return True
    return any(cue in text for cue in ACTION_CUES)


def _fight_or_chase(text: str, task: dict[str, Any]) -> bool:
    return bool(task.get("combat_choreography_contract")) or any(cue in text for cue in FIGHT_PURPOSE_CUES)


def _evaluate_atomic_windows(key: str, contract: dict[str, Any], *, fight_or_chase: bool) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    windows = contract.get("atomic_action_windows")
    if not isinstance(windows, list) or not windows:
        return [{"code": "ATOMIC_ACTION_WINDOWS_MISSING", "task_key": key}]
    first_start: float | None = None
    previous_end = 0.0
    maximum = MAX_FIGHT_BEAT_SECONDS if fight_or_chase else MAX_ATOMIC_BEAT_SECONDS
    for index, window in enumerate(windows, 1):
        if not isinstance(window, dict):
            failures.append({"code": "ATOMIC_ACTION_WINDOW_INVALID", "task_key": key, "index": index})
            continue
        try:
            start = float(window["start_seconds"])
            end = float(window["end_seconds"])
        except (KeyError, TypeError, ValueError):
            failures.append({"code": "ATOMIC_ACTION_WINDOW_INVALID", "task_key": key, "index": index})
            continue
        if first_start is None:
            first_start = start
        if start < 0.0 or end <= start:
            failures.append({"code": "ATOMIC_ACTION_WINDOW_INVALID", "task_key": key, "index": index})
            continue
        if start < previous_end - 0.01:
            failures.append({"code": "ATOMIC_ACTION_WINDOWS_OVERLAP", "task_key": key, "index": index})
        if start - previous_end > MAX_ACTION_IDLE_GAP_SECONDS:
            failures.append({"code": "ACTION_IDLE_GAP_INVITES_SLOW_MOTION", "task_key": key, "index": index, "gap_seconds": round(start - previous_end, 3)})
        span = end - start
        if span > maximum + 0.01:
            failures.append({"code": "ATOMIC_ACTION_WINDOW_TOO_LONG", "task_key": key, "index": index, "action": window.get("action"), "actual_seconds": round(span, 3), "maximum_seconds": maximum})
        previous_end = max(previous_end, end)
    if fight_or_chase and first_start is not None and first_start > MAX_FIGHT_ONSET_SECONDS:
        failures.append({"code": "FIGHT_ACTION_ONSET_TOO_LATE", "task_key": key, "actual_seconds": first_start, "maximum_seconds": MAX_FIGHT_ONSET_SECONDS})
    return failures


def evaluate_batch(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    rows, failures = [], []
    for task in tasks:
        text = _prompt_text(task)
        if not _looks_like_action(task, text):
            continue
        key = str(task.get("task_key") or "UNKNOWN")
        duration = float(task.get("duration_seconds") or task.get("duration") or 0.0)
        contract = task.get("performance_tempo_contract") or {}
        fight_or_chase = _fight_or_chase(text, task)
        structured_combat = str(task.get("shot_type") or "").upper() in COMBAT_TYPES
        rows.append({"task_key": key, "duration_seconds": duration, "fight_or_chase": fight_or_chase, "contract": contract})
        if task.get("action_unit") is not True:
            failures.append({"code": "ACTION_UNIT_CLASSIFICATION_MISSING", "task_key": key})
        if not contract:
            failures.append({"code": "ACTION_TEMPO_CONTRACT_MISSING", "task_key": key})
            continue
        if contract.get("playback_speed") != "REAL_TIME_1X":
            failures.append({"code": "ACTION_NOT_AUTHORED_AT_REAL_TIME", "task_key": key})
        if task.get("semantic_video_unit") is True:
            if not 3.0 <= duration <= 12.0:
                failures.append({"code": "GROUPED_VIDEO_UNIT_DURATION_INVALID", "task_key": key, "actual_seconds": duration})
            windows = contract.get("atomic_action_windows") or []
            if not windows:
                failures.append({"code": "GROUPED_EDITORIAL_BEAT_WINDOWS_MISSING", "task_key": key})
                continue
            previous_end = 0.0
            for index, window in enumerate(windows, 1):
                try:
                    start = float(window["start_seconds"])
                    end = float(window["end_seconds"])
                except (KeyError, TypeError, ValueError):
                    failures.append({"code": "GROUPED_EDITORIAL_BEAT_WINDOW_INVALID", "task_key": key, "index": index})
                    continue
                if start < previous_end - 0.01 or start - previous_end > MAX_ACTION_IDLE_GAP_SECONDS:
                    failures.append({"code": "GROUPED_EDITORIAL_BEAT_SEQUENCE_GAP_OR_OVERLAP", "task_key": key, "index": index})
                if end <= start or end - start > MAX_GROUPED_EDITORIAL_BEAT_SECONDS + 0.01:
                    failures.append({"code": "GROUPED_EDITORIAL_BEAT_DURATION_INVALID", "task_key": key, "index": index, "actual_seconds": round(end - start, 3)})
                previous_end = max(previous_end, end)
            if int(contract.get("grouped_editorial_beat_count") or 0) != len(windows):
                failures.append({"code": "GROUPED_EDITORIAL_BEAT_COUNT_MISMATCH", "task_key": key})
            continue
        if structured_combat:
            first_exchange = float(contract.get("primary_exchange_complete_by_seconds") or 0.0)
            if first_exchange <= 0.0 or first_exchange > 1.5:
                failures.append({"code": "COMBAT_PRIMARY_EXCHANGE_WINDOW_INVALID", "task_key": key, "actual_seconds": first_exchange, "maximum_seconds": 1.5})
            if duration < 8.0 or duration > 15.0:
                failures.append({"code": "COMBAT_GENERATION_DURATION_INVALID", "task_key": key, "actual_seconds": duration, "minimum_seconds": 8.0, "maximum_seconds": 15.0})
            if contract.get("aftermath_in_same_edit_shot") is not False:
                failures.append({"code": "COMBAT_AFTERMATH_HOLD_FORBIDDEN", "task_key": key})
        else:
            max_action = float(contract.get("primary_action_complete_by_seconds") or 0.0)
            if max_action <= 0.0 or max_action > 2.0:
                failures.append({"code": "ATOMIC_ACTION_COMPLETION_WINDOW_INVALID", "task_key": key, "actual_seconds": max_action, "maximum_seconds": 2.0})
            if duration > 4.0:
                failures.append({"code": "ATOMIC_ACTION_DURATION_INVITES_SLOW_MOTION", "task_key": key, "actual_seconds": duration, "maximum_seconds": 4.0})
            if float(contract.get("result_hold_seconds") or 0.0) > 0.75:
                failures.append({"code": "ACTION_RESULT_HOLD_TOO_LONG", "task_key": key})
        failures.extend(_evaluate_atomic_windows(key, contract, fight_or_chase=fight_or_chase))
    return {
        "schema": "qingshan.performance_tempo_gate.v2",
        "status": "PASS" if not failures else "FAIL",
        "rows": rows,
        "failures": failures,
        "policy": (
            "Action-like prompts cannot bypass classification. Atomic contact completes within 2.0s at real-time 1x; "
            "fight/chase beats complete within 1.2s and begin by 0.5s; non-combat atomic unit <=4.0s with result hold <=0.75s; "
            "structured combat uses the registered 8-15s multi-exchange generation contract while each fight beat remains <=1.2s."
        ),
    }
