#!/usr/bin/env python3
"""Stateful-prop ownership and visibility rules for generated video beats."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


REQUIRED_FIELDS = ("owner", "hand", "position", "disposition")


def compile_prop_states(spec: dict[str, Any], *, source_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    failures: list[str] = []
    states: list[dict[str, Any]] = []
    action_kind = str((spec.get("action") or {}).get("action_kind") or "").upper()
    for index, prop in enumerate(spec.get("props") or [], 1):
        prop_id = str(prop.get("prop_id") or prop.get("prop") or f"PROP_{index}")
        state = prop.get("state") or prop.get("prop_state") or {}
        entry = deepcopy(state.get("entry") or prop.get("entry_state") or {})
        exit_state = deepcopy(state.get("exit") or prop.get("exit_state") or {})
        if not entry or not exit_state:
            failures.append(f"PROP_STATE_MISSING:{source_id}:{prop_id}")
            continue
        for endpoint, values in (("ENTRY", entry), ("EXIT", exit_state)):
            missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
            if missing:
                failures.append(f"PROP_STATE_FIELDS_MISSING:{source_id}:{prop_id}:{endpoint}:{','.join(missing)}")
        ownership_changed = any(entry.get(field) != exit_state.get(field) for field in ("owner", "hand", "disposition"))
        authorization = prop.get("transition_authorization") or state.get("transition_authorization") or {}
        if ownership_changed and authorization.get("writer_authored") is not True:
            failures.append(f"PROP_OWNERSHIP_CHANGE_NOT_WRITER_AUTHORED:{source_id}:{prop_id}")
        if action_kind == "DIALOGUE" and ownership_changed and authorization.get("writer_authored") is not True:
            failures.append(f"DIALOGUE_PROP_OWNERSHIP_CHANGE_FORBIDDEN:{source_id}:{prop_id}")
        visual = prop.get("start_frame_visual_confirmation") or state.get("start_frame_visual_confirmation") or {}
        if visual.get("status") != "PASS" or not visual.get("evidence_ref"):
            failures.append(f"START_FRAME_PROP_STATE_NOT_VISUALLY_CONFIRMED:{source_id}:{prop_id}")
        states.append({
            "prop_id": prop_id,
            "entry": entry,
            "exit": exit_state,
            "ownership_changed": ownership_changed,
            "transition_authorization": deepcopy(authorization),
            "start_frame_visual_confirmation": deepcopy(visual),
        })
    return states, failures
