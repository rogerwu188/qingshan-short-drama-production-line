#!/usr/bin/env python3
"""Validate that a video prompt has playable action across its full duration."""

from __future__ import annotations

import math
from typing import Any


POLICY_VERSION = "qingshan.video_prompt_action_density.v1"
MAX_SEGMENT_SECONDS = 3.0
PLACEHOLDER_PHRASES = (
    "稳定站位",
    "保持站位",
    "缓慢推进",
    "缓慢推镜",
    "静止等待",
    "保持不动",
    "stable stance",
    "hold position",
    "slow push",
    "slowly push",
    "wait in place",
    "手部、身体或道具",
    "动作主体离开上一接触点",
    "接触点、受力方向和动作主体",
    "衣摆、器物、灯影或雪粉",
    "产生不可逆的可见位移或结果",
)

REQUIRED_PHYSICAL_MARKERS = ("主体=", "动作=", "接触点=", "方向=", "终态=")


def validate_action_timeline(
    timeline: list[dict[str, Any]] | None,
    duration_seconds: float,
    *,
    source_id: str = "unknown",
    max_segment_seconds: float = MAX_SEGMENT_SECONDS,
) -> dict[str, Any]:
    failures: list[str] = []
    rows = timeline if isinstance(timeline, list) else []
    if not rows:
        failures.append(f"BLOCK_SUBMIT_ACTION_TIMELINE_MISSING:{source_id}")
        return {
            "policy": POLICY_VERSION,
            "status": "FAIL",
            "source_id": source_id,
            "duration_seconds": duration_seconds,
            "action_budget_seconds": 0.0,
            "failures": failures,
        }

    cursor = 0.0
    budget = 0.0
    for index, row in enumerate(rows, 1):
        start = row.get("start_seconds")
        end = row.get("end_seconds")
        actions = row.get("actions")
        state_change = str(row.get("state_change") or "").strip()
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            failures.append(f"BLOCK_SUBMIT_ACTION_SEGMENT_TIME_INVALID:{source_id}:{index}")
            continue
        start = float(start)
        end = float(end)
        segment_duration = end - start
        if not math.isclose(start, cursor, abs_tol=0.01):
            failures.append(
                f"BLOCK_SUBMIT_ACTION_TIMELINE_GAP_OR_OVERLAP:{source_id}:{index}:{cursor:.3f}->{start:.3f}"
            )
        if segment_duration <= 0:
            failures.append(f"BLOCK_SUBMIT_ACTION_SEGMENT_DURATION_INVALID:{source_id}:{index}")
        if segment_duration > max_segment_seconds + 0.01:
            failures.append(
                f"BLOCK_SUBMIT_ACTION_SEGMENT_TOO_LONG:{source_id}:{index}:{segment_duration:.3f}"
            )
        action_text = "；".join(str(item).strip() for item in actions or [] if str(item).strip())
        if not action_text:
            failures.append(f"BLOCK_SUBMIT_ACTION_SEGMENT_EMPTY:{source_id}:{index}")
        for marker in REQUIRED_PHYSICAL_MARKERS:
            if marker not in action_text:
                failures.append(f"BLOCK_SUBMIT_ACTION_PHYSICS_FIELD_MISSING:{source_id}:{index}:{marker}")
        lowered = f"{action_text} {state_change}".lower()
        for phrase in PLACEHOLDER_PHRASES:
            if phrase.lower() in lowered:
                failures.append(f"BLOCK_SUBMIT_ACTION_PLACEHOLDER:{source_id}:{index}:{phrase}")
        if not state_change:
            failures.append(f"BLOCK_SUBMIT_STATE_CHANGE_MISSING:{source_id}:{index}")
        row_budget = row.get("action_budget_seconds", segment_duration)
        if not isinstance(row_budget, (int, float)) or float(row_budget) <= 0:
            failures.append(f"BLOCK_SUBMIT_ACTION_BUDGET_INVALID:{source_id}:{index}")
        else:
            budget += float(row_budget)
        cursor = end

    if not math.isclose(cursor, float(duration_seconds), abs_tol=0.01):
        failures.append(
            f"BLOCK_SUBMIT_ACTION_TIMELINE_DURATION_MISMATCH:{source_id}:{cursor:.3f}!={float(duration_seconds):.3f}"
        )
    if float(duration_seconds) > budget + 0.01:
        failures.append(
            f"BLOCK_SUBMIT_DURATION_EXCEEDS_ACTION_BUDGET:{source_id}:{float(duration_seconds):.3f}>{budget:.3f}"
        )
    return {
        "policy": POLICY_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id,
        "duration_seconds": float(duration_seconds),
        "segment_count": len(rows),
        "max_segment_seconds": max_segment_seconds,
        "action_budget_seconds": round(budget, 3),
        "failures": failures,
    }


def require_action_timeline(
    timeline: list[dict[str, Any]] | None,
    duration_seconds: float,
    *,
    source_id: str,
) -> dict[str, Any]:
    report = validate_action_timeline(timeline, duration_seconds, source_id=source_id)
    if report["status"] != "PASS":
        raise ValueError(";".join(report["failures"]))
    return report
