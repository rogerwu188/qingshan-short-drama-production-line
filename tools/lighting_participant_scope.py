#!/usr/bin/env python3
"""Decide which named people a shot's lighting line may mention.

The lighting line is authored per SCENE and then copied into every shot of that
scene, but a person named in it is only the motivating-subject reference for the
light, not a cast list.  Quoted into a shot whose own cast does not include that
person, it reads to the provider as a person to render — so a declared empty
plate comes back with a face in it, or a two-hander renders a third body.

The rule here is taken from the script, not from preference:

* the scene's lighting line may name a person as the light's motivation;
* a shot may keep that name only if the shot itself puts the person in frame;
* if the shot's own authored text marks the person as off-frame (画外) — the
  standard way a director says "this shot is the other side of a two-hander" —
  the name is removed;
* if the shot does not mention the person at all, the name is removed.

Both removals are objective: the deciding text is the shot's authored axis /
blocking / dialogue lines, which are the shot's own authority.  Nothing is
invented and the light source itself is always preserved — only the participant
clause is dropped, and the fact is recorded so a reviewer can see it happened.
"""

from __future__ import annotations

import re
from typing import Any


SCHEMA = "qingshan.lighting_participant_scope.v1"
POLICY_ID = "SHOT_OWN_CAST_ONLY"

#: The director's markers for "this person is deliberately outside the frame".
OFF_FRAME_MARKERS = ("画外", "画右外", "画左外", "画上外", "画下外", "画面上外", "画面下外")

#: Fields of a shot that carry the shot's own authored text.  These are the
#: deciding evidence: the shot's axis, blocking and dialogue, never the scene
#: header (which is where the lighting line itself lives and would be circular).
SHOT_AUTHORITY_FIELDS = ("axis", "blocking", "primary_action", "dialogue", "action")


def _shot_authority_text(shot: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in SHOT_AUTHORITY_FIELDS:
        value = shot.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, dict):
            for key in ("primary_action", "start_state", "completion_state"):
                inner = value.get(key)
                if isinstance(inner, str) and inner.strip():
                    parts.append(inner.strip())
    for row in shot.get("cast") or []:
        if isinstance(row, dict):
            for key in ("character_id", "canonical_name", "display_name"):
                value = row.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
        elif isinstance(row, str) and row.strip():
            parts.append(row.strip())
    return " ｜ ".join(parts)


def _visible_names(shot: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for row in shot.get("cast") or []:
        if isinstance(row, dict):
            for key in ("character_id", "canonical_name", "display_name"):
                value = str(row.get(key) or "").strip()
                if value:
                    names.add(value)
        elif isinstance(row, str) and row.strip():
            names.add(row.strip())
    return names


def _name_is_off_frame(authority_text: str, name: str) -> bool:
    """Whether the shot's own text places this person outside the frame."""
    for marker in OFF_FRAME_MARKERS:
        # 「面向画右外的秦铭」 / 「秦铭在画外」 — the marker and the name adjacent
        # in either order, with no clause boundary between them.
        if re.search(
            re.escape(name) + r"[^。；，,]{0,8}" + re.escape(marker)
            + r"|" + re.escape(marker) + r"[^。；，,]{0,8}" + re.escape(name),
            authority_text,
        ):
            return True
    return False


def scoped_lighting_line(
    lighting: str,
    *,
    shot: dict[str, Any],
    name_to_entity: dict[str, str] | None = None,
    entity_label: dict[str, str] | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """Return the lighting line this shot may carry, plus what was removed.

    Only a participant clause is ever removed.  The motivating light itself, the
    surfaces it falls on and every non-person detail are preserved verbatim, so
    the shot keeps its authored look and loses only a cast claim it does not own.
    """
    line = str(lighting or "")
    if not line.strip():
        return line, []
    authority = _shot_authority_text(shot)
    visible = _visible_names(shot)
    mapping = name_to_entity or {}
    labels = entity_label or {}
    removals: list[dict[str, str]] = []
    for name in sorted(mapping, key=len, reverse=True):
        if name not in line:
            continue
        entity_id = mapping[name]
        aliases = {name, entity_id, labels.get(entity_id, "")} - {""}
        if aliases & visible:
            # The shot does put this person in frame.  Keep the clause.
            continue
        reason = (
            "SHOT_MARKS_PERSON_OFF_FRAME"
            if _name_is_off_frame(authority, name)
            else "SHOT_NEVER_NAMES_PERSON"
        )
        trimmed = _drop_participant_clause(line, name)
        if trimmed == line:
            continue
        removals.append({
            "name": name, "entity_id": entity_id, "reason": reason,
            "policy": POLICY_ID,
        })
        line = trimmed
    return line, removals


def _drop_participant_clause(line: str, name: str) -> str:
    """Remove this person from the line without touching the light itself.

    Handles the three authored shapes:
      「…照亮池边的老藤与秦铭俯身的脸」 → 「…照亮池边的老藤」
      「…交叉照着窗边的秦铭」           → 「…交叉照着窗边」
      「…的光照着许岳平偏向一边的脸，…」 → 「…的光亮着，…」

    What is left must still read as a lighting line: a bare possessive 「的」 or
    a transitive verb with nothing left to fall on is tidied to an intransitive
    statement about the source.  No surface or object is ever invented.
    """
    patterns = (
        r"[与和及、,，]\s*" + re.escape(name) + r"[^，。；]*",
        re.escape(name) + r"[^，。；]*?(?=[，。；]|$)",
    )
    for pattern in patterns:
        candidate = re.sub(pattern, "", line, count=1)
        candidate = re.sub(r"[，。；]\s*(?=[，。；])", "", candidate)
        candidate = re.sub(r"[与和]\s*(?=[，。；]|$)", "", candidate)
        candidate = re.sub(r"\s{2,}", " ", candidate).strip(" ，、")
        candidate = _tidy_dangling_clause(candidate)
        if candidate and candidate != line:
            return candidate
    return line


#: A transitive light verb left with no object once the person is gone.
_DANGLING_LIGHT_VERB = re.compile(r"(照亮|照着|照在|照向|打在|映在|映着)\s*$")


def _tidy_dangling_clause(line: str) -> str:
    """Make a clause that just lost its object read as a statement about the light."""
    if not line:
        return line
    tidied = re.sub(r"的\s*$", "", line).rstrip(" ，、")
    tidied = _DANGLING_LIGHT_VERB.sub("亮着", tidied)
    return tidied.strip(" ，、")


def audit_shots(
    shots: list[dict[str, Any]],
    *,
    lighting_of: Any,
    name_to_entity: dict[str, str],
    entity_label: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Report every shot whose lighting line names a person the shot does not show.

    Read-only.  Builders call this to fail before a paid POST; reviewers call it
    to see the finding with the reason it was made.
    """
    findings: list[dict[str, Any]] = []
    for shot in shots:
        lighting = lighting_of(shot)
        if not lighting:
            continue
        _, removals = scoped_lighting_line(
            lighting, shot=shot,
            name_to_entity=name_to_entity, entity_label=entity_label,
        )
        for removal in removals:
            findings.append({"shot_id": shot.get("shot_id"), **removal})
    return {
        "schema": SCHEMA,
        "status": "PASS" if not findings else "FINDINGS",
        "policy": POLICY_ID,
        "shot_count": len(shots),
        "finding_count": len(findings),
        "findings": findings,
    }
