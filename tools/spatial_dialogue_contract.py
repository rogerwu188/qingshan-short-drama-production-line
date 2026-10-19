#!/usr/bin/env python3
"""Carry who-speaks-to-whom, where each party stands, and where the eyes go.

The role contract already binds *identity* (who the speaker is) and *addressing*
(the listener's name).  That is not the same as staging: a character may speak
to someone while looking down at a letter, and the listener may be entirely
offscreen.  This module keeps those five facts separate and optional:

  speaker_facing_direction            body orientation, e.g. 「身体转向元掌柜」
  speaker_gaze_target                 eyes, e.g. 「落在手中的药方」 / 「CAMERA」 / 「OFFSCREEN_LEFT」
  listener_position_relative_to_speaker
  listener_facing_direction
  listener_gaze_target
  offscreen_listener_visual_cues      what the audience sees when the listener is not in frame

Nothing is invented.  An absent field renders nothing; a contradiction is a
validation failure, not a default.  "Speaks to X" never implies "looks at X".
"""

from __future__ import annotations

from typing import Any

SCHEMA = "qingshan.spatial_dialogue_contract.v1"
FIELDS = (
    "speaker_facing_direction",
    "speaker_gaze_target",
    "listener_position_relative_to_speaker",
    "listener_facing_direction",
    "listener_gaze_target",
    "offscreen_listener_visual_cues",
)
_GAZE_SENTINELS = {"CAMERA", "OFFSCREEN", "OFFSCREEN_LEFT", "OFFSCREEN_RIGHT", "OFFSCREEN_UP", "OFFSCREEN_DOWN"}
_VISIBLE_STATES = {
    "VISIBLE_AND_IDENTITY_LOCKED",
    "OWNER_PARTIALLY_OCCLUDED_BUT_ANATOMICALLY_CONTINUOUS",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def declared(row: dict[str, Any]) -> dict[str, str]:
    """Only the non-empty spatial fields of a role row."""
    return {key: _clean(row.get(key)) for key in FIELDS if _clean(row.get(key))}


def _registered_targets(row: dict[str, Any]) -> set[str]:
    names = {_clean(value) for value in (row.get("entity_names") or {}).values() if _clean(value)}
    states = {_clean(key) for key in (row.get("entity_states") or {}) if _clean(key)}
    return names | states


def validate(row: dict[str, Any]) -> list[str]:
    """Structural contradictions only; absence is legal and never filled in."""
    values = declared(row)
    if not values:
        return []
    failures: list[str] = []
    speaker = _clean(row.get("dialogue_speaker"))
    listener = _clean(row.get("dialogue_listener"))
    listener_state = _clean((row.get("entity_presence") or {}).get(
        _clean(row.get("dialogue_listener_id")) or listener))
    if values.get("speaker_facing_direction") and not speaker:
        failures.append("SPATIAL_SPEAKER_FACING_WITHOUT_SPEAKER")
    if values.get("speaker_gaze_target") and not speaker:
        failures.append("SPATIAL_SPEAKER_GAZE_WITHOUT_SPEAKER")
    for key in ("listener_position_relative_to_speaker", "listener_facing_direction", "listener_gaze_target"):
        if values.get(key) and not listener:
            failures.append(f"SPATIAL_LISTENER_FIELD_WITHOUT_LISTENER:{key}")
    cues = values.get("offscreen_listener_visual_cues")
    if cues and listener and listener_state in _VISIBLE_STATES:
        failures.append("SPATIAL_OFFSCREEN_CUES_FOR_VISIBLE_LISTENER")
    if listener and not cues and listener_state and listener_state not in _VISIBLE_STATES:
        failures.append("SPATIAL_OFFSCREEN_LISTENER_WITHOUT_VISUAL_CUES")
    targets = _registered_targets(row)
    for key in ("speaker_gaze_target", "listener_gaze_target"):
        value = values.get(key)
        if not value or value.upper() in _GAZE_SENTINELS:
            continue
        if targets and value not in targets and not any(name and name in value for name in targets):
            failures.append(f"SPATIAL_GAZE_TARGET_UNREGISTERED:{key}:{value}")
    return failures


def render_zh(row: dict[str, Any]) -> str:
    """One provider-facing Chinese clause; empty when nothing was declared."""
    values = declared(row)
    if not values:
        return ""
    speaker = _clean(row.get("dialogue_speaker"))
    listener = _clean(row.get("dialogue_listener"))
    parts: list[str] = []
    if values.get("speaker_facing_direction"):
        parts.append(f"{speaker}{values['speaker_facing_direction']}")
    if values.get("speaker_gaze_target"):
        parts.append(f"{speaker}的视线{values['speaker_gaze_target']}")
    if values.get("listener_position_relative_to_speaker"):
        parts.append(f"{listener}{values['listener_position_relative_to_speaker']}")
    if values.get("listener_facing_direction"):
        parts.append(f"{listener}{values['listener_facing_direction']}")
    if values.get("listener_gaze_target"):
        parts.append(f"{listener}的视线{values['listener_gaze_target']}")
    if values.get("offscreen_listener_visual_cues"):
        parts.append(f"画内视觉线索：{values['offscreen_listener_visual_cues']}")
    return "；".join(part for part in parts if part)


def render_en(row: dict[str, Any], *, translated: dict[str, str] | None = None,
              speaker_label: str | None = None, listener_label: str | None = None) -> str:
    """English clause for H3; ``translated`` carries the authored translation.

    ``speaker_label``/``listener_label`` replace the plan's Chinese names so no
    CJK reaches an H3 machine prompt outside a dialogue tag.
    """
    values = declared(row)
    if not values:
        return ""
    source = translated or {}
    speaker = _clean(speaker_label) or _clean(row.get("dialogue_speaker"))
    listener = _clean(listener_label) or _clean(row.get("dialogue_listener"))
    parts: list[str] = []
    def take(key: str, default: str) -> str:
        return _clean(source.get(key)) or default
    if values.get("speaker_facing_direction"):
        parts.append(take("speaker_facing_direction", f"{speaker} turns the body as authored"))
    if values.get("speaker_gaze_target"):
        parts.append(take("speaker_gaze_target", f"{speaker}'s eyes follow the authored target"))
    if values.get("listener_position_relative_to_speaker"):
        parts.append(take("listener_position_relative_to_speaker", f"{listener}'s authored position"))
    if values.get("listener_facing_direction"):
        parts.append(take("listener_facing_direction", f"{listener}'s authored facing"))
    if values.get("listener_gaze_target"):
        parts.append(take("listener_gaze_target", f"{listener}'s gaze follows the authored target"))
    if values.get("offscreen_listener_visual_cues"):
        parts.append(take("offscreen_listener_visual_cues", "the authored offscreen visual cue"))
    return "; ".join(parts)
