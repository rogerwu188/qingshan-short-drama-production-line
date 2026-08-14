#!/usr/bin/env python3
"""Plan and validate story-driven 4-15 second video generation durations."""

from __future__ import annotations

import math
import re
from typing import Any


POLICY_VERSION = "qingshan.shot_generation_duration.v5"
MIN_SECONDS = 4
MAX_SECONDS = 15
PACE_CHARS_PER_SECOND = {"fast": 4.2, "medium": 3.6, "slow": 3.0}

ACTION_FUNCTION_TERMS = (
    "动作",
    "授权",
    "开棺",
    "推进",
    "检查",
    "报告",
    "引入",
    "确认",
    "合成",
    "判断",
    "揭示",
    "解释",
    "锁定",
    "排除",
    "交付",
    "转为",
    "形成",
    "指定",
    "翻转",
)
TURN_FUNCTION_TERMS = (
    "反转",
    "钩子",
    "破绽",
    "异常",
    "矛盾",
    "敏感",
    "压力",
    "反客为主",
    "翻转",
)
ACTION_WORDS = (
    "turn",
    "move",
    "step",
    "reach",
    "open",
    "close",
    "lift",
    "lower",
    "push",
    "pull",
    "cross",
    "reveal",
    "react",
    "withdraw",
    "hold",
    "enter",
    "exit",
    "转身",
    "移动",
    "上前",
    "伸手",
    "打开",
    "合上",
    "抬起",
    "放下",
    "推开",
    "拉开",
    "揭示",
    "反应",
    "退开",
    "露出",
    "放出",
    "夺路",
    "扑空",
    "走向",
    "停下",
    "走近",
    "逼近",
    "亮出",
    "指向",
    "观察",
    "停顿",
    "对视",
    "扑向",
    "撞翻",
    "逃入",
    "追出",
    "叼起",
    "回头",
    "跟随",
    "拍上",
    "推进",
    "翻窗",
    "拖柜",
    "封门",
    "布下",
    "垂索",
    "突入",
    "格刀",
    "护住",
    "擒腕",
    "复现",
    "比较",
    "格挡",
    "锁住",
    "截住",
    "换位",
    "撞窗",
    "翻墙",
    "踏碎",
    "越檐",
    "举火",
    "滑跪",
    "压下",
)


def han_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def action_cue_count(text: str) -> int:
    """Count explicit cues without treating English substrings as whole actions."""
    count = 0
    for word in ACTION_WORDS:
        if re.search(r"[A-Za-z]", word):
            count += bool(re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE))
        else:
            count += word in text
    return int(count)


def plan_dialogue_duration(
    text: str,
    pace: str,
    narrative_function: str,
    *,
    explicit_action_seconds: float | None = None,
    performance_context: str = "",
) -> dict[str, Any]:
    """Return a per-shot duration plan; the tool minimum is a floor, not an edit unit."""
    chars = han_count(text)
    rate = PACE_CHARS_PER_SECOND.get(pace, PACE_CHARS_PER_SECOND["medium"])
    speech = max(0.7, chars / rate)
    combined_context = f"{narrative_function} {performance_context}".lower()
    action_count = action_cue_count(combined_context)
    inferred_action = 1.0 + min(5.0, action_count * 0.55)
    action = inferred_action if explicit_action_seconds is None else explicit_action_seconds
    if any(term in narrative_function for term in ACTION_FUNCTION_TERMS):
        action += 0.9
    reaction = 0.65
    if any(term in narrative_function for term in TURN_FUNCTION_TERMS):
        reaction += 0.65
    if pace == "slow":
        reaction += 0.35
    if any(mark in text for mark in ("，", "——", "…")):
        reaction += 0.35

    raw = speech + action + reaction
    # Duration follows playable speech and action. Context may add action budget,
    # but it must never create an unrelated 8/10/12-second floor.
    performance_floor = MIN_SECONDS
    duration = max(MIN_SECONDS, min(MAX_SECONDS, math.ceil(raw)))
    floor_applied = duration == MIN_SECONDS and raw < MIN_SECONDS
    return {
        "policy": POLICY_VERSION,
        "duration_seconds": duration,
        "speech_seconds_estimate": round(speech, 3),
        "action_seconds": round(action, 3),
        "reaction_or_button_seconds": round(reaction, 3),
        "context_actions_detected": action_count,
        "performance_floor_seconds": performance_floor,
        "raw_seconds": round(raw, 3),
        "tool_minimum_floor_applied": floor_applied,
        "edit_policy": "End at the natural speech/action result; do not add holds, slow motion, or filler to reach a prior target.",
        "rationale": (
            f"{chars} Han characters at {pace} pace plus "
            f"{action:.2f}s action and {reaction:.2f}s reaction/button coverage; "
            f"{action_count} explicit performance cues contribute only their estimated playable action budget."
        ),
    }


def plan_action_duration(
    action_summary: str,
    narrative_function: str,
    *,
    requested_floor: int = MIN_SECONDS,
) -> dict[str, Any]:
    combined = f"{action_summary} {narrative_function}".lower()
    action_count = action_cue_count(combined)
    action = 1.8 + min(4.8, action_count * 0.65)
    reaction = 0.8
    if any(term.lower() in combined for term in ("hook", "button", "reveal", "反转", "钩子", "揭示")):
        reaction += 0.8
    raw = action + reaction
    duration = max(MIN_SECONDS, requested_floor, min(MAX_SECONDS, math.ceil(raw)))
    return {
        "policy": POLICY_VERSION,
        "duration_seconds": duration,
        "speech_seconds_estimate": 0.0,
        "action_seconds": round(action, 3),
        "reaction_or_button_seconds": round(reaction, 3),
        "raw_seconds": round(raw, 3),
        "tool_minimum_floor_applied": duration == MIN_SECONDS and raw < MIN_SECONDS,
        "edit_policy": "Generate the complete physical action, then trim to the action delta and motivated reaction boundary in AgentCut.",
        "rationale": f"{action_count} explicit action cues plus the shot's narrative function; existing requested floor={requested_floor}s.",
    }


def validate_duration_task(task: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    source_id = task.get("source_id") or task.get("dialogue_id") or "unknown"
    duration = task.get("duration")
    plan = task.get("duration_plan")
    if not isinstance(duration, (int, float)) or not MIN_SECONDS <= duration <= MAX_SECONDS:
        problems.append(f"FAIL_SHOT_DURATION_RANGE:{source_id}:{duration}")
    if not isinstance(plan, dict):
        problems.append(f"FAIL_SHOT_DURATION_PLAN_MISSING:{source_id}")
        return problems
    if plan.get("policy") != POLICY_VERSION:
        problems.append(f"FAIL_SHOT_DURATION_POLICY_VERSION:{source_id}")
    if plan.get("duration_seconds") != duration:
        problems.append(f"FAIL_SHOT_DURATION_PLAN_MISMATCH:{source_id}")
    if not str(plan.get("rationale", "")).strip():
        problems.append(f"FAIL_SHOT_DURATION_RATIONALE_MISSING:{source_id}")
    if not str(plan.get("edit_policy", "")).strip():
        problems.append(f"FAIL_SHOT_DURATION_EDIT_POLICY_MISSING:{source_id}")
    return problems
