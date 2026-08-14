#!/usr/bin/env python3
"""Validate that scene and camera continuity are chosen per authored shot."""

from __future__ import annotations

import re
from typing import Any


SAME_SPACE = "SAME_SPACE_CONTINUOUS"
CROSS_SPACE = "CROSS_SPACE_TRANSITION"
MODES = {SAME_SPACE, CROSS_SPACE}

SAME_SPACE_LOCK = re.compile(
    r"保持(?:同一?|原)(?:场景|空间|机位)|同一(?:场景|空间|机位)|"
    r"same[- ]?(?:scene|space|camera)|keep the same (?:scene|space|camera)",
    re.IGNORECASE,
)
CROSS_SPACE_ACTION = re.compile(
    r"跨空间|跨地点|转场|抵达|到达|穿窗|掠向|掠过.*(?:城|街|楼)|"
    r"进入新|落到.*(?:窗外|屋顶|楼外)|cross[- ]?location|arriv(?:e|es|al)",
    re.IGNORECASE,
)


def _prompt(task: dict[str, Any]) -> str:
    return str(task.get("compiled_prompt") or task.get("prompt") or "")


def evaluate_task(task: dict[str, Any], prompt_text: str | None = None) -> dict[str, Any]:
    contract = (task.get("prompt_contract") or {}).get("spatial_continuity")
    contract = contract or task.get("spatial_continuity")
    failures: list[dict[str, Any]] = []
    if not isinstance(contract, dict):
        return {
            "task_key": task.get("task_key"),
            "status": "FAIL",
            "failures": [{"code": "MISSING_PER_SHOT_SPATIAL_CONTINUITY_CONTRACT"}],
        }

    mode = str(contract.get("mode") or "")
    if mode not in MODES:
        failures.append({"code": "INVALID_SPATIAL_CONTINUITY_MODE", "actual": mode or "MISSING"})
    if contract.get("policy_source") != "PER_UNIT_SCRIPT_CONTENT":
        failures.append({
            "code": "SPATIAL_POLICY_NOT_DERIVED_PER_UNIT",
            "actual": contract.get("policy_source") or "MISSING",
        })

    prompt = prompt_text if prompt_text is not None else _prompt(task)
    source_action = str((task.get("prompt_contract") or {}).get("source_action") or "")
    if mode == CROSS_SPACE:
        origin = str(contract.get("origin_scene_id") or "")
        destination = str(contract.get("destination_scene_id") or "")
        if not origin or not destination or origin == destination:
            failures.append({
                "code": "CROSS_SPACE_REQUIRES_DISTINCT_ORIGIN_AND_DESTINATION",
                "origin": origin or "MISSING",
                "destination": destination or "MISSING",
            })
        if SAME_SPACE_LOCK.search(prompt):
            failures.append({
                "code": "CROSS_SPACE_LOCKED_TO_ORIGIN_SCENE_OR_CAMERA",
                "message": "Cross-space shots must allow the authored scene and camera change.",
            })
        scope = str(contract.get("anchor_scope") or "")
        if scope == "DESTINATION_REANCHOR":
            destination_refs = [
                row for row in task.get("reference_bindings") or []
                if row.get("role") == "destination_scene"
                or (row.get("role") == "scene" and row.get("entity_id") == destination)
            ]
            if len(destination_refs) != 1:
                failures.append({"code": "CROSS_SPACE_DESTINATION_ANCHOR_MISSING"})
        elif scope == "ORIGIN_ONLY_WITH_DECLARED_DEPENDENT_DESTINATION":
            if not contract.get("destination_anchor_task_key"):
                failures.append({"code": "CROSS_SPACE_DEPENDENT_DESTINATION_NOT_DECLARED"})
        elif scope != "VIDEO_WITH_ORIGIN_AND_DESTINATION_ANCHORS":
            failures.append({"code": "INVALID_CROSS_SPACE_ANCHOR_SCOPE", "actual": scope or "MISSING"})
    elif mode == SAME_SPACE and CROSS_SPACE_ACTION.search(source_action):
        failures.append({
            "code": "AUTHORED_CROSS_SPACE_ACTION_MISCLASSIFIED_AS_SAME_SPACE",
            "source_action": source_action,
        })

    return {
        "task_key": task.get("task_key"),
        "status": "PASS" if not failures else "FAIL",
        "mode": mode,
        "failures": failures,
    }


def evaluate_batch(tasks: list[dict[str, Any]], prompts: dict[str, str] | None = None) -> dict[str, Any]:
    prompts = prompts or {}
    results = [evaluate_task(task, prompts.get(str(task.get("task_key")))) for task in tasks]
    failures = [failure for result in results for failure in result["failures"]]
    return {
        "schema": "qingshan.shot_space_camera_constraint_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "results": results,
        "failures": failures,
        "rollback": "Change only the affected shot's spatial contract or destination anchor; preserve all admitted siblings.",
    }
