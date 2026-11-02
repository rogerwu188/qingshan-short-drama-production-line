#!/usr/bin/env python3
"""Cross-shot checks over the per-entity state ledger, plus what the viewer perceives.

Why this exists
---------------
The line owner asked (2026-11-01, item 4) that continuity be checked between shots on
two questions at once: does the STATE survive the cut, and does the audience SEE what
the ledger claims.  Two mechanisms already answer half of each and neither is compared
across shots:

  * ``tools/event_boundary_continuity_contract.py`` holds the per-entity persistent
    state ledger (presence / posture / injury / wardrobe / position + the environment
    block) and compares exit/entry snapshots, but only inside an episode that ships a
    ledger at all -- E11-E13 have none, E59 has 30/30 ledgers;
  * ``build_nalu_preproduction.build_transition`` writes a prose bridge between shots
    (``prop_bridge.ownership_or_handoff``, ``action_bridge``, ``cast_bridge``) that no
    consumer ever compares;
  * ``tools/continuity_state_contract_gate.py`` reads life state, head count, creature
    form and costume inheritance -- per entity across a whole episode, never
    per shot pair, and never about props, screen position or who a gaze addresses;
  * ``tools/prompt_scope_conflict_gate.py`` checks speaker/face/camera scope at send
    time; ``prompt_batch_qa.py`` checks verbatim presence in the prompt text.

So this module EXTENDS that state model instead of starting a second one.  It reads the
same ledger, from the same file the pipeline already consumes
(``preproduction/<EP>/shot_state_authoring.json``, schema
``qingshan.authored_shot_state_attachment.v1``), and adds five declared dimensions the
ledger did not carry:

    prop_holder        who holds prop X in this shot, or ON_GROUND / OFF_SCREEN /
                       NOT_PRESENT
    prop_pickup_state  HELD / PICKED_UP_IN_SHOT / PUT_DOWN_IN_SHOT / INHERITED
    action_repeat      the same action as the previous shot with no new state (NEW or
                       REPEAT + a reason)
    character_position screen slot + the eye-line target it addresses
    time_space         SAME_CONTINUOUS / DECLARED_TIME_JUMP / DECLARED_SCENE_CHANGE

They live in a ``perception_state`` block on the same authored shot record, beside the
``persistent_state_contract`` that is already there (see the vocabulary in
``tools/event_boundary_continuity_contract.py`` -- one definition, imported here).
A prop state declared only through the legacy ``persistent_state_contract.props`` map
is still read; anything the map cannot resolve is UNKNOWN, never a pass.

The six checks (one row per shot pair)
--------------------------------------
    PROP_HELD_WITHOUT_PICKUP        P1, a blocking CANDIDATE for the writer: held in
                                    shot N+1, the previous shot had it elsewhere and
                                    nothing between them picks it up.
    PROP_RETAKE_UNDECLARED          PUT_DOWN_IN_SHOT, later HELD again, no declared
                                    re-take.
    ACTION_REPEAT_WITHOUT_STATE_CHANGE
                                    identical action text and identical state across
                                    the pair: a MERGE proposal, not a defect.
    EYELINE_ADDRESSEE_NOT_IN_FRAME  a gaze addressed at a character while the shot
                                    declares nobody in frame.
    SCREEN_SLOT_CHANGED_WITHOUT_CUT a person moves across the frame with no cut to
                                    carry the move.
    TIME_SPACE_CHANGE_UNDECLARED    the pair crosses a location or a time and says
                                    SAME_CONTINUOUS.

Legal by construction (each has a test): an off-screen addressee with nobody in frame
(the target is a sentinel, not a character), over-the-shoulder occlusion (the target IS
on screen, just occluded), a declared jump cut, a declared time jump, a pickup staged on
screen (PICKED_UP_IN_SHOT), and a prop that is only mentioned in the action text.

PLANNED versus OBSERVED
-----------------------
Every report row carries ``planned`` (from the authored ledger/contract) and
``observed`` (from a real measurement, if one exists) separately.  No producer writes an
observation file today, so ``observed`` is normally ``UNKNOWN`` -- and a row whose state
is not declared is ``UNKNOWN`` too.  Neither is a failure and neither is a pass.

Never blocking by default
-------------------------
``configs/CROSS_SHOT_STATE_PERCEPTION_V1.json`` ships ``blocking: false``.  The checks
write a report and a writer-facing item list; whether a P1 stops a paid batch is the
line owner's switch.  The absence of the config file means report-only, never blocking.

Per pair, never per episode
---------------------------
``evaluate`` walks the shot order it is given, so a caller can hand it one unit's shots
and it stays parallel-safe: pure functions, no shared state, no write, results keyed by
shot pair.  Nothing here serialises unit generation.

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:  # the state vocabulary has exactly one definition
    from tools.event_boundary_continuity_contract import (
        ACTION_REPEAT_VALUES,
        MOTIVATED_CUT_DEVICES,
        CHARACTER_STATE_FIELDS,
        PERCEPTION_PROP_HOLDER_SENTINELS,
        PERCEPTION_TIME_SPACE_VALUES,
        PROP_PICKUP_STATES,
    )
except ModuleNotFoundError:  # pragma: no cover - bare tools/ on sys.path
    from event_boundary_continuity_contract import (  # type: ignore
        ACTION_REPEAT_VALUES,
        MOTIVATED_CUT_DEVICES,
        CHARACTER_STATE_FIELDS,
        PERCEPTION_PROP_HOLDER_SENTINELS,
        PERCEPTION_TIME_SPACE_VALUES,
        PROP_PICKUP_STATES,
    )

try:  # one action-text reading, shared with the S1 continuity gate
    from tools.continuity_state_contract_gate import _action_text
except ModuleNotFoundError:  # pragma: no cover
    try:
        from continuity_state_contract_gate import _action_text  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        def _action_text(shot: dict[str, Any]) -> str:
            spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
            action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
            return " ".join(
                part for part in (str(shot.get("blocking") or "").strip(),
                                  str(action.get("primary_action") or "").strip()) if part)


TOOL_ID = "cross_shot_state_perception.v1"
SCHEMA = "qingshan.cross_shot_state_perception.v1"
STATE_SCHEMA = "qingshan.authored_shot_state_attachment.v1"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs/CROSS_SHOT_STATE_PERCEPTION_V1.json"

UNKNOWN = "UNKNOWN"

#: transitions that carry an audience-visible edit.  A screen-slot change across one of
#: these is legal; across a continuous action it is a person teleporting.
CUT_DEVICES = set(MOTIVATED_CUT_DEVICES) | {
    "CUT", "HARD_CUT", "JUMP_CUT", "PAN_REVEAL", "OCCLUSION_REVEAL", "WHIP_PAN",
}

RULE_ORDER = (
    "PROP_HELD_WITHOUT_PICKUP",
    "PROP_RETAKE_UNDECLARED",
    "ACTION_REPEAT_WITHOUT_STATE_CHANGE",
    "EYELINE_ADDRESSEE_NOT_IN_FRAME",
    "SCREEN_SLOT_CHANGED_WITHOUT_CUT",
    "TIME_SPACE_CHANGE_UNDECLARED",
)

#: rule -> (severity, what the writer is looking at)
RULES: dict[str, dict[str, str]] = {
    "PROP_HELD_WITHOUT_PICKUP": {
        "severity": "P1", "kind": "BLOCKING_CANDIDATE",
        "question": "Who picks this up, in which shot, and does the audience see it?",
        "answer_options": ("ADD_PICKUP_SHOT_OR_BEAT", "MARK_INHERITED_FROM_PREVIOUS_SHOT",
                           "CORRECT_THE_LEDGER"),
    },
    "PROP_RETAKE_UNDECLARED": {
        "severity": "P2", "kind": "FLAG",
        "question": "It was put down; where is it taken up again?",
        "answer_options": ("DECLARE_THE_RETAKE_IN_A_SHOT", "STAGE_IT_ON_SCREEN",
                           "CORRECT_THE_LEDGER"),
    },
    "ACTION_REPEAT_WITHOUT_STATE_CHANGE": {
        "severity": "MERGE", "kind": "MERGE_PROPOSAL",
        "question": "Same action, same state twice: do these two shots earn their own cut?",
        "answer_options": ("MERGE_THE_PAIR", "GIVE_THE_SECOND_SHOT_NEW_STATE",
                           "DECLARE_REPEAT_WITH_A_REASON"),
    },
    "EYELINE_ADDRESSEE_NOT_IN_FRAME": {
        "severity": "P2", "kind": "CONTRADICTION",
        "question": "The gaze addresses someone the frame says is not there: who is in frame?",
        "answer_options": ("NAME_THE_ADDRESSEE_IN_FRAME", "MAKE_THE_TARGET_OFF_SCREEN",
                           "CORRECT_THE_LEDGER"),
    },
    "SCREEN_SLOT_CHANGED_WITHOUT_CUT": {
        "severity": "P2", "kind": "CONTRADICTION",
        "question": "This person changes side with no cut: which shot carries the move?",
        "answer_options": ("ADD_A_CUT_OR_A_MOVE_BEAT", "CORRECT_THE_SLOT"),
    },
    "TIME_SPACE_CHANGE_UNDECLARED": {
        "severity": "P2", "kind": "FLAG",
        "question": "This pair crosses a place or a time: is it declared?",
        "answer_options": ("DECLARE_TIME_JUMP", "DECLARE_SCENE_CHANGE", "CORRECT_THE_CONTRACT"),
    },
}


# --------------------------------------------------------------------------- config


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    candidate = Path(path or CONFIG_PATH)
    if not candidate.is_file():
        # fail CLOSED on the only thing that matters: no config means report-only.
        return {"schema": "qingshan.cross_shot_state_perception_config.v1",
                "blocking": False, "missing_config": True}
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": "qingshan.cross_shot_state_perception_config.v1",
                "blocking": False, "unreadable_config": True}


# --------------------------------------------------------------------------- state


def load_state(path: Path | str | None) -> dict[str, Any] | None:
    """The authored ledger, or None when the episode never declared one."""
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None
    try:
        state = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def state_records(state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    rows = (state or {}).get("shots") or []
    return {str(row.get("shot_id")): row for row in rows
            if isinstance(row, dict) and str(row.get("shot_id") or "").strip()}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _clean(value).upper()


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", _clean(value)).strip(" ，。；、,.;:")


def _rows(value: Any) -> list[dict[str, Any]]:
    """A list of rows, or an id-keyed map, as a list of rows."""
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        out: list[dict[str, Any]] = []
        for key, row in value.items():
            merged = dict(row) if isinstance(row, dict) else {"holder": row}
            merged.setdefault("prop_id", key)
            merged.setdefault("character_id", key)
            out.append(merged)
        return out
    return []


def _prop_holder(raw: Any, characters: set[str], *, strict: bool = True) -> str:
    """A declared holder, or UNKNOWN.

    In the perception block (``strict``) the holder must be a sentinel or an id the ledger
    itself declares, so a typo reads as UNKNOWN instead of as a different person.  The legacy
    ``persistent_state_contract.props`` map is untyped — the migrated E59 ledger writes bare
    holder strings there — so a non-sentinel value is taken verbatim as somebody's id.
    """
    value = _clean(raw)
    if not value:
        return UNKNOWN
    upper = value.upper()
    if upper in PERCEPTION_PROP_HOLDER_SENTINELS:
        return upper
    if value in characters or upper in characters:
        return value if value in characters else upper
    return value if not strict else UNKNOWN


def _screen_slot(raw: Any) -> str:
    """A declared slot, ON_SCREEN/IN_FRAME, or UNKNOWN.  Never guessed from a role."""
    value = _upper(raw)
    if not value:
        return UNKNOWN
    return value


def _off_screen(value: str) -> bool:
    return value != UNKNOWN and "OFFSCREEN" in value.replace("-", "_")


def shot_view(shot: dict[str, Any], record: dict[str, Any] | None) -> dict[str, Any]:
    """One shot's declared perception state, in the shape the rules read."""
    record = record or {}
    perception = record.get("perception_state") if isinstance(record.get("perception_state"), dict) else {}
    contract = record.get("persistent_state_contract") if isinstance(record.get("persistent_state_contract"), dict) else {}
    contract_chars = _rows(contract.get("characters"))
    character_ids = {_clean(row.get("character_id") or row.get("entity_id") or row.get("character"))
                     for row in contract_chars}
    character_ids |= {_clean(row.get("character_id")) for row in _rows(perception.get("characters"))}
    character_ids.discard("")

    # --- characters in frame, screen slot, eye-line target
    on_screen_raw = perception.get("on_screen")
    if isinstance(on_screen_raw, list):
        on_screen: Any = [_clean(value) for value in on_screen_raw if _clean(value)]
    else:
        on_screen = UNKNOWN
    positions: dict[str, dict[str, str]] = {}
    for row in _rows(perception.get("characters")):
        cid = _clean(row.get("character_id") or row.get("character") or row.get("entity_id"))
        if not cid:
            continue
        target = _clean(row.get("eyeline_target") or row.get("addressee"))
        positions[cid] = {
            "screen_slot": _screen_slot(row.get("screen_slot")),
            "eyeline_target": target,
            "eyeline_direction": _upper(row.get("eyeline_direction")),
            "occluded_by": _clean(row.get("occluded_by")),
            "occlusion": _upper(row.get("occlusion")),
        }

    # --- in frame: the declared on_screen list; without one, the slots say it
    if on_screen == UNKNOWN and positions:
        on_screen = sorted(cid for cid, row in positions.items() if not _off_screen(row["screen_slot"]))

    # --- props: the new block first, the legacy props map as a fallback
    props: dict[str, dict[str, Any]] = {}
    from_map = False
    legacy = contract.get("props") if isinstance(contract.get("props"), dict) else {}
    legacy_entry = legacy.get("entry_state") if isinstance(legacy.get("entry_state"), dict) else {}
    for prop_id, raw in legacy_entry.items():
        props[_clean(prop_id)] = {
            "holder": _prop_holder(raw, character_ids, strict=False),
            "pickup_state": UNKNOWN,
            "retake_source_ref": "",
            "declared_by": "persistent_state_contract.props",
        }
        from_map = True
    perception_props = _rows(perception.get("props"))
    for row in perception_props:
        prop_id = _clean(row.get("prop_id") or row.get("prop") or row.get("entity_id"))
        if not prop_id:
            continue
        props[prop_id] = {
            "holder": _prop_holder(row.get("holder") or row.get("holder_id"), character_ids),
            "pickup_state": _upper(row.get("pickup_state")) or UNKNOWN,
            "retake_source_ref": _clean(row.get("retake_source_ref") or row.get("source_ref")),
            "declared_by": "perception_state.props",
        }

    action_repeat = perception.get("action_repeat") if isinstance(perception.get("action_repeat"), dict) else {}
    jump_cut = bool(perception.get("jump_cut") is True
                    or (isinstance(perception.get("jump_cut"), dict)
                        and perception["jump_cut"].get("declared") is True))

    return {
        "shot_id": _clean(shot.get("shot_id")),
        "unit_id": _clean(shot.get("unit_id")),
        "scene_id": _clean(shot.get("scene_id")),
        "location_id": _clean(shot.get("location_id") or shot.get("location")),
        "time": _clean(shot.get("time")),
        "transition_device": _upper(shot.get("transition_device")),
        "action_text": _action_text(shot) if isinstance(shot, dict) else "",
        "declared": bool(record),
        "characters": positions,
        "on_screen": on_screen,
        "props": props,
        "props_declared": from_map or bool(perception_props),
        "time_space": _upper(perception.get("time_space")) or UNKNOWN,
        "jump_cut": jump_cut,
        "action_repeat": {"status": _upper(action_repeat.get("status")) or UNKNOWN,
                          "reason": _clean(action_repeat.get("reason"))},
        "entry_signature": _state_signature(contract_chars, legacy_entry, perception, "entry",
                                            positions, props),
        "exit_signature": _state_signature(contract_chars, legacy.get("exit_state") or {},
                                           perception, "exit", positions, props),
    }


def _state_signature(characters: list[dict[str, Any]], legacy_props: dict[str, Any],
                     perception: dict[str, Any], side: str,
                     positions: dict[str, dict[str, str]],
                     props: dict[str, dict[str, Any]]) -> str:
    """A comparable fingerprint of everything this shot says is true of the frame."""
    rows: list[Any] = []
    for row in characters:
        cid = _clean(row.get("character_id") or row.get("entity_id") or row.get("character"))
        state = row.get(f"{side}_state") if isinstance(row.get(f"{side}_state"), dict) else {}
        rows.append([cid, [state.get(field) for field in CHARACTER_STATE_FIELDS]])
    for cid, row in sorted(positions.items()):
        rows.append([cid, row["screen_slot"], row["eyeline_target"], row["occlusion"]])
    rows.append(["on_screen", perception.get("on_screen") if isinstance(perception.get("on_screen"), list) else None])
    rows.append(["time_space", _upper(perception.get("time_space"))])
    if isinstance(legacy_props, dict):
        for prop_id, value in sorted(legacy_props.items()):
            rows.append(["prop", _clean(prop_id), _clean(value)])
    for prop_id, row in sorted(props.items()):
        if row.get("declared_by") == "perception_state.props":
            rows.append(["prop", prop_id, row.get("holder"), row.get("pickup_state")])
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


# --------------------------------------------------------------------------- rules


def _character_global_ids(state: dict[str, Any] | None) -> set[str]:
    ids: set[str] = set()
    for record in state_records(state).values():
        contract = record.get("persistent_state_contract") or {}
        for row in _rows(contract.get("characters")):
            cid = _clean(row.get("character_id") or row.get("entity_id") or row.get("character"))
            if cid:
                ids.add(cid)
        perception = record.get("perception_state") or {}
        for row in _rows(perception.get("characters")):
            cid = _clean(row.get("character_id") or row.get("character"))
            if cid:
                ids.add(cid)
        if isinstance(perception.get("on_screen"), list):
            ids.update(_clean(value) for value in perception["on_screen"] if _clean(value))
    return ids


def _is_held_by_character(prop: dict[str, Any], characters: set[str]) -> bool:
    holder = prop.get("holder")
    if holder and holder not in PERCEPTION_PROP_HOLDER_SENTINELS and holder != UNKNOWN:
        return True
    return prop.get("pickup_state") in {"HELD", "INHERITED", "PICKED_UP_IN_SHOT"}


def _rule_prop_held(previous: dict[str, Any], current: dict[str, Any],
                    characters: set[str]) -> tuple[str, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    unreachable = False
    if not current.get("props_declared") or not previous.get("props_declared"):
        return UNKNOWN, findings
    for prop_id, cur in sorted(current["props"].items()):
        if cur.get("holder") == UNKNOWN and cur.get("pickup_state") == UNKNOWN:
            # the row exists and says nothing this rule can read: that is not a pass
            unreachable = True
            continue
        if not _is_held_by_character(cur, characters):
            continue
        if cur.get("pickup_state") == "PICKED_UP_IN_SHOT":
            continue  # the audience sees it taken up in this shot
        prior = previous["props"].get(prop_id)
        if prior is None:
            # The previous shot says nothing about this prop.  A prop first seen in N+1 may
            # legitimately come out of a pocket, so an undeclared prior is UNKNOWN, not a P1:
            # only a prior the ledger PLACES somewhere else is a contradiction.
            unreachable = True
            continue
        if prior.get("holder") == UNKNOWN and prior.get("pickup_state") == UNKNOWN:
            unreachable = True
            continue
        if prior.get("holder") == cur.get("holder") and cur.get("holder") not in (None, UNKNOWN):
            continue  # inherited: the ledger's whole job
        if cur.get("pickup_state") == "INHERITED":
            continue  # explicitly inherited; rule 2 still watches a put-down
        findings.append({
            "code": "PROP_HELD_WITHOUT_PICKUP",
            "prop_id": prop_id,
            "from_shot_id": previous["shot_id"], "to_shot_id": current["shot_id"],
            "prior_holder": prior.get("holder"),
            "holder": cur.get("holder"),
            "pickup_state": cur.get("pickup_state"),
        })
    if findings:
        return "FINDING", findings
    return (UNKNOWN if unreachable else "PASS"), findings


def _rule_prop_retake(window: list[dict[str, Any]], index: int,
                      characters: set[str]) -> tuple[str, list[dict[str, Any]]]:
    current = window[index]
    findings: list[dict[str, Any]] = []
    if not current.get("props_declared"):
        return UNKNOWN, findings
    for prop_id, cur in sorted(current["props"].items()):
        if not _is_held_by_character(cur, characters):
            continue
        put_down_index = None
        for before in range(index - 1, -1, -1):
            row = window[before]["props"].get(prop_id)
            if row is None:
                continue
            if row.get("pickup_state") == "PUT_DOWN_IN_SHOT":
                put_down_index = before
                break
            if row.get("pickup_state") == "PICKED_UP_IN_SHOT":
                break
        if put_down_index is None:
            continue
        retake = (cur.get("pickup_state") == "PICKED_UP_IN_SHOT"
                  or bool(cur.get("retake_source_ref"))
                  or any(window[after]["props"].get(prop_id, {}).get("pickup_state")
                         == "PICKED_UP_IN_SHOT"
                         for after in range(put_down_index + 1, index + 1)))
        if retake:
            continue
        findings.append({
            "code": "PROP_RETAKE_UNDECLARED",
            "prop_id": prop_id,
            "from_shot_id": window[put_down_index]["shot_id"],
            "to_shot_id": current["shot_id"],
            "holder": cur.get("holder"),
            "pickup_state": cur.get("pickup_state"),
        })
    return ("FINDING" if findings else "PASS"), findings


def _rule_action_repeat(previous: dict[str, Any],
                        current: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    declared = current.get("action_repeat") or {}
    if declared.get("status") == "REPEAT":
        return "PASS", []
    before, after = _norm_text(previous.get("action_text", "")), _norm_text(current.get("action_text", ""))
    if not before or before != after:
        return "PASS", []
    if previous.get("entry_signature") != current.get("entry_signature"):
        return "PASS", []
    if previous.get("exit_signature") != current.get("exit_signature"):
        return "PASS", []
    return "FINDING", [{
        "code": "ACTION_REPEAT_WITHOUT_STATE_CHANGE",
        "from_shot_id": previous["shot_id"], "to_shot_id": current["shot_id"],
        "action_text": after,
    }]


def _rule_eyeline(current: dict[str, Any],
                  characters: set[str]) -> tuple[str, list[dict[str, Any]]]:
    if current.get("on_screen") == UNKNOWN:
        return UNKNOWN, []
    if current.get("on_screen"):
        return "PASS", []
    findings: list[dict[str, Any]] = []
    for cid, row in sorted(current["characters"].items()):
        target = row.get("eyeline_target")
        if not target:
            continue
        if target.upper() in PERCEPTION_PROP_HOLDER_SENTINELS:
            continue  # "look at the door" is not an addressee
        if ":" in target:  # OFF_SCREEN:..., OBJECT:..., NOBODY
            kind = target.split(":", 1)[0].strip().upper()
            if kind in {"OFF_SCREEN", "OBJECT", "NOBODY", "VOICE"}:
                continue
        if target in characters or target in current["characters"]:
            findings.append({
                "code": "EYELINE_ADDRESSEE_NOT_IN_FRAME",
                "character_id": cid, "addressee": target,
                "from_shot_id": current["shot_id"], "to_shot_id": current["shot_id"],
                "on_screen": [],
                "occlusion": row.get("occlusion") or "",
            })
    return ("FINDING" if findings else "PASS"), findings


def _cut_evidence(previous: dict[str, Any], current: dict[str, Any]) -> str | None:
    if current.get("jump_cut"):
        return "DECLARED_JUMP_CUT"
    if current.get("time_space") in {"DECLARED_TIME_JUMP", "DECLARED_SCENE_CHANGE"}:
        return current["time_space"]
    if current.get("transition_device") in CUT_DEVICES:
        return f"TRANSITION_DEVICE:{current['transition_device']}"
    return None


def _rule_screen_slot(previous: dict[str, Any],
                      current: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if not current.get("characters") or not previous.get("characters"):
        return UNKNOWN, []
    findings: list[dict[str, Any]] = []
    for cid, row in sorted(current["characters"].items()):
        before = previous["characters"].get(cid)
        if not before:
            continue
        now, was = row.get("screen_slot"), before.get("screen_slot")
        if not now or not was or UNKNOWN in (now, was) or now == was:
            continue
        if _cut_evidence(previous, current):
            continue
        findings.append({
            "code": "SCREEN_SLOT_CHANGED_WITHOUT_CUT",
            "character_id": cid,
            "from_shot_id": previous["shot_id"], "to_shot_id": current["shot_id"],
            "from_slot": was, "to_slot": now,
            "cut_evidence": "NONE_DECLARED",
        })
    return ("FINDING" if findings else "PASS"), findings


def _rule_time_space(previous: dict[str, Any],
                     current: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    space_before = previous.get("location_id") or previous.get("scene_id")
    space_after = current.get("location_id") or current.get("scene_id")
    time_before, time_after = previous.get("time"), current.get("time")
    moved = bool(space_before and space_after and space_before != space_after)
    jumped = bool(time_before and time_after and time_before != time_after)
    if not (moved or jumped):
        if not (space_before and space_after and time_before and time_after):
            return UNKNOWN, []
        return "PASS", []
    declared = current.get("time_space")
    if declared in {"DECLARED_TIME_JUMP", "DECLARED_SCENE_CHANGE"}:
        return "PASS", []
    if declared == UNKNOWN:
        return UNKNOWN, []
    return "FINDING", [{
        "code": "TIME_SPACE_CHANGE_UNDECLARED",
        "from_shot_id": previous["shot_id"], "to_shot_id": current["shot_id"],
        "space_changed": moved, "time_changed": jumped,
        "declared": declared,
    }]


# --------------------------------------------------------------------------- report


def _observation_slice(observations: dict[str, Any] | None, shot_id: str) -> dict[str, Any]:
    if not isinstance(observations, dict):
        return {"status": "NO_QA_MEASUREMENT"}
    row = observations.get(shot_id)
    if not isinstance(row, dict):
        return {"status": UNKNOWN}
    characters = row.get("characters") if isinstance(row.get("characters"), dict) else {}
    props = row.get("props") if isinstance(row.get("props"), dict) else {}
    if not characters and not props:
        return {"status": UNKNOWN}
    return {
        "status": _clean(row.get("status")).upper() or "MEASURED",
        "characters": {cid: {"screen_slot": _upper(value.get("screen_slot") if isinstance(value, dict) else value)
                             or UNKNOWN} for cid, value in characters.items()},
        "props": {pid: {"holder": _clean(value.get("holder") if isinstance(value, dict) else value) or UNKNOWN}
                  for pid, value in props.items()},
        "source": _clean(row.get("source")) or UNKNOWN,
    }


def _planned(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    return {
        "from_shot_id": previous.get("shot_id"), "to_shot_id": current.get("shot_id"),
        "action_text": _norm_text(current.get("action_text", "")),
        "time_space": current.get("time_space"),
        "on_screen": current.get("on_screen"),
        "characters": {cid: {"screen_slot": row.get("screen_slot"),
                             "eyeline_target": row.get("eyeline_target")}
                       for cid, row in current.get("characters", {}).items()},
        "props": {pid: {"holder": row.get("holder"), "pickup_state": row.get("pickup_state")}
                  for pid, row in current.get("props", {}).items()},
        "from_props": {pid: {"holder": row.get("holder"), "pickup_state": row.get("pickup_state")}
                       for pid, row in previous.get("props", {}).items()},
        "transition_device": current.get("transition_device") or "",
        "declared": bool(current.get("declared")),
    }


def _writer_item(finding: dict[str, Any]) -> dict[str, Any]:
    rule = RULES[finding["code"]]
    item_id = ":".join(part for part in (
        finding["code"], str(finding.get("from_shot_id")), str(finding.get("to_shot_id")),
        str(finding.get("prop_id") or finding.get("character_id") or "")) if part)
    return {
        "item_id": item_id,
        "code": finding["code"],
        "severity": rule["severity"],
        "kind": rule["kind"],
        "from_shot_id": finding.get("from_shot_id"),
        "to_shot_id": finding.get("to_shot_id"),
        "prop_id": finding.get("prop_id"),
        "character_id": finding.get("character_id"),
        "question": rule["question"],
        "answer_options": list(rule["answer_options"]),
        "status": "OPEN",
    }


def shots_from_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """The shot order and the fields the rules read, from a generation contract."""
    unit_by_shot: dict[str, str] = {}
    for unit in contract.get("video_units") or contract.get("units") or []:
        if isinstance(unit, dict):
            for shot_id in unit.get("editorial_shot_ids") or []:
                unit_by_shot[str(shot_id)] = _clean(unit.get("unit_id"))
    scenes = {_clean(row.get("scene_id")): row for row in contract.get("scene_states") or []
              if isinstance(row, dict)}
    out: list[dict[str, Any]] = []
    for shot in contract.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        scene = scenes.get(_clean(shot.get("scene_id"))) or {}
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        transition = shot.get("incoming_transition_contract") or shot.get("transition_contract") or {}
        out.append({
            "shot_id": _clean(shot.get("shot_id")),
            "unit_id": unit_by_shot.get(_clean(shot.get("shot_id")), ""),
            "scene_id": _clean(shot.get("scene_id")),
            "location_id": _clean(scene.get("location_id")),
            "time": _clean(scene.get("time_id") or scene.get("time_of_day_state") or scene.get("time")),
            "blocking": _clean(shot.get("blocking")),
            "prompt_spec": spec,
            "transition_device": transition.get("transition_device"),
        })
    return out


def evaluate(shots: list[dict[str, Any]], *, state: dict[str, Any] | None = None,
             observations: dict[str, Any] | None = None, config: dict[str, Any] | None = None,
             focus: set[str] | None = None, state_source: str | None = None) -> dict[str, Any]:
    """One row per shot pair; per pair, one status per rule.  Pure, order-preserving."""
    config = config if config is not None else load_config()
    records = state_records(state)
    declared = bool(records) and (state or {}).get("schema") in (None, STATE_SCHEMA)
    characters = _character_global_ids(state)
    for shot, record in zip(shots, [records.get(_clean(s.get("shot_id"))) for s in shots]):
        for cid in (record or {}).get("persistent_state_contract", {}).get("characters") or []:
            if isinstance(cid, dict):
                characters.add(_clean(cid.get("character_id") or cid.get("entity_id") or cid.get("character")))
    characters.discard("")

    # eye-line is a property of ONE frame, so it is read once per shot and attached to the
    # pair that enters it; the slice's first shot has no entering pair of its own, so its
    # finding rides the first pair rather than being dropped.
    window = [shot_view(shot, records.get(_clean(shot.get("shot_id")))) for shot in shots]
    eyeline_by_index: dict[int, list[dict[str, Any]]] = {}
    eyeline_unknown: set[int] = set()
    for position, view in enumerate(window):
        outcome, found = _rule_eyeline(view, characters)
        if outcome == "FINDING":
            eyeline_by_index[position] = found
        elif outcome == UNKNOWN:
            eyeline_unknown.add(position)

    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for index in range(1, len(window)):
        previous, current = window[index - 1], window[index]
        if focus is not None and current["shot_id"] not in focus:
            continue
        checks: dict[str, str] = {}
        pair_findings: list[dict[str, Any]] = []
        if not declared:
            checks = {code: UNKNOWN for code in RULE_ORDER}
        else:
            outcome, found = _rule_prop_held(previous, current, characters)
            checks["PROP_HELD_WITHOUT_PICKUP"] = outcome
            pair_findings.extend(found)
            outcome, found = _rule_prop_retake(window, index, characters)
            checks["PROP_RETAKE_UNDECLARED"] = outcome
            pair_findings.extend(found)
            outcome, found = _rule_action_repeat(previous, current)
            checks["ACTION_REPEAT_WITHOUT_STATE_CHANGE"] = outcome
            pair_findings.extend(found)
            shot_findings = list(eyeline_by_index.get(index, []))
            if index == 1:  # the episode's first shot has no entering pair of its own
                shot_findings = list(eyeline_by_index.get(0, [])) + shot_findings
            checks["EYELINE_ADDRESSEE_NOT_IN_FRAME"] = (
                "FINDING" if shot_findings
                else UNKNOWN if (index in eyeline_unknown or (index == 1 and 0 in eyeline_unknown))
                else "PASS")
            pair_findings.extend(shot_findings)
            outcome, found = _rule_screen_slot(previous, current)
            checks["SCREEN_SLOT_CHANGED_WITHOUT_CUT"] = outcome
            pair_findings.extend(found)
            outcome, found = _rule_time_space(previous, current)
            checks["TIME_SPACE_CHANGE_UNDECLARED"] = outcome
            pair_findings.extend(found)
        status = (UNKNOWN if not declared
                  else "FINDING" if pair_findings
                  else "UNKNOWN" if UNKNOWN in checks.values()
                  else "PASS")
        row = {
            "from_shot_id": previous["shot_id"], "to_shot_id": current["shot_id"],
            "unit_id": current["unit_id"],
            "status": status,
            "checks": checks,
            "planned": _planned(previous, current),
            "observed": {"from_shot": _observation_slice(observations, previous["shot_id"]),
                         "to_shot": _observation_slice(observations, current["shot_id"])},
            "findings": pair_findings,
        }
        rows.append(row)
        findings.extend(pair_findings)
        unknown.append({"from_shot_id": previous["shot_id"], "to_shot_id": current["shot_id"],
                        "codes": sorted(code for code, value in checks.items() if value == UNKNOWN)})

    items = [_writer_item(finding) for finding in findings]
    items.sort(key=lambda item: ({"P1": 0, "P2": 1, "MERGE": 2}.get(item["severity"], 3),
                                 item["to_shot_id"], item["item_id"]))
    blocking = bool(config.get("blocking") is True)
    return {
        "schema": SCHEMA,
        "tool": TOOL_ID,
        "policy": config.get("policy"),
        "state_source": state_source or (UNKNOWN if not declared else "DECLARED"),        "state_declared": declared,
        "blocking_enabled": blocking,
        "status": ("UNKNOWN" if not declared
                   else "FINDINGS" if findings
                   else "UNKNOWN" if any(row["status"] == UNKNOWN for row in rows)
                   else "PASS"),
        "would_block": bool(blocking and any(item["severity"] == "P1" for item in items)),
        "pair_count": len(rows),
        "rows": rows,
        "findings": findings,
        "unknown_pairs": [row for row in unknown if row["codes"]],
        "writer_items": items,
        "tally": {code: sum(1 for row in rows for key, value in row["checks"].items()
                            if key == code and value == "FINDING") for code in RULE_ORDER},
        "rules": {code: dict(meta) for code, meta in RULES.items()},
        "note": ("Per shot pair.  PLANNED comes from the authored ledger, OBSERVED from a QA "
                 "measurement if one exists — otherwise UNKNOWN.  A missing state file is "
                 "UNKNOWN, never a pass and never a failure.  Nothing here stops a paid run "
                 "unless the config's blocking switch is on; it ships off."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--contract", required=True, help="the episode's generation contract")
    parser.add_argument("--state", help="shot_state_authoring.json (absent = UNKNOWN)")
    parser.add_argument("--observations", help="per-shot QA measurement, if one exists")
    parser.add_argument("--unit", help="only report pairs entering this unit")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    shots = shots_from_contract(contract)
    focus = None
    if args.unit:
        focus = {shot["shot_id"] for shot in shots if shot["unit_id"] == args.unit}
    observations = (json.loads(Path(args.observations).read_text(encoding="utf-8"))
                    if args.observations else None)
    report = evaluate(shots, state=load_state(args.state), observations=observations,
                      config=load_config(args.config), focus=focus,
                      state_source=str(args.state) if args.state else UNKNOWN)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "pairs": report["pair_count"],
                      "findings": len(report["findings"]),
                      "would_block": report["would_block"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
