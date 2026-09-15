#!/usr/bin/env python3
"""Canonical character identity graph shared by script, picture and sound.

Names are presentation labels.  ``character_id`` is the only identity key.
Aliases may resolve to that key, but may never create a second person.
"""

from __future__ import annotations

import re
from typing import Any


SCHEMA = "qingshan.character_entity_contract.v1"
ACTIVE_FROM_EPISODE = 54
VISIBLE = {"VISIBLE_AND_IDENTITY_LOCKED", "OWNER_PARTIALLY_OCCLUDED_BUT_AN_CONTINUOUS"}
SILENT_MARKERS = ("闭口", "不得张口", "不可张口", "不说话", "silent")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _speaker_is_marked_silent(value: Any) -> bool:
    text = _clean(value).lower()
    return any(
        text.startswith(prefix)
        for prefix in ("闭口", "全程闭口", "保持闭口", "不得张口", "不可张口", "不说话", "silent")
    )


def _episode_number(payload: dict[str, Any]) -> int:
    match = re.match(r"E(\d+)", _clean(payload.get("episode") or payload.get("unit_id")).upper())
    return int(match.group(1)) if match else 0


def _specs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("ordered_prompt_specs")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return [row.get("prompt_spec") for row in payload.get("shots") or [] if isinstance(row.get("prompt_spec"), dict)]


def build_character_index(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
    rows = payload.get("character_entities")
    failures: list[str] = []
    if not isinstance(rows, list) or not rows:
        return {}, {}, ["CHARACTER_ENTITY_REGISTRY_MISSING"]
    by_id: dict[str, dict[str, Any]] = {}
    alias_to_id: dict[str, str] = {}
    for row in rows:
        cid = _clean(row.get("character_id"))
        canonical = _clean(row.get("canonical_name"))
        if not cid or not canonical:
            failures.append("CHARACTER_ENTITY_ID_OR_CANONICAL_NAME_MISSING")
            continue
        if cid in by_id:
            failures.append(f"CHARACTER_ENTITY_ID_DUPLICATE:{cid}")
            continue
        by_id[cid] = row
        labels = [canonical, *list(row.get("aliases") or [])]
        for label in labels:
            name = _clean(label)
            if not name:
                continue
            previous = alias_to_id.get(name)
            if previous and previous != cid:
                failures.append(f"CHARACTER_ALIAS_COLLISION:{name}:{previous}:{cid}")
            alias_to_id[name] = cid
    return by_id, alias_to_id, failures


def resolve_character_id(value: Any, alias_to_id: dict[str, str]) -> str | None:
    name = _clean(value)
    return alias_to_id.get(name) or (name if name in set(alias_to_id.values()) else None)


def validate_character_entity_contract(payload: dict[str, Any]) -> dict[str, Any]:
    required = _episode_number(payload) >= ACTIVE_FROM_EPISODE
    if not required and not payload.get("character_entities"):
        return {"schema": "qingshan.character_entity_gate.v1", "status": "PASS", "required": False, "failures": []}
    by_id, aliases, failures = build_character_index(payload)
    for spec_index, spec in enumerate(_specs(payload), 1):
        sid = _clean(spec.get("shot_id")) or f"SPEC-{spec_index}"
        cast_ids: set[str] = set()
        cast_names: dict[str, str] = {}
        for cast in spec.get("cast") or []:
            name = _clean(cast.get("character"))
            cid = _clean(cast.get("character_id"))
            resolved = resolve_character_id(name, aliases)
            if not cid:
                failures.append(f"{sid}_CAST_CHARACTER_ID_MISSING:{name or 'UNKNOWN'}")
            elif cid not in by_id:
                failures.append(f"{sid}_CAST_CHARACTER_ID_UNREGISTERED:{cid}")
            elif resolved != cid:
                failures.append(f"{sid}_CAST_NAME_ID_MISMATCH:{name}:{cid}:{resolved or 'UNRESOLVED'}")
            if cid in cast_ids:
                failures.append(f"{sid}_CAST_CHARACTER_ID_DUPLICATE:{cid}")
            cast_ids.add(cid)
            cast_names[name] = cid

        dialogue = _clean(spec.get("dialogue"))
        speaker_name = ""
        speaker_id = None
        if dialogue:
            speaker_name, separator, _ = dialogue.partition("：")
            if not separator:
                failures.append(f"{sid}_DIALOGUE_FORMAT_INVALID")
            speaker_name = speaker_name.strip()
            speaker_id = resolve_character_id(speaker_name, aliases)
            if not speaker_id:
                failures.append(f"{sid}_DIALOGUE_SPEAKER_UNREGISTERED:{speaker_name}")

        role = spec.get("role_semantic_disambiguation") or {}
        for name_field, id_field in (
            ("primary_actor", "primary_actor_id"),
            ("dialogue_speaker", "dialogue_speaker_id"),
            ("dialogue_listener", "dialogue_listener_id"),
            ("action_patient", "action_patient_id"),
        ):
            name = _clean(role.get(name_field))
            cid = _clean(role.get(id_field))
            is_character_role = (
                name_field in {"dialogue_speaker", "dialogue_listener"}
                or (name_field == "primary_actor" and _clean(role.get("primary_actor_kind") or "CHARACTER") == "CHARACTER")
                or (name_field == "action_patient" and resolve_character_id(name, aliases) is not None)
            )
            if name and is_character_role and not cid:
                failures.append(f"{sid}_{id_field.upper()}_MISSING:{name}")
            if cid and (cid not in by_id or resolve_character_id(name, aliases) != cid):
                failures.append(f"{sid}_{name_field.upper()}_NAME_ID_MISMATCH:{name}:{cid}")

        role_speaker_id = _clean(role.get("dialogue_speaker_id"))
        role_actor_id = _clean(role.get("primary_actor_id"))
        action = spec.get("action") or {}
        action_subject_id = _clean(action.get("subject_id"))
        actor_is_character = _clean(role.get("primary_actor_kind") or "CHARACTER") == "CHARACTER"
        if _clean(action.get("primary_action")) and actor_is_character and not action_subject_id:
            failures.append(f"{sid}_ACTION_SUBJECT_ID_MISSING")
        elif action_subject_id and actor_is_character and action_subject_id != role_actor_id:
            failures.append(f"{sid}_ACTION_SUBJECT_ROLE_ACTOR_MISMATCH:{action_subject_id}:{role_actor_id}")
        if dialogue and role_speaker_id != speaker_id:
            failures.append(f"{sid}_DIALOGUE_ROLE_SPEAKER_MISMATCH:{speaker_name}:{speaker_id}:{role_speaker_id}")
        presence = role.get("entity_presence") or {}
        states = role.get("entity_states") or {}
        offscreen = role_speaker_id and _clean(presence.get(role_speaker_id)) == "OFFSCREEN_VOICE_ONLY"
        if role_speaker_id and role_speaker_id not in cast_ids and not offscreen:
            failures.append(f"{sid}_DIALOGUE_SPEAKER_NOT_IN_VISIBLE_CAST:{role_speaker_id}")
        lip_owner_id = _clean(role.get("lip_owner_id"))
        if role_speaker_id and not offscreen and lip_owner_id != role_speaker_id:
            failures.append(f"{sid}_VISIBLE_LIP_OWNER_SPEAKER_MISMATCH:{lip_owner_id or 'MISSING'}:{role_speaker_id}")
        if offscreen and lip_owner_id:
            failures.append(f"{sid}_OFFSCREEN_DIALOGUE_MUST_NOT_HAVE_VISIBLE_LIP_OWNER:{lip_owner_id}")
        if role_speaker_id:
            state = _clean(states.get(role_speaker_id)).lower()
            if _speaker_is_marked_silent(state):
                failures.append(f"{sid}_DIALOGUE_SPEAKER_MARKED_SILENT:{role_speaker_id}")
        # Character entries are keyed by IDs. Typed non-character entities may
        # retain their role-contract labels.
        for field, mapping in (("STATE", states), ("PRESENCE", presence)):
            for key in mapping:
                if _clean(key) in aliases:
                    failures.append(f"{sid}_ENTITY_{field}_KEY_NOT_CHARACTER_ID:{key}")

    return {
        "schema": "qingshan.character_entity_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "required": required,
        "character_count": len(by_id),
        "failures": failures,
    }
