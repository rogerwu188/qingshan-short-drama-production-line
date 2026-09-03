#!/usr/bin/env python3
"""Classify video-unit boundaries and enforce persistent state continuity.

Scene numbers are editorial labels, not evidence of a time/space/event break.
For E54+ every unit must carry a structured persistent-state ledger.  At a
continuous boundary the previous exit state must equal the next entry state,
unless a named, writer-authorized and visibly staged change is declared.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


POLICY = "opening_anchor_is_continuity_event_routed_v4"
BOUNDARY_CLASSES = {"HARD_CONTINUATION", "MOTIVATED_CUT", "NEW_EVENT_ANCHOR"}
CHARACTER_STATE_FIELDS = ("presence", "posture", "injury", "wardrobe", "position")
ENVIRONMENT_STATE_FIELDS = (
    "time", "weather", "lighting", "space_topology", "population", "ambient_life"
)
MOTIVATED_CUT_DEVICES = {
    "MOTIVATED_CUT", "GAZE_MATCH", "EYELINE_MATCH", "REACTION_CUT",
    "REVERSE_ANGLE", "INSERT", "MATCH_CUT", "NEW_SPACE_MATCH_CUT",
}
CAMERA_STATE_FIELDS = (
    "shot_scale", "camera_position_id", "axis_id", "lens_intent", "motion_family"
)


def episode_number(value: Any) -> int | None:
    match = re.search(r"(?:^|[^A-Z])E(\d+)", str(value or "").upper())
    return int(match.group(1)) if match else None


def strict_required(unit: dict[str, Any]) -> bool:
    number = episode_number(unit.get("episode") or unit.get("unit_id"))
    return bool(number is not None and number >= 54)


def _first_spec(unit: dict[str, Any]) -> dict[str, Any]:
    rows = unit.get("ordered_prompt_specs") or []
    return rows[0] if rows else {}


def _last_spec(unit: dict[str, Any]) -> dict[str, Any]:
    rows = unit.get("ordered_prompt_specs") or []
    return rows[-1] if rows else {}


def _space(unit: dict[str, Any], *, terminal: bool) -> dict[str, str]:
    transition = (
        unit.get("outgoing_transition_contract") if terminal
        else unit.get("incoming_transition_contract") or unit.get("transition_contract")
    ) or {}
    state = (
        transition.get("source_terminal_state") if terminal
        else transition.get("target_initial_state")
    ) or {}
    raw = state.get("space") or ((_last_spec(unit) if terminal else _first_spec(unit)).get("space") or {})
    return {key: str(raw.get(key) or "").strip() for key in ("global", "location", "subspace")}


def _time(unit: dict[str, Any], *, terminal: bool) -> str:
    spec = _last_spec(unit) if terminal else _first_spec(unit)
    return str((spec.get("scene_state") or {}).get("time") or "").strip()


def _camera_changed(previous: dict[str, Any], current: dict[str, Any], transition: dict[str, Any]) -> bool:
    left, right = previous.get("camera_plan") or {}, current.get("camera_plan") or {}
    keys = ("shot_scale", "camera_height", "camera_side", "start_framing", "motion_family", "motion_direction")
    if any(str(left.get(key) or "") != str(right.get(key) or "") for key in keys):
        return True
    return str(transition.get("transition_device") or "").upper() in MOTIVATED_CUT_DEVICES


def _state_rows(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in contract.get("characters") or []:
        entity = str(row.get("character_id") or row.get("entity_id") or row.get("character") or "").strip()
        if entity:
            rows[entity] = row
    return rows


def validate_persistent_state_contract(unit: dict[str, Any]) -> list[str]:
    uid = str(unit.get("unit_id") or "UNKNOWN")
    contract = unit.get("persistent_state_contract")
    if not isinstance(contract, dict):
        return [f"PERSISTENT_STATE_CONTRACT_MISSING:{uid}"]
    failures: list[str] = []
    if contract.get("status") != "PASS":
        failures.append(f"PERSISTENT_STATE_CONTRACT_NOT_PASS:{uid}")
    characters = contract.get("characters")
    if not isinstance(characters, list):
        failures.append(f"PERSISTENT_CHARACTER_STATES_MISSING:{uid}")
        characters = []
    tracked = {str(value) for value in contract.get("tracked_character_ids") or [] if str(value)}
    supplied: set[str] = set()
    for row in characters:
        entity = str(row.get("character_id") or row.get("entity_id") or row.get("character") or "").strip()
        if not entity:
            failures.append(f"PERSISTENT_CHARACTER_ID_MISSING:{uid}")
            continue
        supplied.add(entity)
        for side in ("entry_state", "exit_state"):
            state = row.get(side)
            if not isinstance(state, dict):
                failures.append(f"PERSISTENT_CHARACTER_{side.upper()}_MISSING:{uid}:{entity}")
                continue
            for field in CHARACTER_STATE_FIELDS:
                if state.get(field) in (None, ""):
                    failures.append(f"PERSISTENT_CHARACTER_FIELD_MISSING:{uid}:{entity}:{side}:{field}")
    if tracked - supplied:
        failures.append(f"TRACKED_CHARACTER_STATE_MISSING:{uid}:{','.join(sorted(tracked - supplied))}")
    if not tracked and not characters and not str(contract.get("no_character_state_reason") or "").strip():
        failures.append(f"PERSISTENT_CHARACTER_SCOPE_UNDECLARED:{uid}")
    environment = contract.get("environment")
    if not isinstance(environment, dict):
        failures.append(f"PERSISTENT_ENVIRONMENT_STATE_MISSING:{uid}")
    else:
        for side in ("entry_state", "exit_state"):
            state = environment.get(side)
            if not isinstance(state, dict):
                failures.append(f"PERSISTENT_ENVIRONMENT_{side.upper()}_MISSING:{uid}")
                continue
            for field in ENVIRONMENT_STATE_FIELDS:
                if state.get(field) in (None, ""):
                    failures.append(f"PERSISTENT_ENVIRONMENT_FIELD_MISSING:{uid}:{side}:{field}")
    return failures


def _authorized_changes(current: dict[str, Any]) -> set[str]:
    contract = current.get("persistent_state_contract") or {}
    return {
        str(row.get("path") or "").strip()
        for row in contract.get("authorized_boundary_changes") or []
        if row.get("writer_authorized") is True
        and str(row.get("visible_transition") or "").strip()
        and str(row.get("source_ref") or "").strip()
    }


def _compare_contracts(
    previous_contract: dict[str, Any], current_contract: dict[str, Any],
    *, uid: str, allowed: set[str],
) -> list[str]:
    failures: list[str] = []
    prev_rows, cur_rows = _state_rows(previous_contract), _state_rows(current_contract)
    for entity in sorted(set(prev_rows) | set(cur_rows)):
        left = (prev_rows.get(entity) or {}).get("exit_state") or {}
        right = (cur_rows.get(entity) or {}).get("entry_state") or {}
        for field in CHARACTER_STATE_FIELDS:
            path = f"characters.{entity}.{field}"
            if left.get(field) != right.get(field) and path not in allowed:
                failures.append(f"UNAUTHORIZED_PERSISTENT_CHARACTER_STATE_CHANGE:{uid}:{path}")
    left_env = ((previous_contract.get("environment") or {}).get("exit_state") or {})
    right_env = ((current_contract.get("environment") or {}).get("entry_state") or {})
    for field in ENVIRONMENT_STATE_FIELDS:
        path = f"environment.{field}"
        if left_env.get(field) != right_env.get(field) and path not in allowed:
            failures.append(f"UNAUTHORIZED_PERSISTENT_ENVIRONMENT_STATE_CHANGE:{uid}:{path}")
    return failures


def _compare_snapshots(
    left_contract: dict[str, Any], left_side: str,
    right_contract: dict[str, Any], right_side: str,
    *, uid: str, allowed: set[str] | None = None,
) -> list[str]:
    """Compare any two ledger snapshots, including unit-to-shot envelopes."""
    allowed = allowed or set()
    failures: list[str] = []
    left_rows, right_rows = _state_rows(left_contract), _state_rows(right_contract)
    for entity in sorted(set(left_rows) | set(right_rows)):
        left = (left_rows.get(entity) or {}).get(left_side) or {}
        right = (right_rows.get(entity) or {}).get(right_side) or {}
        for field in CHARACTER_STATE_FIELDS:
            path = f"characters.{entity}.{field}"
            if left.get(field) != right.get(field) and path not in allowed:
                failures.append(f"PERSISTENT_STATE_ENVELOPE_MISMATCH:{uid}:{path}")
    left_env = ((left_contract.get("environment") or {}).get(left_side) or {})
    right_env = ((right_contract.get("environment") or {}).get(right_side) or {})
    for field in ENVIRONMENT_STATE_FIELDS:
        path = f"environment.{field}"
        if left_env.get(field) != right_env.get(field) and path not in allowed:
            failures.append(f"PERSISTENT_STATE_ENVELOPE_MISMATCH:{uid}:{path}")
    return failures


def _camera_state_failures(row: dict[str, Any], *, uid: str) -> list[str]:
    camera = row.get("camera_state")
    if not isinstance(camera, dict):
        return [f"SHOT_CAMERA_STATE_MISSING:{uid}"]
    return [
        f"SHOT_CAMERA_FIELD_MISSING:{uid}:{field}"
        for field in CAMERA_STATE_FIELDS if camera.get(field) in (None, "")
    ]


def compare_persistent_states(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Compare the prior exit ledger with the current entry ledger."""
    return _compare_contracts(
        previous.get("persistent_state_contract") or {},
        current.get("persistent_state_contract") or {},
        uid=str(current.get("unit_id") or "UNKNOWN"),
        allowed=_authorized_changes(current),
    )


def compile_internal_shot_boundaries(unit: dict[str, Any]) -> dict[str, Any]:
    """Validate every editorial-shot boundary inside one generated video unit."""
    uid = str(unit.get("unit_id") or "UNKNOWN")
    if not strict_required(unit):
        return {"schema": "qingshan.internal_shot_state_chain.v1", "status": "NOT_APPLICABLE", "boundaries": [], "failures": []}
    shot_ids = [str(value) for value in unit.get("editorial_shot_ids") or []]
    rows = unit.get("shot_state_contracts")
    failures: list[str] = []
    if not isinstance(rows, list):
        return {
            "schema": "qingshan.internal_shot_state_chain.v1", "status": "FAIL",
            "boundaries": [], "failures": [f"SHOT_STATE_CONTRACTS_MISSING:{uid}"],
        }
    by_id = {str(row.get("shot_id") or ""): row for row in rows if isinstance(row, dict)}
    if set(by_id) != set(shot_ids):
        failures.append(f"SHOT_STATE_CONTRACT_COVERAGE_MISMATCH:{uid}")
    boundaries: list[dict[str, Any]] = []
    for shot_id in shot_ids:
        row = by_id.get(shot_id) or {}
        wrapped = {"unit_id": f"{uid}:{shot_id}", "persistent_state_contract": row.get("persistent_state_contract")}
        failures.extend(validate_persistent_state_contract(wrapped))
        failures.extend(_camera_state_failures(row, uid=f"{uid}:{shot_id}"))
    unit_contract = unit.get("persistent_state_contract") or {}
    if shot_ids:
        first_contract = (by_id.get(shot_ids[0]) or {}).get("persistent_state_contract") or {}
        last_contract = (by_id.get(shot_ids[-1]) or {}).get("persistent_state_contract") or {}
        failures.extend(_compare_snapshots(
            unit_contract, "entry_state", first_contract, "entry_state",
            uid=f"{uid}:UNIT_ENTRY->{shot_ids[0]}",
        ))
        failures.extend(_compare_snapshots(
            last_contract, "exit_state", unit_contract, "exit_state",
            uid=f"{uid}:{shot_ids[-1]}->UNIT_EXIT",
        ))
    internal_transitions = unit.get("internal_transition_contracts") or []
    for index in range(1, len(shot_ids)):
        left_id, right_id = shot_ids[index - 1], shot_ids[index]
        left = (by_id.get(left_id) or {}).get("persistent_state_contract") or {}
        right_row = by_id.get(right_id) or {}
        right = right_row.get("persistent_state_contract") or {}
        allowed = {
            str(change.get("path") or "").strip()
            for change in right.get("authorized_boundary_changes") or []
            if change.get("writer_authorized") is True
            and str(change.get("visible_transition") or "").strip()
            and str(change.get("source_ref") or "").strip()
        }
        boundary_failures = _compare_contracts(
            left, right, uid=f"{uid}:{left_id}->{right_id}", allowed=allowed
        )
        transition = internal_transitions[index - 1] if index - 1 < len(internal_transitions) else {}
        mode = str(transition.get("transition_mode") or "").upper()
        if not mode:
            boundary_failures.append(f"INTERNAL_SHOT_CAMERA_TRANSITION_UNDECLARED:{uid}:{left_id}->{right_id}")
        left_camera = (by_id.get(left_id) or {}).get("camera_state") or {}
        right_camera = right_row.get("camera_state") or {}
        camera_changed = any(left_camera.get(key) != right_camera.get(key) for key in CAMERA_STATE_FIELDS)
        motivated = mode in MOTIVATED_CUT_DEVICES
        motivation = str(
            transition.get("camera_change_reason")
            or transition.get("plot_motivation")
            or (transition.get("camera_bridge") or {}).get("transition_execution")
            or ""
        ).strip()
        if camera_changed and (not motivated or not motivation):
            boundary_failures.append(f"UNMOTIVATED_INTERNAL_CAMERA_CHANGE:{uid}:{left_id}->{right_id}")
        boundaries.append({
            "from_shot_id": left_id,
            "to_shot_id": right_id,
            "boundary_class": "MOTIVATED_CUT" if motivated else "HARD_CONTINUATION",
            "camera_transition_mode": mode,
            "camera_changed": camera_changed,
            "camera_change_reason": motivation,
            "state_inheritance_survives_camera_change": True,
            "status": "FAIL" if boundary_failures else "PASS",
            "failures": boundary_failures,
        })
        failures.extend(boundary_failures)
    return {
        "schema": "qingshan.internal_shot_state_chain.v1",
        "status": "FAIL" if failures else "PASS",
        "shot_count": len(shot_ids),
        "boundaries": boundaries,
        "failures": list(dict.fromkeys(failures)),
    }


def classify_boundary(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Return a state-first boundary and camera decision; never use scene id as proof."""
    uid = str(current.get("unit_id") or "UNKNOWN")
    state_failures = validate_persistent_state_contract(current) if strict_required(current) else []
    if previous is None:
        return {
            "schema": "qingshan.event_boundary_decision.v1",
            "status": "FAIL" if state_failures else "PASS",
            "boundary_class": "NEW_EVENT_ANCHOR",
            "opening_source": "NEW_EVENT_GENERATED_KEYFRAME",
            "previous_unit_id": None,
            "same_continuous_event": False,
            "scene_id_is_not_break_evidence": True,
            "camera_transition": {"change_required": False, "mode": "ESTABLISH_NEW_EVENT"},
            "persistent_state_contract": deepcopy(current.get("persistent_state_contract") or {}),
            "failures": state_failures,
        }
    transition = current.get("incoming_transition_contract") or current.get("transition_contract") or {}
    prev_space, cur_space = _space(previous, terminal=True), _space(current, terminal=False)
    prev_time, cur_time = _time(previous, terminal=True), _time(current, terminal=False)
    same_location = bool(prev_space["location"] and prev_space["location"] == cur_space["location"])
    same_time = bool(prev_time and prev_time == cur_time)
    explicit = current.get("event_boundary_contract") or transition.get("event_boundary_contract") or {}
    relation = str(explicit.get("relation_to_previous") or "").upper()
    explicit_break = relation in {"NEW_EVENT", "ELAPSED", "TIME_JUMP", "LOCATION_CHANGE"}
    legacy_same_scene = (
        not strict_required(current)
        and previous.get("scene_id") == current.get("scene_id")
    )
    same_event = relation in {"CONTINUING", "SAME_EVENT"} or (
        (same_location and same_time and not explicit_break) or legacy_same_scene
    )
    failures = [*state_failures]
    if explicit_break and same_location and same_time:
        authority = explicit.get("event_break_authority") or {}
        if not (authority.get("writer_authorized") is True and authority.get("source_ref") and authority.get("reason")):
            failures.append(f"FALSE_EVENT_BREAK_WITHOUT_AUTHORITY:{uid}")
    camera_changed = _camera_changed(previous, current, transition)
    if same_event:
        boundary_class = "MOTIVATED_CUT" if camera_changed else "HARD_CONTINUATION"
        opening_source = "CONTINUITY_DERIVED_KEYFRAME" if camera_changed else "PREVIOUS_UNIT_REAL_FINAL_FRAME"
        if camera_changed and strict_required(current):
            motivation = str(
                transition.get("camera_change_reason")
                or transition.get("plot_motivation")
                or (transition.get("camera_bridge") or {}).get("transition_execution")
                or ""
            ).strip()
            if not motivation:
                failures.append(f"UNMOTIVATED_VIDEO_UNIT_CAMERA_CHANGE:{uid}")
        failures.extend(validate_persistent_state_contract(previous) if strict_required(current) else [])
        failures.extend(compare_persistent_states(previous, current))
    else:
        boundary_class = "NEW_EVENT_ANCHOR"
        opening_source = "NEW_EVENT_GENERATED_KEYFRAME"
    if boundary_class not in BOUNDARY_CLASSES:
        failures.append(f"EVENT_BOUNDARY_CLASS_INVALID:{uid}")
    return {
        "schema": "qingshan.event_boundary_decision.v1",
        "status": "FAIL" if failures else "PASS",
        "boundary_class": boundary_class,
        "opening_source": opening_source,
        "previous_unit_id": previous.get("unit_id"),
        "same_continuous_event": same_event,
        "scene_id_changed": previous.get("scene_id") != current.get("scene_id"),
        "scene_id_is_not_break_evidence": True,
        "evidence": {
            "previous_space": prev_space, "current_space": cur_space,
            "previous_time": prev_time, "current_time": cur_time,
            "same_location": same_location, "same_time": same_time,
            "explicit_relation": relation or "INFERRED_FROM_STRUCTURED_TIME_SPACE_AND_TRANSITION",
        },
        "camera_transition": {
            "change_required": camera_changed,
            "mode": "STATE_PRESERVING_MOTIVATED_CUT" if camera_changed and same_event
                    else "PIXEL_CONTINUATION" if same_event else "ESTABLISH_NEW_EVENT",
            "state_inheritance_survives_camera_change": True,
        },
        "persistent_state_contract": deepcopy(current.get("persistent_state_contract") or {}),
        "failures": failures,
    }


def validate_task_boundary(task: dict[str, Any]) -> list[str]:
    if not strict_required(task):
        return []
    uid = str(task.get("unit_id") or task.get("task_key") or "UNKNOWN")
    decision = task.get("event_boundary_decision") or (task.get("machine_contract") or {}).get("event_boundary_decision")
    if not isinstance(decision, dict):
        return [f"EVENT_BOUNDARY_DECISION_MISSING:{uid}"]
    failures = list(decision.get("failures") or [])
    if decision.get("status") != "PASS":
        failures.append(f"EVENT_BOUNDARY_DECISION_NOT_PASS:{uid}")
    if decision.get("boundary_class") not in BOUNDARY_CLASSES:
        failures.append(f"EVENT_BOUNDARY_CLASS_INVALID:{uid}")
    failures.extend(validate_persistent_state_contract(task))
    internal = compile_internal_shot_boundaries(task)
    if internal.get("status") == "FAIL":
        failures.extend(internal.get("failures") or [])
    return list(dict.fromkeys(failures))


def provider_state_lock_text(plan: dict[str, Any], *, language: str) -> str:
    """Render the current entry ledger as a mandatory provider hard contract."""
    decision = plan.get("event_boundary_decision") or {}
    contract = plan.get("persistent_state_contract") or {}
    character_rows: list[str] = []
    for row in contract.get("characters") or []:
        entity = str(row.get("character_id") or row.get("entity_id") or row.get("character") or "UNKNOWN")
        state = row.get("entry_state") or {}
        values = ", ".join(f"{field}={state.get(field)}" for field in CHARACTER_STATE_FIELDS)
        character_rows.append(f"{entity}[{values}]")
    environment = ((contract.get("environment") or {}).get("entry_state") or {})
    environment_text = ", ".join(f"{field}={environment.get(field)}" for field in ENVIRONMENT_STATE_FIELDS)
    boundary = str(decision.get("boundary_class") or "UNDECLARED")
    camera_mode = str((decision.get("camera_transition") or {}).get("mode") or "UNDECLARED")
    if language.upper() == "ZH":
        return (
            f"边界类型={boundary}，镜头衔接={camera_mode}；人物持续状态="
            + ("；".join(character_rows) or "无人物，但已声明原因")
            + f"；环境持续状态={environment_text}；换镜头不得解除上述状态，只有合同内具名授权并在画面中完成的变化才允许发生"
        )
    return (
        f"boundary={boundary}; camera_transition={camera_mode}; persistent_characters="
        + ("; ".join(character_rows) or "none with declared reason")
        + f"; persistent_environment={environment_text}; a camera cut never resets these states; "
          "only named, source-authorized changes visibly staged on screen may alter them"
    )


def provider_shot_state_lock_texts(plan: dict[str, Any], *, language: str) -> list[str]:
    """Render per-editorial-shot state envelopes without weakening unit state."""
    result: list[str] = []
    for row in plan.get("shot_state_contracts") or []:
        shot_id = str(row.get("shot_id") or "UNKNOWN")
        contract = row.get("persistent_state_contract") or {}
        characters: list[str] = []
        for entity_row in contract.get("characters") or []:
            entity = str(entity_row.get("character_id") or entity_row.get("entity_id") or entity_row.get("character") or "UNKNOWN")
            entry, exit_state = entity_row.get("entry_state") or {}, entity_row.get("exit_state") or {}
            delta = [
                f"{field}:{entry.get(field)}->{exit_state.get(field)}"
                for field in CHARACTER_STATE_FIELDS
            ]
            characters.append(f"{entity}[{', '.join(delta)}]")
        env = contract.get("environment") or {}
        env_entry, env_exit = env.get("entry_state") or {}, env.get("exit_state") or {}
        env_delta = [
            f"{field}:{env_entry.get(field)}->{env_exit.get(field)}"
            for field in ENVIRONMENT_STATE_FIELDS
        ]
        camera = row.get("camera_state") or {}
        camera_text = ", ".join(f"{key}={camera.get(key)}" for key in CAMERA_STATE_FIELDS)
        if language.upper() == "ZH":
            result.append(
                f"{shot_id}：人物状态={'；'.join(characters) or '无人物'}；环境状态={', '.join(env_delta)}；摄影状态={camera_text}"
            )
        else:
            result.append(
                f"{shot_id}: character state={' ; '.join(characters) or 'none'}; environment state={', '.join(env_delta)}; camera state={camera_text}"
            )
    return result
