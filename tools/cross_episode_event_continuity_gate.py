#!/usr/bin/env python3
"""Protect the first scene from silently flattening an unresolved prior event."""

from __future__ import annotations

from typing import Any


RELATIONS = {"CONTINUING", "RESOLVED", "ELAPSED"}
STATIC_CLASSES = {"STATIC", "TABLEAU", "QUEUE", "POSE_HOLD", "ATMOSPHERE"}


def evaluate(first_scene: dict[str, Any]) -> dict[str, Any]:
    relation = str(first_scene.get("prior_episode_event_relation") or "").upper()
    motion_class = str(first_scene.get("event_motion_class") or "").upper()
    failures: list[str] = []
    if relation not in RELATIONS:
        failures.append(f"PRIOR_EPISODE_EVENT_RELATION_INVALID:{relation or 'MISSING'}")
    if relation == "CONTINUING":
        if motion_class in STATIC_CLASSES or not motion_class:
            failures.append(f"CONTINUING_EVENT_DEGRADED_TO_STATIC:{motion_class or 'MISSING'}")
        if not str(first_scene.get("writer_authored_continuation_action") or "").strip():
            failures.append("CONTINUING_EVENT_WRITER_ACTION_MISSING")
    return {
        "schema": "qingshan.cross_episode_event_continuity_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "relation": relation,
        "event_motion_class": motion_class,
        "failures": failures,
        "rule": "CONTINUING must remain an active writer-authored event; only RESOLVED or ELAPSED may open statically.",
    }
