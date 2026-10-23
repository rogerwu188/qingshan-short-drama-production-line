#!/usr/bin/env python3
"""MiniMax-H3 renderer over the shared execution plan.

All machine-facing prose is English. Original-language dialogue is the only
text allowed inside ``<d>[Chinese]...</d>`` tags (``<d>[English]...</d>`` when the
unit's ``dialogue_language`` is ``en``).
"""

from __future__ import annotations

import re
from typing import Any

try:
    from tools.provider_scope_projection import (
        instance_cardinality_clauses,
        is_single_subject_mode,
        is_tight_pov_mode,
        population_clause,
        positive_single_subject_composition_clause,
    )
except ModuleNotFoundError:  # pragma: no cover - flat sys.path deployments
    from provider_scope_projection import (
        instance_cardinality_clauses,
        is_single_subject_mode,
        is_tight_pov_mode,
        population_clause,
        positive_single_subject_composition_clause,
    )

try:
    from tools.h3_provider_english_contract import (
        require_h3_provider_english_contract,
        validate_h3_provider_text_boundary,
    )
    from tools.prompt_budget_observability import measure_prompt
    from tools.provider_contract_boundary import validate_provider_prompt_boundary
    from tools.provider_semantic_coverage import build_semantic_coverage_receipt
    from tools.wardrobe_identity_contract import h3_adult_female_visual_block
    from tools.visual_culture_contract import prompt_block_en as visual_culture_prompt_block
except ModuleNotFoundError:
    from h3_provider_english_contract import (
        require_h3_provider_english_contract,
        validate_h3_provider_text_boundary,
    )
    from prompt_budget_observability import measure_prompt
    from provider_contract_boundary import validate_provider_prompt_boundary
    from provider_semantic_coverage import build_semantic_coverage_receipt
    from wardrobe_identity_contract import h3_adult_female_visual_block
    from visual_culture_contract import prompt_block_en as visual_culture_prompt_block
try:
    from tools.provider_contract_boundary import is_being_prop
except ModuleNotFoundError:
    from provider_contract_boundary import is_being_prop
try:
    from tools.prompt_shot_scope_policy import active_for as shot_scope_active_for
except ModuleNotFoundError:
    from prompt_shot_scope_policy import active_for as shot_scope_active_for
try:
    from tools import spatial_dialogue_contract
except ModuleNotFoundError:
    import spatial_dialogue_contract  # type: ignore


SCHEMA = "qingshan.minimax_h3_provider_renderer.v2_english_machine_dialogue_tags"
try:
    from tools.editorial_pacing_contract import delivery_clause, content_window_clause
except ModuleNotFoundError:
    from editorial_pacing_contract import delivery_clause, content_window_clause
ANTI_TEXT = (
    "TEXT-FREE FRAME: dialogue exists only as synchronized native speech; never render captions, "
    "subtitles, letters, numbers, punctuation, dialogue boxes, labels, signs, UI, logos, or watermarks"
)


_MOTION_MAPPING = {
    "STATIC": "locked camera", "LOCKED": "locked camera",
    "DOLLY": "one short dolly move", "PAN": "one short pan",
    "TRUCK": "one short lateral truck", "TRACK": "one short lateral track",
    "TRACKING": "one motivated axial follow",
    "CRANE": "one motivated vertical move", "TILT": "one motivated tilt",
    "ARC": "one motivated arc move",
}


def _optical(plan: dict[str, Any]) -> str:
    optical = []
    if plan.get("lens_mm"):
        optical.append(f"estimated {int(plan['lens_mm'])}mm focal length")
    shutter = {
        "NATURAL_MOTION_CLARITY": "natural real-time motion with clear contours",
        "CRISP_ACTION_DIRECTION": "crisp action direction and readable contact without long trails",
        "DIRECTIONAL_ACTION_BLUR": "slight directional blur only on fast-moving limbs while identities remain clear",
    }.get(str(plan.get("shutter_visual_intent") or ""))
    if shutter:
        optical.append(shutter)
    dof = {
        "DEEP_SPATIAL_READABILITY": "deep enough focus to read subjects, contact path, and spatial relation",
        "BALANCED_SUBJECT_SPACE": "balanced depth of field preserving essential space",
        "CONTROLLED_SUBJECT_SEPARATION": "controlled subject separation without blurring the opponent or key prop",
    }.get(str(plan.get("depth_of_field_intent") or ""))
    if dof:
        optical.append(dof)
    if plan.get("atmosphere_intent"):
        optical.append(f"authorized atmosphere effect only: {plan['atmosphere_intent']}")
    if plan.get("effect_intent"):
        optical.append(f"authorized visual effect only: {plan['effect_intent']}")
    return "; " + "; ".join(optical) if optical else ""


def _camera_grammar_clause(plan: dict[str, Any]) -> str:
    """CAMERA_GRAMMAR_V1 film-grammar wording, only for plans stamped camera_grammar (else "")."""
    if plan.get("camera_grammar") != "CAMERA_GRAMMAR_V1":
        return ""
    if str(plan.get("motion_family") or "STATIC").upper() in {"STATIC", "LOCKED"}:
        return "; a still, composed frame: the action plays inside it, no drift"
    return "; a motivated move: it starts with the action, settles on the end framing and holds; never sweep across empty space"


# ---------------------------------------------------------------------------
# CAMERA_GRAMMAR_V1 director block (docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md): named roster,
# wardrobe and creature looks in words, no extras, object inserts without people, no boilerplate
# framing.  Only for units whose camera plans carry the camera_grammar stamp (build_nalu_preproduction
# stamps them when camera_grammar_policy.active(contract, episode)); other units render byte-identically.
# ---------------------------------------------------------------------------
_PROVIDER_RUNE_LIMIT = 10_000  # = video_prompt_compiler.PROVIDER_PROMPT_RUNE_LIMIT (importing it would cycle)
_BOILERPLATE_FRAMING = re.compile(
    r"^(?:the )?framing (?:changes|moves|follows) with the camera(?: motion| move| movement)?$", re.IGNORECASE)
_NO_TRANSFER = ("Each subject wears only its own clothing; never transfer clothing, collars, hands or "
                "materials between subjects")
_NO_EXTRAS = ("No other people, figures, silhouettes, hands or body parts appear anywhere in frame, "
              "including the background and frame edges")
_WARDROBE_FIELDS = ("silhouette", "outer_layer", "inner_layer", "primary_color", "material", "footwear", "accessory")


def director_active(unit: dict[str, Any], plan: dict[str, Any]) -> bool:
    rows = [plan.get("camera_plan"), unit.get("camera_plan"),
            *[spec.get("camera_plan") for spec in unit.get("ordered_prompt_specs") or []]]
    for row in [*(plan.get("per_shot_camera_plans") or []), *(unit.get("per_shot_camera_plans") or [])]:
        rows += [row, row.get("camera_plan")] if isinstance(row, dict) else []
    return any(isinstance(row, dict) and row.get("camera_grammar") == "CAMERA_GRAMMAR_V1" for row in rows)


def _plain_en(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split()).strip().rstrip(".;,")
    if not text or _CJK.search(text):
        return ""
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;")


def _director_subjects(
    unit: dict[str, Any], plan: dict[str, Any],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    """(people [(label, wardrobe)], beings [(label, look)], plain prop labels) of the unit, English only."""
    labels = _entity_labels(unit, plan)
    wardrobe = {}
    for row in (unit.get("wardrobe_contract") or {}).get("characters") or []:
        desc = _plain_en(row.get("authored_description")) or _plain_en(
            ", ".join(v for v in (_plain_en(row.get(k), 80) for k in _WARDROBE_FIELDS) if v)
        ) or _plain_en(row.get("appearance_ch1"))
        for key in (row.get("character_id"), row.get("character")):
            if key:
                wardrobe.setdefault(str(key), desc)
    people: dict[str, str] = {}
    beings: dict[str, str] = {}
    props: list[str] = []
    for spec in unit.get("ordered_prompt_specs") or []:
        for member in spec.get("cast") or []:
            if str(member.get("face_visibility") or "") == "OFFSCREEN_VOICE_ONLY":
                continue
            cid = str(member.get("character_id") or "")
            label = labels.get(cid) or _plain_en(member.get("character"), 80)
            if label and label not in people:
                people[label] = wardrobe.get(cid) or wardrobe.get(str(member.get("character") or "")) or ""
        for row in spec.get("props") or []:
            label = _plain_en(row.get("prop"), 80)
            if not label:
                continue
            if not is_being_prop(row):
                props += [label] if label not in props else []
                continue
            card = row.get("creature_card") or {}
            gait = {"biped": "moves upright on two legs", "quadruped": "moves on four legs"}.get(
                str(card.get("locomotion") or "").strip().lower(), "")
            eyes = _plain_en(card.get("eye_color"), 60)
            look = [_plain_en(row.get("note")), gait,
                    f"eyes: {eyes}" if eyes and eyes.lower() not in {"none", "n/a", "no eyes"} else ""]
            beings.setdefault(label, "; ".join(v for v in look if v))
    return list(people.items()), list(beings.items()), props


def _director_roster(people: list[tuple[str, str]], beings: list[tuple[str, str]], *, crowd: bool,
                     compact: bool) -> str:
    names = [label for label, _ in people] + [label for label, _ in beings]
    if not names:
        return ""
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    parts = [("Named subjects: " if crowd else "The only subjects in this clip are ") + joined]
    parts += [f"{label} wears {desc}" for label, desc in people if desc and not compact]
    parts += [f"{label} is a non-human subject, not a prop" + (f": {look}" if look and not compact else "")
              for label, look in beings]
    if len(names) > 1:
        parts.append(_NO_TRANSFER)
    if not crowd:
        parts.append(_NO_EXTRAS)
    return "cast_roster: " + ". ".join(parts) + "."


def _camera(plan: dict[str, Any]) -> str:
    """Legacy unit camera line (gate off).  Kept byte-identical."""
    family = str(plan.get("motion_family") or "STATIC").upper()
    direction = str(plan.get("motion_direction") or "NONE").upper()
    scale = str(plan.get("shot_scale") or "MEDIUM").upper()
    suffix = _optical(plan) + _camera_grammar_clause(plan)
    return f"shot scale={scale}; {_MOTION_MAPPING.get(family, family)}; direction={direction}; execute the declared move once{suffix}"

# ---------------------------------------------------------------------------
# Shot-scope upgrade (configs/PROMPT_SHOT_SCOPE_POLICY_V1.json).  Everything
# below is consulted only when ``shot_scope_active(unit, plan)`` is True; with
# the gate off the renderer output is byte-identical to the legacy path.
# ---------------------------------------------------------------------------

SHOT_SCOPE_SCHEMA = "qingshan.h3_shot_scope.v1_entity_beat_bound"
_CJK = re.compile(r"[㐀-鿿]")
_BODY_PART_WORDS = {
    "HAND": "hand", "HANDS": "hands", "PAW": "paw", "PAWS": "paws",
    "ARM": "arm", "ARMS": "arms", "LEG": "legs", "LEGS": "legs",
    "FOOT": "foot", "FEET": "feet", "TAIL": "tail", "BACK": "back",
    "TORSO": "torso", "SHOULDER": "shoulder", "SHOULDERS": "shoulders",
}
_PART_ONLY = re.compile(r"([A-Z]+(?:_AND_[A-Z]+)*)_ONLY(?:_FACE_OUT_OF_FRAME)?")
_VISIBILITY_FIELDS = ("visible_body_range", "visible_extent", "face_visibility")
_CUT_TRANSITION_MODES = {"MOTIVATED_CUT", "REACTION_CUT", "MATCH_CUT", "HARD_CUT"}
_CONTINUOUS_TRANSITION_MODES = {
    "CONTINUOUS_ACTION", "CAMERA_REFRAME", "PAN_REVEAL", "OCCLUSION_REVEAL", "CONTINUOUS_MOVE",
}
_CAMERA_TEXT_FIELDS = ("start_framing", "end_framing", "follow_subject", "subject_to_keep")


def shot_scope_active(unit: dict[str, Any], plan: dict[str, Any] | None = None) -> bool:
    """The single per-episode/per-model switch, read from the shared policy."""
    episode = unit.get("episode") or unit.get("unit_id") or (plan or {}).get("unit_id")
    return shot_scope_active_for(episode, unit.get("model") or "MiniMax-H3")


def partial_visibility_part(value: Any) -> str | None:
    """Return the visible part for an explicit partial-visibility marker.

    ``None`` means "not a partial declaration" (including a missing value, which
    must never be read as a face prohibition).  ``""`` means the face is declared
    out of frame without naming the visible part.
    """
    raw = str(value or "").strip().upper()
    if not raw:
        return None
    match = _PART_ONLY.fullmatch(raw)
    if match:
        tokens = match.group(1).split("_AND_")
        if any(token in _BODY_PART_WORDS for token in tokens):
            return " and ".join(_BODY_PART_WORDS.get(token, token.lower()) for token in tokens)
    if "FACE_OUT_OF_FRAME" in raw:
        return ""
    return None


def _english_label(value: Any) -> str:
    label = str(value or "").strip()
    return "" if not label or _CJK.search(label) else label


def _entity_labels(unit: dict[str, Any], plan: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    sources = [
        *((unit.get("provider_scope_projection") or {}).get("reference_identity_bindings") or []),
        *(unit.get("reference_image_sequence") or []),
        *((plan.get("h3_crossmodal_speaker_binding") or {}).get("bindings") or []),
    ]
    for row in sources:
        cid = str(row.get("entity_id") or row.get("character_id") or "").strip()
        label = _english_label(row.get("provider_entity_label"))
        if cid and label and cid not in labels:
            labels[cid] = label
    return labels


def beat_visibility_scopes(unit: dict[str, Any], plan: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Per beat, the entities whose visible range is *explicitly* partial.

    Sources (all already authored upstream; nothing is defaulted):
    ``ordered_prompt_specs[i].role_semantic_disambiguation.entity_visible_extent``,
    ``ordered_prompt_specs[i].cast[].visible_body_range|visible_extent|face_visibility``,
    ``plan.role_bindings[i].entity_face_visibility`` and
    ``provider_scope_projection.beats[i].entities[].visible_extent`` (index-aligned only).
    """
    beats = (plan.get("action_ir") or {}).get("causal_chains") or plan.get("beats") or []
    specs = unit.get("ordered_prompt_specs") or []
    roles = plan.get("role_bindings") or []
    scope_beats = (unit.get("provider_scope_projection") or {}).get("beats") or []
    if len(scope_beats) != len(beats):
        scope_beats = []
    labels = _entity_labels(unit, plan)
    result: list[list[dict[str, Any]]] = []
    for index in range(len(beats)):
        declared: list[tuple[str, str, str]] = []
        spec = specs[index] if index < len(specs) else {}
        role = spec.get("role_semantic_disambiguation") or {}
        for cid, value in (role.get("entity_visible_extent") or {}).items():
            declared.append((str(cid), str(value), "role_semantic_disambiguation.entity_visible_extent"))
        for cast in spec.get("cast") or []:
            cid = str(cast.get("character_id") or "").strip()
            for field in _VISIBILITY_FIELDS:
                if cid and cast.get(field):
                    declared.append((cid, str(cast[field]), f"cast.{field}"))
        role_binding = roles[index] if index < len(roles) else {}
        for cid, value in (role_binding.get("entity_face_visibility") or {}).items():
            declared.append((str(cid), str(value), "plan.role_bindings.entity_face_visibility"))
        if scope_beats:
            for row in scope_beats[index].get("entities") or []:
                if row.get("entity_id") and row.get("visible_extent"):
                    declared.append((str(row["entity_id"]), str(row["visible_extent"]),
                                     "provider_scope_projection.beats.entities.visible_extent"))
        rows: dict[str, dict[str, Any]] = {}
        for cid, value, source in declared:
            part = partial_visibility_part(value)
            if part is None or cid in rows:
                continue
            rows[cid] = {
                "beat_index": index + 1,
                "entity_id": cid,
                "label": labels.get(cid, ""),
                "declared_value": value,
                "part": part,
                "source": source,
            }
        result.append(list(rows.values()))
    return result


def _visible_speaker_ids(plan: dict[str, Any]) -> list[set[str]]:
    """Per beat, the entity ids/labels that speak with visible lip-sync."""
    beats = (plan.get("action_ir") or {}).get("causal_chains") or plan.get("beats") or []
    rows = (plan.get("h3_crossmodal_speaker_binding") or {}).get("bindings") or []
    by_speaker = {str(row.get("speaker") or "").strip(): row for row in rows}
    result: list[set[str]] = []
    for beat in beats:
        speaker = str(beat.get("dialogue") or "").partition("：")[0].strip()
        row = by_speaker.get(speaker) if beat.get("dialogue") else None
        names: set[str] = set()
        if row and row.get("visible_speaker"):
            for key in ("character_id", "entity_id", "provider_entity_label"):
                if row.get(key):
                    names.add(str(row[key]))
        result.append(names)
    return result


def partial_clause(label: str, part: str) -> str:
    """The one canonical, entity-named partial-visibility clause."""
    if part:
        return (
            f"{label}: only {label}'s {part} in frame during this beat, "
            f"do not reveal {label}'s face or full body"
        )
    return f"{label}: do not reveal {label}'s face during this beat, {label}'s face stays out of frame"


def _beat_scope_clauses(
    uid: str, scopes: list[dict[str, Any]], speakers: set[str], beat_index: int,
) -> tuple[str, dict[str, str]]:
    clauses: list[str] = []
    evidence: dict[str, str] = {}
    for row in scopes:
        if row["entity_id"] in speakers or (row["label"] and row["label"] in speakers):
            raise ValueError(
                f"{uid}:H3_SHOT_SCOPE_CONFLICT:BEAT.{beat_index}:{row['entity_id']}:"
                "VISIBLE_LIP_SYNC_SPEAKER_DECLARED_PARTIAL"
            )
        if not row["label"]:
            raise ValueError(
                f"{uid}:H3_PARTIAL_VISIBILITY_ENGLISH_LABEL_MISSING:BEAT.{beat_index}:{row['entity_id']}"
            )
        clause = partial_clause(row["label"], row["part"])
        clauses.append(clause)
        evidence[f"BEAT.{beat_index}.VISIBILITY.{row['entity_id']}"] = clause
    if not clauses:
        return "", evidence
    return " Visibility for this beat only: " + "; ".join(clauses) + ".", evidence


def _camera_english(
    uid: str, shot_label: str, camera_plan: dict[str, Any], english: dict[str, Any], failures: list[str],
) -> dict[str, str]:
    """Resolve framing text in English; never invent and never leak CJK.

    A source field that exists only in Chinese (no ``<field>_en`` on the camera
    plan and no English-contract ``camera_plan``/``camera_plans`` entry) is not
    serialized; it is recorded in ``failures`` and surfaced in the receipt as
    ``untranslated_fields`` so the submit gate can decide, without breaking a
    line that has not yet authored English framing.
    """
    values: dict[str, str] = {}
    for key in _CAMERA_TEXT_FIELDS:
        source = camera_plan.get(key)
        value = english.get(key) or camera_plan.get(f"{key}_en")
        if not value and source and not _CJK.search(str(source)):
            value = source
        value = str(value or "").strip().rstrip(".; ")
        if value and _CJK.search(value):
            value = ""
        if source and not value:
            failures.append(f"{uid}:H3_CAMERA_FIELD_ENGLISH_MISSING:{shot_label}:{key}")
        if value:
            values[key] = value
    return values


def _camera_scoped(camera_plan: dict[str, Any], english: dict[str, str]) -> str:
    family = str(camera_plan.get("motion_family") or "STATIC").upper()
    direction = str(camera_plan.get("motion_direction") or "NONE").upper()
    scale = str(camera_plan.get("shot_scale") or "MEDIUM").upper()
    parts = [f"shot scale={scale}"]
    if camera_plan.get("camera_height"):
        parts.append(f"camera height={str(camera_plan['camera_height']).upper()}")
    if camera_plan.get("camera_side"):
        parts.append(f"camera side={str(camera_plan['camera_side']).upper()}")
    start, end = english.get("start_framing"), english.get("end_framing")
    if camera_plan.get("camera_grammar") == "CAMERA_GRAMMAR_V1":  # boilerplate framing says nothing
        start, end = (None if value and _BOILERPLATE_FRAMING.match(value) else value for value in (start, end))
    if family in {"STATIC", "LOCKED"}:
        parts.append("locked camera with no camera movement")
        if start:
            parts.append(f"hold the framing: {start}")
        if end and end != start:
            parts.append(f"end framing: {end}")
    else:
        parts.append(f"{_MOTION_MAPPING.get(family, family)}; direction={direction}")
        if english.get("follow_subject"):
            parts.append(f"the camera follows {english['follow_subject']}")
        if english.get("subject_to_keep"):
            parts.append(f"keep {english['subject_to_keep']} in frame throughout the move")
        if start:
            parts.append(f"start framing: {start}")
        if end:
            parts.append(f"the move lands on and holds the end framing: {end}")
    return "; ".join(parts) + _optical(camera_plan) + _camera_grammar_clause(camera_plan)


def _shot_rows(unit: dict[str, Any], plan: dict[str, Any], action_beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    uid = str(plan["unit_id"])
    roles = plan.get("role_bindings") or []
    specs = unit.get("ordered_prompt_specs") or []

    def shot_id(index: int) -> str:
        role = roles[index] if index < len(roles) else {}
        spec = specs[index] if index < len(specs) else {}
        return str(role.get("shot_id") or spec.get("shot_id") or "").strip()

    plan_rows = plan.get("per_shot_camera_plans") or []
    unit_rows = unit.get("per_shot_camera_plans") or []
    if plan_rows:
        if len(plan_rows) == len(action_beats):
            return [{"shot_id": str(row.get("shot_id") or shot_id(i)), "start": beat["start_seconds"],
                     "end": beat["end_seconds"], "camera_plan": row.get("camera_plan") or {}}
                    for i, (row, beat) in enumerate(zip(plan_rows, action_beats))]
        return [{"shot_id": str(row.get("shot_id") or ""), "start": row["start_seconds"],
                 "end": row["end_seconds"], "camera_plan": row.get("camera_plan") or {}} for row in plan_rows]
    if unit_rows:
        if len(unit_rows) != len(action_beats):
            raise ValueError(f"{uid}:H3_PER_SHOT_CAMERA_COUNT_MISMATCH:{len(unit_rows)}!={len(action_beats)}")
        return [{"shot_id": str(row.get("shot_id") or shot_id(i)), "start": beat["start_seconds"],
                 "end": beat["end_seconds"],
                 "camera_plan": row.get("camera_plan") if isinstance(row.get("camera_plan"), dict) else row}
                for i, (row, beat) in enumerate(zip(unit_rows, action_beats))]
    return []


def _shot_boundary(unit: dict[str, Any], index: int, previous: dict[str, Any], current: dict[str, Any], uid: str) -> str:
    contracts = unit.get("internal_transition_contracts") or []
    mode = str((contracts[index] or {}).get("transition_mode") or "").upper() if index < len(contracts) else ""
    if mode in _CUT_TRANSITION_MODES or (not mode and previous["shot_id"] and current["shot_id"]
                                         and previous["shot_id"] != current["shot_id"]):
        return "hard cut to a new framing"
    if mode in _CONTINUOUS_TRANSITION_MODES or (not mode and previous["shot_id"]
                                                and previous["shot_id"] == current["shot_id"]):
        return "no cut; one continuous camera move into this framing"
    raise ValueError(f"{uid}:H3_SHOT_BOUNDARY_UNDECLARED:{index + 1}->{index + 2}")


def _camera_section(
    unit: dict[str, Any], plan: dict[str, Any], contract: dict[str, Any], action_beats: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    uid = str(plan["unit_id"])
    rows = _shot_rows(unit, plan, action_beats)
    if not rows:
        camera_plan = plan.get("camera_plan") or {}
        failures: list[str] = []
        english = _camera_english(uid, "UNIT", camera_plan, contract.get("camera_plan") or {}, failures)
        return _camera_scoped(camera_plan, english), [{
            "shot_id": "UNIT", "fields": sorted(english), "untranslated_fields": failures,
        }]
    translated = contract.get("camera_plans") or contract.get("per_shot_camera_plans") or []
    lines = ["per-shot camera; each line applies only to its own time window"]
    receipt = []
    for index, row in enumerate(rows):
        english_source = translated[index] if index < len(translated) and isinstance(translated[index], dict) else {}
        label = row["shot_id"] or f"SHOT_{index + 1}"
        missing: list[str] = []
        english = _camera_english(uid, label, row["camera_plan"], english_source, missing)
        boundary = "opening shot" if index == 0 else _shot_boundary(unit, index - 1, rows[index - 1], row, uid)
        lines.append(
            f"SHOT {index + 1} [{float(row['start']):g}s-{float(row['end']):g}s] ({boundary}): "
            + _camera_scoped(row["camera_plan"], english)
        )
        receipt.append({
            "shot_id": label, "boundary": boundary, "fields": sorted(english), "untranslated_fields": missing,
        })
    return "\n".join(lines), receipt


# ---------------------------------------------------------------------------
# Final-text checkers, importable by the submit boundary gate.
# ---------------------------------------------------------------------------

_BEAT_LINE = re.compile(r"^\[(\d+(?:\.\d+)?)s-(\d+(?:\.\d+)?)s\] Start from ")
_FACE_FORBID = re.compile(
    r"(cropped body parts|\bits face\b|do not (?:widen the frame to )?reveal\b[^.;]*\b(?:face|full body)"
    r"|face out of frame|(?:face|mouth)[^.;]{0,40}\b(?:outside|out of) (?:the )?frame)",
    re.IGNORECASE,
)
_NAMED_FORBID = re.compile(r"do not reveal (.+?)'s face")


def partial_clause_leaks(text: str, plan: dict[str, Any], unit: dict[str, Any] | None = None) -> list[str]:
    """Return every partial-visibility clause that escapes its declared scope.

    A face/full-body prohibition is legal only inside a timed beat line, only
    when it names an entity whose visible range is explicitly partial in that
    beat, and never for that beat's visible lip-sync speaker.  Generic wording
    ("its face", "cropped body parts") and prohibitions outside beat lines are
    always leaks.  A declared partial entity with no clause is reported as
    ``PARTIAL_CLAUSE_MISSING``.  Empty list == clean.
    """
    unit = unit or {}
    scopes = beat_visibility_scopes(unit, plan)
    speakers = _visible_speaker_ids(plan)
    labels = _entity_labels(unit, plan)
    speaker_labels = [
        {labels.get(value, value) for value in names} | names for names in speakers
    ]
    findings: list[str] = []
    beat_number = 0
    for line in text.splitlines():
        is_beat = bool(_BEAT_LINE.match(line))
        if is_beat:
            beat_number += 1
        expected = scopes[beat_number - 1] if is_beat and beat_number <= len(scopes) else []
        expected_labels = {row["label"] for row in expected if row["label"]}
        found_labels: set[str] = set()
        for fragment in re.split(r"(?<=[.;])\s+", line):
            if not _FACE_FORBID.search(fragment):
                continue
            if not is_beat:
                findings.append(f"PARTIAL_CLAUSE_OUTSIDE_BEAT_SCOPE:{fragment.strip()[:80]}")
                continue
            named = _NAMED_FORBID.search(fragment)
            if not named:
                findings.append(f"PARTIAL_CLAUSE_GENERIC_UNNAMED:BEAT.{beat_number}:{fragment.strip()[:80]}")
                continue
            label = named.group(1).strip()
            found_labels.add(label)
            if label not in expected_labels:
                findings.append(f"PARTIAL_CLAUSE_LEAK:BEAT.{beat_number}:{label}")
            if beat_number <= len(speaker_labels) and label in speaker_labels[beat_number - 1]:
                findings.append(f"PARTIAL_CLAUSE_VISIBLE_SPEAKER_CONFLICT:BEAT.{beat_number}:{label}")
        if is_beat:
            for label in sorted(expected_labels - found_labels):
                findings.append(f"PARTIAL_CLAUSE_MISSING:BEAT.{beat_number}:{label}")
    return list(dict.fromkeys(findings))


_MOVE_WORDS = re.compile(
    r"(execute the declared move|\bmove lands\b|\b(?:dolly|pan|truck|track|tilt|crane|arc|follow|push|pull)\b)",
    re.IGNORECASE,
)


def locked_camera_move_conflicts(text: str) -> list[str]:
    """Return camera entries that declare a locked camera and a move together."""
    match = re.search(r"^camera: (.*?)(?=^physical_continuity:)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return []
    findings = []
    for index, entry in enumerate(re.split(r"\n(?=SHOT \d+ )", match.group(1)), 1):
        instructions = re.sub(r"(?:hold the framing|start framing|end framing): [^;]*", "", entry)
        if "locked camera" in instructions and _MOVE_WORDS.search(instructions):
            findings.append(f"LOCKED_CAMERA_WITH_MOVE_INSTRUCTION:{index}:{entry.strip()[:80]}")
    return findings


DIALOGUE_LANGUAGE_TAGS = {"zh": "Chinese", "en": "English"}


def _dialogue_partition(raw: str, language: str = "zh") -> tuple[str, str, str]:
    """``speaker：words``; English dialogue may also use an ASCII colon."""
    speaker, separator, words = raw.partition("：")
    if not separator and language == "en":
        speaker, separator, words = raw.partition(":")
    return speaker, separator, words


def _beat(
    source: dict[str, Any], translated: dict[str, Any], *, dialogue_binding: dict[str, Any] | None,
    positive_single_subject: bool = False, language: str = "zh",
) -> tuple[str, dict[str, str]]:
    index = int(source["source_index"])
    prefix = f"BEAT.{index}"
    line = (
        f"[{source['start_seconds']:g}s-{source['end_seconds']:g}s] "
        f"Start from {translated['entry_state']}. Force origin: {translated.get('force_origin') or translated['entry_state']}. "
        f"{translated['primary_action']}"
    )
    interaction_mode = str(source.get("interaction_mode") or "NONE")
    interaction_label = {
        "CONTACT": "physical contact",
        "EVASION": "clear evasion",
        "THREAT_THRESHOLD": "pre-contact threat threshold",
    }.get(interaction_mode, "no person-to-person interaction")
    evidence = {
        f"{prefix}.ENTRY": translated["entry_state"],
        f"{prefix}.ACTION": translated["primary_action"],
        f"{prefix}.FORCE_ORIGIN": translated.get("force_origin") or translated["entry_state"],
        f"{prefix}.INTERACTION_MODE": interaction_label,
        f"{prefix}.EXIT": translated["exit_state"],
    }
    if source.get("contact_time_seconds") is not None:
        contact_time = f"{float(source['contact_time_seconds']):g}s"
        line += f" Interaction mode: {interaction_label}; the interaction point is reached at {contact_time}"
        evidence[f"{prefix}.CONTACT_TIME"] = contact_time
    elif interaction_mode != "NONE":
        # No contact timestamp, but the interaction mode is still required by the coverage gate.
        # Emit the label unconditionally so coverage can find it in the rendered text.
        line += f" Interaction mode: {interaction_label}"
    if source.get("contact_point"):
        line += f" at {translated['contact_point']}"
        evidence[f"{prefix}.CONTACT_POINT"] = translated["contact_point"]
    if source.get("primary_feedback"):
        primary_feedback = translated.get("primary_feedback") or translated.get("force_feedback")
        line += f"; primary feedback: {primary_feedback}"
        evidence[f"{prefix}.PRIMARY_FEEDBACK"] = primary_feedback
    translated_secondary = translated.get("secondary_feedback") or []
    for secondary_index, value in enumerate(translated_secondary, 1):
        line += f"; secondary feedback: {value}"
        evidence[f"{prefix}.SECONDARY_FEEDBACK.{secondary_index}"] = value
    line += f". End at {translated['exit_state']}."
    raw = str(source.get("dialogue") or "").strip()
    if raw:
        speaker, separator, words = _dialogue_partition(raw, language)
        if not separator or not words.strip() or dialogue_binding is None:
            raise ValueError(f"DIALOGUE_SPEAKER_BINDING_INVALID:{raw}")
        literal = f"<d>[{DIALOGUE_LANGUAGE_TAGS[language]}] {words.strip()}</d>"
        label = str(dialogue_binding["provider_entity_label"])
        subject = str(dialogue_binding["subject_token"])
        image_slot = str(dialogue_binding["image_slot"])
        speaker_slot = str(dialogue_binding["speaker_slot"])
        audio_slot = str(dialogue_binding["audio_slot"])
        if dialogue_binding.get("visible_speaker"):
            line += (
                f" {label} ({subject}, identity {image_slot}, lip owner {speaker_slot}, fixed voice {audio_slot}) "
                f"opens the mouth in sync and says exactly once {literal}."
            )
            if not positive_single_subject:
                line += " All other people keep their mouths closed."
        else:
            line += (
                f" Offscreen {label} ({subject}, identity reference {image_slot}, voice owner {speaker_slot}, "
                f"fixed voice {audio_slot}) says exactly once {literal}; "
                "do not show the offscreen speaker; all visible people keep their mouths closed."
            )
        evidence[f"{prefix}.DIALOGUE"] = literal
        pace = delivery_clause(source, "EN")
        if pace:
            line += " " + pace
            evidence[f"{prefix}.DIALOGUE_DELIVERY"] = pace
        evidence[f"{prefix}.DIALOGUE_SPEAKER"] = speaker.strip()
        evidence[f"{prefix}.CROSSMODAL_BINDING"] = (
            f"{subject}={image_slot}={speaker_slot}={audio_slot}"
        )
    if source.get("microexpression_cue"):
        line += f" Microexpression: {translated['microexpression_cue']}."
        evidence[f"{prefix}.MICROEXPRESSION"] = translated["microexpression_cue"]
    if source.get("body_sync_cue"):
        line += f" Body synchronization: {translated['body_sync_cue']}."
        evidence[f"{prefix}.BODY_SYNC"] = translated["body_sync_cue"]
    if source.get("internal_transition_after"):
        line += f" Then bridge into the next beat: {translated['internal_transition_after']}."
        evidence[f"{prefix}.INTERNAL_TRANSITION_AFTER"] = translated["internal_transition_after"]
    return line, evidence


#: Period lock for H3 units below visual_culture_contract.ACTIVE_FROM_EPISODE.  The qingshan block
#: (prompt_block_en) spells the qingshan profile's Northern-Song wuxia/armour prose; the SD2 renderer already
#: renders it only for the episodes that contract governs (sd2_provider_prompt_renderer._vc_prompt_block_for_unit),
#: but H3 rendered it for every unit — so a Qing-era Jiangnan NALU drama (2026-10-16) and the Song apothecary
#: of 青灯巷 E02 both got "Northern Song Chinese wuxia ... lamellar armor".  Below that episode the line's own
#: era comes from the references and the bound English facts; this lock only names what to avoid.
H3_NEUTRAL_PERIOD_LOCK = (
    "EAST-ASIAN PERIOD VISUAL LOCK: keep the period, architecture, dress and props exactly as the reference "
    "images and the described facts show; real materials, soft motivated light, muted natural palette. Never "
    "European medieval/Gothic, Western plate armor or knight helmets, heraldry, black-gold Western fantasy or "
    "game-poster light, teal-orange grade, or modern objects."
)


#: Lock for a line whose writer authored its own world (not an East-Asian period drama): the
#: references and bound facts still carry the era; nothing names a culture or bans modern objects.
#: Twelve Gazes E01 (2026-10-21, near-future English line) got the East-Asian period lock and its
#: semantic review failed 15 prompts for a field jacket and modern props the script requires.
H3_AUTHORED_WORLD_LOCK = (
    "WORLD VISUAL LOCK: keep the world, era, architecture, costume and props exactly as the reference "
    "images and the described facts show; real materials, soft motivated light, natural grade. Never drift "
    "into another era, culture or genre than the references show; no game-poster light, no teal-orange grade."
)


def authored_world(unit: dict[str, Any]) -> bool:
    """True when the H3 lock must follow the writer's own world instead of the East-Asian period lock.

    ``visual_culture_contract.era_lock`` decides when authored ("AUTHORED_WORLD" / "EAST_ASIAN_PERIOD");
    otherwise an English-dialogue line is an authored world and every Chinese line keeps the period lock.
    """
    vcc = unit.get("visual_culture_contract") if isinstance(unit.get("visual_culture_contract"), dict) else {}
    mode = str(vcc.get("era_lock") or "").strip().upper()
    if mode in {"AUTHORED_WORLD", "EAST_ASIAN_PERIOD"}:
        return mode == "AUTHORED_WORLD"
    return str(unit.get("dialogue_language") or "zh").strip().lower().startswith("en")


def h3_visual_culture_block(unit: dict[str, Any]) -> str:
    try:
        from tools.visual_culture_contract import ACTIVE_FROM_EPISODE
    except ImportError:  # pragma: no cover - direct-script import path
        from visual_culture_contract import ACTIVE_FROM_EPISODE
    match = re.search(r"(?:^|[^A-Z])E(\d+)", str(unit.get("episode") or unit.get("unit_id") or "").upper())
    if match and int(match.group(1)) >= ACTIVE_FROM_EPISODE:
        return visual_culture_prompt_block(unit.get("visual_culture_contract"))
    return H3_AUTHORED_WORLD_LOCK if authored_world(unit) else H3_NEUTRAL_PERIOD_LOCK


def render_h3_prompt(unit: dict[str, Any], plan: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    uid = str(plan["unit_id"])
    language = str(unit.get("dialogue_language") or "zh")
    if language not in DIALOGUE_LANGUAGE_TAGS:
        raise ValueError(f"{uid}:H3_DIALOGUE_LANGUAGE_UNSUPPORTED:{language}")
    profile = str(unit.get("h3_prompt_profile") or "").strip()
    # The image presubmit gate and the projection carry the same flag under two
    # other spellings; normalize so one value reaches all three.
    positive_single_subject = is_single_subject_mode(profile)
    tight_pov_single_subject = is_tight_pov_mode(profile)
    scoped = shot_scope_active(unit, plan)
    refs = unit.get("reference_images") or []
    if not refs or len(refs) > 9:
        raise ValueError(f"{uid}:H3_REFERENCE_COUNT_OUT_OF_RANGE:{len(refs)}")
    contract = require_h3_provider_english_contract(unit, plan)
    crossmodal = plan.get("h3_crossmodal_speaker_binding") or {}
    if crossmodal.get("status") not in {"PASS", "NOT_APPLICABLE"}:
        raise ValueError(";".join(crossmodal.get("failures") or [f"H3_CROSSMODAL_BINDING_INVALID:{uid}"]))
    crossmodal_rows = crossmodal.get("bindings") or []
    crossmodal_by_speaker = {
        str(row.get("speaker") or "").strip(): row for row in crossmodal_rows
    }
    reference_lines = []
    sequence_by_path = {
        str(row.get("path") or ""): row
        for row in unit.get("reference_image_sequence") or []
        if row.get("path") and str(row.get("entity_id") or "").startswith("CHAR-")
    }
    scope_bindings = {
        int(row["reference_index"]): row
        for row in (unit.get("provider_scope_projection") or {}).get("reference_identity_bindings") or []
        if row.get("reference_index") is not None
    }
    scope = unit.get("provider_scope_projection") or {}
    # Director units: a reference without its own provider label (e.g. the continuity-derived opening
    # frame) takes the same English name the unit's other bindings use, never the raw CHAR-* id.
    director_labels = _entity_labels(unit, plan) if director_active(unit, plan) else {}
    for index, raw_ref in enumerate(refs, 1):
        ref = raw_ref if isinstance(raw_ref, dict) else {"path": str(raw_ref)}
        # Index binding is authoritative.  Path lookup is compatibility-only:
        # different role references may legitimately share one source image.
        bound = scope_bindings.get(index) or sequence_by_path.get(str(ref.get("path") or ""), {})
        ref = {**bound, **ref}
        entity = str(ref.get("provider_entity_label")
                     or director_labels.get(str(ref.get("entity_id") or "").strip())
                     or ref.get("entity_id") or "").strip()
        role = str(ref.get("role") or "REFERENCE").strip()
        binding_role = str(bound.get("binding_role") or "")
        role_is_identity = binding_role == "IDENTITY" or (
            not binding_role
            and str(bound.get("entity_id") or ref.get("entity_id") or "").startswith("CHAR-")
        )
        if role in {"ADMITTED_NEW_EVENT_ENTRY_STATE", "PREVIOUS_UNIT_FINAL_FRAME", "IDENTITY_OR_PROP_REANCHOR"}:
            entity = ""
        if entity and not role_is_identity:
            # A geometry / location / prop plate: it carries no face, so it must
            # not be described as an identity lock.  Previously every binding was
            # rendered as "exclusive identity of X", which is what let a plate in
            # the wrong slot read as an identity anchor.
            reference_lines.append(
                f"@Image{index}: exclusive {role} reference for {entity}; bind only that declared role, "
                f"map geometry, material and scale only; define no face and never overwrite a named identity; role={role}."
            )
        elif entity:
            declared_count = int(
                (scope.get("visible_entity_instance_counts") or {}).get(str(ref.get("entity_id") or "")) or 1
            )
            if positive_single_subject:
                reference_lines.append(
                    f"@Image{index}: {entity} is SUBJECT_1; preserve this face, age, hair, body, wardrobe, "
                    f"opening pose and architectural background; role={role}."
                )
            elif scoped:
                reference_lines.append(
                    f"@Image{index}: exclusive identity of {entity}; lock this entity's face, age, hair, body and wardrobe; "
                    + instance_cardinality_clauses(entity, declared_count)[-1]
                    + f"; this reference alone does not put {entity} "
                    "in frame, presence and visible range follow each timed beat; "
                    f"never duplicate or assign it to another entity; role={role}."
                )
            else:
                reference_lines.append(
                    f"@Image{index}: exclusive identity of {entity}; lock this entity's face, age, hair, body and wardrobe; "
                    + instance_cardinality_clauses(entity, declared_count)[0]
                    + f"; never duplicate or assign it to another entity; "
                    f"role={role}."
                )
        elif index == 1:
            reference_lines.append(
                f"@Image{index}: opening composition, location, camera axis, pose and state; "
                "named identity references override uncertain faces; never copy a static pose."
            )
        else:
            reference_lines.append(
                f"@Image{index}: exclusive {role} reference; bind only that declared role and never overwrite a named identity."
            )
    translated_transition = contract.get("transition") or {}
    # A unit with no projection declares nothing, and the historical rendering
    # for that case is a zero population; several units below the projection
    # gate legitimately have none, so that case keeps its old meaning.  What is
    # no longer tolerated is a projection that exists and still fails to state
    # its population: the old code silently replaced the missing declaration
    # with a count derived from whatever bindings happened to be attached.
    if not scope:
        visible_total = 0
        background_total = 0
        unbound_total = 0
    elif "visible_living_entity_instance_total" not in scope:
        raise ValueError(f"{uid}:H3_PROVIDER_SCOPE_POPULATION_UNDECLARED")
    else:
        visible_total = int(scope.get("visible_living_entity_instance_total") or 0)
        background_total = int(scope.get("background_population_count") or 0)
        unbound_total = int(scope.get("unbound_visible_living_entity_count") or 0)
    if positive_single_subject:
        composition = positive_single_subject_composition_clause(tight_pov_single_subject)
        population_scope = (
            composition + "; the closed shallow architectural background preserves the opening image"
            if tight_pov_single_subject
            else composition + "; the shallow architectural background preserves the opening image"
        )
    else:
        population_scope = population_clause(
            visible_total,
            background_population_count=background_total,
            unbound_visible_living_entity_count=unbound_total,
            anonymous_role_descriptors=scope.get("anonymous_role_descriptors") or [],
        )
    source_transition = plan.get("transition") or {}
    description: list[str] = []
    content_window = content_window_clause(plan, "EN")
    if content_window:
        description.append(content_window)
    clause_evidence = {
        "ANCHOR.IDENTITY_PROP": contract["identity_prop_fact"],
        "ANCHOR.SPACE_WEATHER": contract["space_weather_fact"],
    }
    persistent_state_lock = str(contract.get("persistent_state_lock") or "").strip()
    if content_window:
        clause_evidence["PACING.CONTENT_WINDOW"] = content_window
    if persistent_state_lock:
        clause_evidence["CONTINUITY.PERSISTENT_STATE"] = persistent_state_lock
    shot_state_locks = [str(value).strip() for value in contract.get("shot_state_locks") or []]
    for index, value in enumerate(shot_state_locks, 1):
        clause_evidence[f"CONTINUITY.SHOT_STATE.{index}"] = value
    if source_transition.get("incoming"):
        incoming = str(translated_transition.get("incoming") or "").strip()
        if not incoming:
            raise ValueError(f"H3_ENGLISH_CONTRACT_FIELD_MISSING:{uid}:transition.incoming")
        description.append(f"Open directly from the inherited state: {incoming}. Do not reset or replay it.")
        clause_evidence["TRANSITION.INCOMING"] = incoming
    action_beats = (plan.get("action_ir") or {}).get("causal_chains") or plan["beats"]
    visibility_scopes = beat_visibility_scopes(unit, plan) if scoped else []
    visible_speakers = _visible_speaker_ids(plan) if scoped else []
    for beat_number, (source, translated) in enumerate(zip(action_beats, contract["beats"]), 1):
        dialogue_binding = None
        if source.get("dialogue"):
            speaker = _dialogue_partition(str(source.get("dialogue") or ""), language)[0].strip()
            dialogue_binding = crossmodal_by_speaker.get(speaker)
            if dialogue_binding is None:
                raise ValueError(f"H3_DIALOGUE_CROSSMODAL_BINDING_MISSING:{uid}:{speaker}")
        line, evidence = _beat(
            source,
            translated,
            dialogue_binding=dialogue_binding,
            positive_single_subject=positive_single_subject,
            language=language,
        )
        if scoped:
            scope_text, scope_evidence = _beat_scope_clauses(
                uid, visibility_scopes[beat_number - 1], visible_speakers[beat_number - 1], beat_number
            )
            line += scope_text
            evidence.update(scope_evidence)
            if dialogue_binding is not None and dialogue_binding.get("visible_speaker"):
                keep = (
                    f"{dialogue_binding['provider_entity_label']}'s face and mouth stay readable in frame "
                    "while speaking in this beat"
                )
                line += f" {keep}."
                evidence[f"BEAT.{beat_number}.SPEAKER_FACE_VISIBLE"] = keep
        description.append(line)
        clause_evidence.update(evidence)
    # Spatial staging: who faces where, where the listener stands and where the
    # eyes go.  Only emitted for the role rows that declared it; an absent
    # declaration renders nothing and never defaults to mutual eye contact.
    spatial_roles = [
        (role, translated_row)
        for role, translated_row in zip(
            [role for role in (plan.get("role_bindings") or []) if role.get("spatial_dialogue")],
            contract.get("spatial_dialogue") or [],
        )
    ]
    labels = _entity_labels(unit, plan)
    for index, (role, translated_row) in enumerate(spatial_roles, 1):
        speaker = str(role.get("dialogue_speaker") or "")
        listener = str(role.get("dialogue_listener") or "")
        clause = spatial_dialogue_contract.render_en(
            role, translated=translated_row,
            speaker_label=labels.get(str(role.get("shot_id") or ""), speaker),
            listener_label=labels.get(str(role.get("shot_id") or ""), listener),
        )
        if clause:
            description.append(f"Staging: {clause}.")
            clause_evidence[f"SPATIAL_DIALOGUE.{index}"] = clause
    if source_transition.get("outgoing"):
        outgoing = str(translated_transition.get("outgoing") or "").strip()
        if not outgoing:
            raise ValueError(f"H3_ENGLISH_CONTRACT_FIELD_MISSING:{uid}:transition.outgoing")
        description.append(f"End by completing this handoff: {outgoing}. Keep natural micro-motion and the sound tail.")
        clause_evidence["TRANSITION.OUTGOING"] = outgoing

    translated_sounds = contract.get("sounds") or {}
    sound_rows: list[str] = []
    for key in ("ambience", "foley", "action_sound"):
        source_rows = (plan.get("sounds") or {}).get(key) or []
        provider_rows = translated_sounds.get(key) or []
        if len(provider_rows) != len(source_rows):
            raise ValueError(f"H3_ENGLISH_CONTRACT_SOUND_COUNT:{uid}:{key}:{len(provider_rows)}!={len(source_rows)}")
        for index, value in enumerate(provider_rows, 1):
            value = str(value).strip()
            sound_rows.append(value)
            clause_evidence[f"SOUND.{key.upper()}.{index}"] = value

    source_environment = plan.get("environment_motion") or []
    translated_environment = contract.get("environment_motion") or []
    if len(translated_environment) != len(source_environment):
        raise ValueError(
            f"H3_ENGLISH_CONTRACT_ENVIRONMENT_COUNT:{uid}:"
            f"{len(translated_environment)}!={len(source_environment)}"
        )
    environment_rows = [str(value).strip() for value in translated_environment]
    for index, value in enumerate(environment_rows, 1):
        clause_evidence[f"ENVIRONMENT_MOTION.{index}"] = value

    voice_rows = []
    for index, row in enumerate(crossmodal_rows, 1):
        line = (
            f"{row['provider_entity_label']} is {row['subject_token']} with identity {row['image_slot']}, "
            f"lip owner {row['speaker_slot']} and exclusive voice {row['audio_slot']}; never reassign this chain"
        )
        voice_rows.append(line)
        # Keep the semantic-coverage key ordinal stable while the actual
        # identity/audio relation is resolved by canonical character id.
        clause_evidence[f"VOICE_BINDING.{index}"] = line
    if not any(beat.get("dialogue") for beat in action_beats):
        vocal_rule = (
            "SUBJECT_1 keeps a naturally closed mouth for the complete clip."
            if positive_single_subject
            else "No human speech event; every visible person keeps the mouth closed for the entire clip."
        )
    else:
        vocal_rule = (
            "SPEAKER_1 performs the literal inside the d-tag as synchronized native speech."
            if positive_single_subject
            else "Only literals inside d-tags may become speech; never vocalize machine metadata."
        )

    camera_receipt: list[dict[str, Any]] = []
    if scoped:
        camera, camera_receipt = _camera_section(unit, plan, contract, action_beats)
    else:
        camera = _camera(plan.get("camera_plan") or {})
    clause_evidence["CAMERA.PLAN"] = camera
    physical_rules = []
    if plan.get("interaction_topology_required"):
        topology = (
            "Every visible hand has one named owner and remains anatomically connected through shoulder, "
            "upper arm, elbow, forearm, wrist, palm, and fingers; no isolated limb, extra limb, severed limb, "
            "reversed joint, fixed-surface penetration, or owner swap"
        )
        physical_rules.append(topology)
        clause_evidence["PHYSICAL.INTERACTION_TOPOLOGY"] = topology
    if plan.get("combat_execution_required"):
        combat = (
            "Execute each combat beat in real time as setup and displacement, one contact or clear evasion, "
            "force feedback, and a new position; no posing, push-hands contact, or still-frame interpolation"
        )
        physical_rules.append(combat)
        clause_evidence["COMBAT.EXECUTION_RULE"] = combat
    wuxia_profile = plan.get("wuxia_combat_profile_selection") or {}
    if wuxia_profile.get("status") == "SELECTED":
        profile_clause = (
            "Wuxia action-camera profile [INFERRED_RECONSTRUCTED_NOT_ORIGINAL]: "
            + str(wuxia_profile.get("prompt_module_en") or "")
            + " This profile only expresses the existing Action-IR and must not add moves, hits, injuries, "
            "effects, winners, losers, dialogue, or story outcomes"
        )
        physical_rules.append(profile_clause)
        clause_evidence["COMBAT.WUXIA_PROFILE_MODULE"] = profile_clause
    # Run the established explicit-content validator.  The returned Chinese
    # prose is intentionally not serialized; H3 receives an equivalent English
    # model-specific styling clause only for explicitly confirmed adults.
    adult_style_source = h3_adult_female_visual_block(unit)
    adult_style = (
        "For every explicitly confirmed adult woman, use a mature, naturally fuller silhouette with "
        "role-appropriate fitted tailoring, a clear waistline, complete period clothing, and tasteful non-explicit styling"
        if adult_style_source else ""
    )
    negatives = (
        [
            "TEXT-FREE FRAME with no captions, labels, signs, letters, numbers, UI, logos, or watermark",
            "Preserve the bound face, wardrobe, body anatomy, map, dry weather, lighting direction, voice and prop ownership",
            "Natural real-time movement without freeze, loop, pose interpolation, unmotivated orbit, or discontinuous spatial jump",
        ]
        if positive_single_subject
        else list(contract.get("negative_constraints") or [])
    )
    negatives.extend([
        ANTI_TEXT,
        "No identity, wardrobe, prop ownership, map, weather, lighting-direction, or voice drift",
        "No freeze, loop, pose interpolation, unmotivated orbit, or discontinuous spatial jump",
    ])
    if wuxia_profile.get("status") == "SELECTED":
        negatives.extend(wuxia_profile.get("negative_constraints_en") or [])
    profile_constraints = {
        "H3_CONCISE_QUOTED_DIALOGUE_REPAIR_V1": "Only the bound named speaker may speak; never add, translate, repeat, or visualize dialogue",
        "H3_MINIMAL_AUDIO_RESCUE_V1": "Repair only the declared native sound; do not rewrite identity, map, action, framing, or timing",
        "H3_ENGLISH_MACHINE_AUDIO_RESCUE_V1": "Never vocalize machine metadata; only tagged source-language dialogue may become speech",
        "H3_CONCISE_COMBAT_REPAIR_V1": "Execute one physical force chain; no push-hands contact, posing, or reference-frame interpolation",
        "H3_OFFICIAL_REF2VA_V1": "References bind only their declared identity, location, prop, and state roles",
        "H3_POSITIVE_SINGLE_SUBJECT_V1": "SUBJECT_1 remains the single composed human figure throughout the shot",
        "H3_TIGHT_POV_SINGLE_SUBJECT_V1": (
            "SUBJECT_1 remains centered in the tight point-of-view close-up throughout the shot; "
            "the frame stays closed on this face and upper torso"
        ),
    }
    if profile in profile_constraints:
        negatives.append(profile_constraints[profile])
    genre = "live-action short drama"
    roster_variants = [""]
    if director_active(unit, plan) and not positive_single_subject:
        people, beings, plain_props = _director_subjects(unit, plan)
        if not people and not beings:
            genre = (f"a single photographic insert shot of {' and '.join(plain_props) or 'the object described below'}; "
                     "no people, no hands, no body parts")
        else:
            crowd = bool(background_total or unbound_total or scope.get("anonymous_role_descriptors"))
            roster_variants = [_director_roster(people, beings, crowd=crowd, compact=compact)
                               for compact in (False, True)] + [""]

    def assemble(roster: str) -> str:
        return "\n".join([
        "subject_definitions:", *reference_lines,
        "population_scope: " + population_scope + ".",
        *([roster] if roster else []),
        f"summary: [reference generation + keyframe completion] {plan['duration_seconds']:g}s vertical 9:16 {genre}; {contract['identity_prop_fact']}; {contract['space_weather_fact']}.",
        "visual_culture: " + h3_visual_culture_block(unit),
        *( ["persistent_state_lock: " + persistent_state_lock + "."] if persistent_state_lock else [] ),
        *( ["shot_state_chain:", *[f"SHOT_{index}: {value}." for index, value in enumerate(shot_state_locks, 1)]] if shot_state_locks else [] ),
        "retention_analysis: @Image1 locks the opening identity and space; later references bind only their declared identity, prop, or result state.",
        "detailed_description:", *description,
        "camera: " + camera + ".",
        "physical_continuity: " + ("; ".join(physical_rules) or "Preserve continuous body ownership and real physical causality") + ".",
        *( ["adult_woman_style: " + adult_style + "."] if adult_style else [] ),
        "environment_motion: " + ("; ".join(environment_rows) or "Background life moves naturally only when motivated by the story; never freeze into a still image") + ".",
        "overall_soundscape: " + ("; ".join(sound_rows) or "Native location ambience, cloth, foley, action contact, and declared dialogue only") + ".",
        "voice_binding: " + ("; ".join(voice_rows) or "No dialogue voice reference is required") + ".",
        "vocal_rule: " + vocal_rule,
        "non_diegetic_music: none unless the structured audio profile explicitly binds a cue.",
        "negative_constraints: " + "; ".join(dict.fromkeys(value.strip().rstrip(".; ") for value in negatives if value.strip())) + ".",
    ]) + "\n"

    # the director roster is trimmed (looks dropped, then the whole line) rather than ever failing the limit
    for roster in roster_variants:
        text = assemble(roster)
        if len(text) <= _PROVIDER_RUNE_LIMIT:
            break
    boundary = validate_provider_prompt_boundary(text, source_id=uid, model_family="MINIMAX_H3")
    h3_boundary = validate_h3_provider_text_boundary(text, source_id=uid)
    failures = [*boundary["failures"], *h3_boundary["failures"]]
    if failures:
        raise ValueError(";".join(failures))
    coverage = build_semantic_coverage_receipt(
        plan=plan,
        prompt_text=text,
        model_family="MINIMAX_H3",
        clause_evidence=clause_evidence,
    )
    if coverage["status"] != "PASS":
        raise ValueError(";".join(coverage["failures"]))
    shot_scope_receipt: dict[str, Any] = {}
    if scoped:
        scope_failures = [*partial_clause_leaks(text, plan, unit), *locked_camera_move_conflicts(text)]
        if scope_failures:
            raise ValueError(f"{uid}:H3_SHOT_SCOPE_SELF_CHECK:" + ";".join(scope_failures))
        shot_scope_receipt = {"shot_scope": {
            "schema": SHOT_SCOPE_SCHEMA,
            "status": "PASS",
            "partial_visibility_rules": [row for rows in visibility_scopes for row in rows],
            "camera_shots": camera_receipt,
        }}
    return text, {
        "schema": SCHEMA,
        "status": "PASS",
        "unit_id": uid,
        "model_family": "MINIMAX_H3",
        "h3_prompt_profile": profile or "STANDARD",
        "immutable_contract_sha256": plan["immutable_contract_sha256"],
        "execution_semantics_sha256": plan["execution_semantics_sha256"],
        "camera_language_selection": plan["camera_language_selection"],
        "wuxia_combat_profile_selection": wuxia_profile,
        "motion_density_gate": plan["motion_density_gate"],
        "provider_semantic_coverage_receipt": coverage,
        "provider_boundary": boundary,
        "h3_english_boundary": h3_boundary,
        "prompt_budget": measure_prompt(text, source_id=uid, model_family="MINIMAX_H3"),
        **shot_scope_receipt,
    }
