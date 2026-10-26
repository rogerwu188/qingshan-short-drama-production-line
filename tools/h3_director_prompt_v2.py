#!/usr/bin/env python3
"""DIRECTOR_PROMPT_V2: an opt-in MiniMax-H3 prompt that reads like a director briefing camera and actors.

Opt-in only: a generation contract declares ``"h3_prompt_style": "DIRECTOR_PROMPT_V2"`` (top level), the grouped
compiler stamps the field on its H3 units, the transaction task carries it and the paid boundary re-renders
from it (``submit_giggle_video_manifest_v2.provider_prompt_unit``).  Every other unit renders the V1
``subject_definitions:`` prompt byte-identically (tools/h3_provider_prompt_renderer.py).

Sections, in order: References / Who is in frame / Setting / Camera / Action / Dialogue / Sound / Never.
Every fact comes from the same execution plan and bound English contract V1 uses; the optional
``director_v2`` block of that contract (appearance, wardrobe, setting in English) is requested by
tools/h3_english_contract_io.py for V2 units only.  Machine ids, retention/force/interaction templates,
duplicated start/end states and NO_BGM tokens are never serialized.  See
docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md ("DIRECTOR_PROMPT_V2").
"""

from __future__ import annotations

import re
from typing import Any

try:
    from tools.provider_scope_projection import (
        DIRECTOR_PROMPT_V2,
        director_v2_background_clause,
        director_v2_onscreen_entity_ids,
        director_v2_population_core,
        director_v2_roster_marker,
        number_word,
    )
    from tools.provider_contract_boundary import is_being_prop, validate_provider_prompt_boundary
    from tools.h3_provider_english_contract import validate_h3_provider_text_boundary
    from tools.provider_semantic_coverage import build_semantic_coverage_receipt
    from tools.prompt_budget_observability import measure_prompt
    from tools.editorial_pacing_contract import content_window_clause, delivery_clause
    from tools.wardrobe_identity_contract import h3_adult_female_visual_block
except ModuleNotFoundError:  # pragma: no cover - flat sys.path deployments
    from provider_scope_projection import (  # type: ignore
        DIRECTOR_PROMPT_V2,
        director_v2_background_clause,
        director_v2_onscreen_entity_ids,
        director_v2_population_core,
        director_v2_roster_marker,
        number_word,
    )
    from provider_contract_boundary import is_being_prop, validate_provider_prompt_boundary  # type: ignore
    from h3_provider_english_contract import validate_h3_provider_text_boundary  # type: ignore
    from provider_semantic_coverage import build_semantic_coverage_receipt  # type: ignore
    from prompt_budget_observability import measure_prompt  # type: ignore
    from editorial_pacing_contract import content_window_clause, delivery_clause  # type: ignore
    from wardrobe_identity_contract import h3_adult_female_visual_block  # type: ignore

try:
    from tools import h3_provider_prompt_renderer as v1
except ModuleNotFoundError:  # pragma: no cover
    import h3_provider_prompt_renderer as v1  # type: ignore

SCHEMA = "qingshan.minimax_h3_director_prompt.v2"
CJK = re.compile(r"[㐀-鿿]")
#: Internal machine ids that must never reach the provider (spaces, entities, angles, axes, shots, units).
INTERNAL_ID = re.compile(
    r"\b(?:GLOBAL-SPACE|GSM|LOC|SUBSPACE|SUB|SET|CHAR|PROP|ANGLE|AXIS|ZONE|WARD|WARDROBE|PF|BND|SLOT)-[A-Z0-9][A-Z0-9_-]*"
    r"|\bE\d{2,}-(?:VU-\d+|S\d+(?:-\d+)?)\b")
_SHOT_SCOPE_PREFIX = re.compile(r"^\s*Only for shot [A-Za-z0-9_-]+:\s*", re.IGNORECASE)
_NO_BGM = re.compile(r"[;,.\s]*\bNO_BGM\b[.;]?", re.IGNORECASE)
_MACHINE_PREFIXES = (
    (re.compile(r"^Light-source micromotion:\s*", re.IGNORECASE), "Light: "),
)
_FORBIDDEN_V2_PHRASES = ("at most one", "retention_analysis", "Force origin:", "Interaction mode:", "NO_BGM",
                         "this reference alone does not put")
_SCALE_WORDS = {
    "EXTREME_CLOSE_UP": "extreme close-up", "ECU": "extreme close-up", "CLOSE_UP": "close-up", "CU": "close-up",
    "MEDIUM_CLOSE_UP": "medium close-up", "MCU": "medium close-up", "MEDIUM": "medium shot",
    "MEDIUM_WIDE": "medium-wide shot", "MEDIUM_FULL": "medium-full shot", "FULL": "full shot",
    "WIDE": "wide shot", "EXTREME_WIDE": "extreme wide shot", "INSERT": "insert shot",
}
_HEIGHT_WORDS = {"EYE_LEVEL": "eye level", "LOW": "low angle", "LOW_ANGLE": "low angle", "HIGH": "high angle",
                 "HIGH_ANGLE": "high angle", "OVERHEAD": "overhead", "TOP_DOWN": "overhead",
                 "GROUND_LEVEL": "ground level", "SHOULDER_LEVEL": "shoulder level"}
_MOVE_WORDS = {
    "DOLLY": "One short dolly move", "PAN": "One short pan", "TRUCK": "One short lateral truck",
    "TRACK": "One short lateral track", "TRACKING": "One motivated follow", "CRANE": "One motivated vertical move",
    "TILT": "One motivated tilt", "ARC": "One motivated arc move", "HANDHELD": "A gentle handheld follow",
}
_IDENTITY_FREE_REFERENCE_ROLES = {"ADMITTED_NEW_EVENT_ENTRY_STATE", "PREVIOUS_UNIT_FINAL_FRAME",
                                  "IDENTITY_OR_PROP_REANCHOR"}
_PREVIOUS_FRAME_ROLES = {"PREVIOUS_REAL_TAIL_STATE_AUTHORITY", "PREVIOUS_UNIT_FINAL_FRAME"}
#: CAMERA_GRAMMAR_V1: roles of the unit's start frame.  At @Image1 they are always the opening / exact first frame,
#: even when the reference sequence tags that keyframe with the CHAR-* id of the person in it (lab Holmes E06
#: 2026-10-26: a recompile turned the own keyframe of a motivated cut into "@Image1 is Holmes's face and body.").
_OPENING_FRAME_ROLES = {"ADMITTED_NEW_EVENT_ENTRY_STATE", "CONTINUITY_DERIVED_ENTRY_STATE", "PREVIOUS_UNIT_FINAL_FRAME",
                        "PREVIOUS_UNIT_REAL_FINAL_FRAME"}
_NEGATED_MOVES = re.compile(r"\bno (?:pan|zoom|drift|dolly|tilt|track|push|pull|follow)\b", re.IGNORECASE)
TOPOLOGY_V2 = "Every hand stays attached to its owner's body; no extra, isolated or severed limbs"
_ECHO_FILLER = {"visible", "subtle", "motion", "consistent", "with", "and", "the", "continuous", "slight"}
NEVER_V2 = "captions, subtitles, letters or logos on screen; a second copy of anyone"


# ----------------------------------------------------------------------------------------------------------
# text helpers
# ----------------------------------------------------------------------------------------------------------
def _en(value: Any, limit: int = 400) -> str:
    """One clean English sentence body: whitespace folded, no trailing punctuation, '' when CJK."""
    text = " ".join(str(value or "").split()).strip().rstrip(".;, ")
    if not text or CJK.search(text):
        return ""
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;")


def scrub(value: Any) -> str:
    """Drop machine scaffolding from an English contract string (ids, shot-scope prefixes, NO_BGM)."""
    text = _NO_BGM.sub("", _SHOT_SCOPE_PREFIX.sub("", " ".join(str(value or "").split())))
    for pattern, replacement in _MACHINE_PREFIXES:
        text = pattern.sub(replacement, text)
    if INTERNAL_ID.search(text):
        kept = []
        for clause in re.split(r"\s*;\s*", text):
            if INTERNAL_ID.search(clause):
                residue = INTERNAL_ID.sub("", clause)
                # "Within the same SUBSPACE-..." says nothing without its id: drop the whole clause
                if len(re.findall(r"[A-Za-z]{3,}", residue)) <= 4:
                    continue
                clause = re.sub(r"\s{2,}", " ", residue).strip(" ,")
            kept.append(clause)
        text = "; ".join(kept)
    text = re.sub(r"\btime: ([A-Z][A-Z_]+)\b", lambda m: "time: " + m.group(1).lower().replace("_", " "), text)
    return text.strip().rstrip(".;, ")


def _sentence(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    value = value[0].upper() + value[1:]
    return value if value[-1] in ".!?" else value + "."


def _cap(value: str) -> str:
    return value[:1].upper() + value[1:]


def _same(a: str, b: str) -> bool:
    return re.sub(r"[\s.;,]+", " ", a).strip().lower() == re.sub(r"[\s.;,]+", " ", b).strip().lower()


def _join_names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# ----------------------------------------------------------------------------------------------------------
# subjects
# ----------------------------------------------------------------------------------------------------------
def _catalog(unit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in unit.get("character_entities") or []:
        cid = str(row.get("character_id") or row.get("entity_id") or "")
        if cid:
            rows.setdefault(cid, row)
    return rows


def _wardrobe_rows(unit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in (unit.get("wardrobe_contract") or {}).get("characters") or []:
        for key in (row.get("character_id"), row.get("character")):
            if key:
                rows.setdefault(str(key), row)
    return rows


def _id_label(entity_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", " ", re.sub(r"^(PROP|OBJ|SET|CREATURE|BEING|CHAR)-", "", entity_id)).strip().title()


def subject_label(unit: dict[str, Any], plan: dict[str, Any], entity_id: str, fallback: Any = "") -> str:
    labels = v1._entity_labels(unit, plan)
    if labels.get(entity_id):
        return labels[entity_id]
    row = _catalog(unit).get(entity_id) or {}
    for value in (row.get("english_name"), *(row.get("aliases") or []), row.get("canonical_name"), fallback):
        label = _en(value, 80)
        if label:
            return label
    return _id_label(entity_id) or entity_id


def subject_sources(unit: dict[str, Any]) -> list[dict[str, Any]]:
    """Every subject the unit's specs put in its cast or carded beings, first appearance order.

    ``{"entity_id", "kind": PERSON|BEING, "name", "appearance", "wardrobe", "look"}`` with the raw authored
    texts (any language): the renderer keeps the English ones, the English-contract request asks for the rest.
    """
    catalog = _catalog(unit)
    wardrobe = _wardrobe_rows(unit)
    rows: dict[str, dict[str, Any]] = {}
    for spec in unit.get("ordered_prompt_specs") or []:
        for member in spec.get("cast") or []:
            cid = str(member.get("character_id") or member.get("character") or "")
            if not cid or cid in rows:
                continue
            entity = catalog.get(cid) or {}
            dress = wardrobe.get(cid) or wardrobe.get(str(member.get("character") or "")) or {}
            appearance = (entity.get("appearance_en") or entity.get("english_appearance")
                          or entity.get("appearance") or entity.get("appearance_ch1") or dress.get("appearance_ch1") or "")
            rows[cid] = {"entity_id": cid, "kind": "PERSON",
                         "name": str(member.get("character") or entity.get("canonical_name") or ""),
                         "appearance": str(appearance or ""),
                         "wardrobe": str(dress.get("authored_description") or "")}
        for prop in spec.get("props") or []:
            pid = str(prop.get("prop_id") or prop.get("prop") or "")
            if not pid or pid in rows or not is_being_prop(prop):
                continue
            rows[pid] = {"entity_id": pid, "kind": "BEING", "name": str(prop.get("english_name") or prop.get("prop") or ""),
                         "look": str(prop.get("note") or ""), "creature_card": prop.get("creature_card") or {}}
    return list(rows.values())


def setting_source(unit: dict[str, Any]) -> str:
    """Authored location + light words for the Setting line (any language)."""
    vcc = unit.get("visual_culture_contract") if isinstance(unit.get("visual_culture_contract"), dict) else {}
    specs = unit.get("ordered_prompt_specs") or []
    first = specs[0] if specs else {}
    scene = first.get("scene_state") or {}
    design = first.get("visual_design") or {}
    # the middle-ground layer restates the beat's action: the Action section owns that
    layers = [row for row in design.get("depth_layers") or []
              if isinstance(row, str) and not re.match(r"\s*(?:中景|middle ?ground)", row, re.IGNORECASE)]
    parts = [vcc.get("story_world"), vcc.get("production_design"), *layers,
             design.get("key_light") or scene.get("lighting")]
    seen: list[str] = []
    for value in parts:
        value = " ".join(str(value or "").split())
        if value and not INTERNAL_ID.fullmatch(value) and value not in seen:
            seen.append(value)
    return "；".join(seen)


def _beats(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return (plan.get("action_ir") or {}).get("causal_chains") or plan.get("beats") or []


def _spec_for(unit: dict[str, Any], beat: dict[str, Any]) -> dict[str, Any]:
    specs = unit.get("ordered_prompt_specs") or []
    try:
        position = int(beat.get("source_index")) - 1
    except (TypeError, ValueError):
        return {}
    return specs[position] if 0 <= position < len(specs) and isinstance(specs[position], dict) else {}


def _visible_in_spec(spec: dict[str, Any], entity_id: str) -> bool:
    role = spec.get("role_semantic_disambiguation") or {}
    presence = str((role.get("entity_presence") or {}).get(entity_id) or "").upper()
    if "OFFSCREEN" in presence or presence in {"ABSENT", "NOT_PRESENT"}:
        return False
    for member in spec.get("cast") or []:
        if str(member.get("character_id") or member.get("character") or "") == entity_id:
            return str(member.get("face_visibility") or "").upper() != "OFFSCREEN_VOICE_ONLY"
    return any(str(prop.get("prop_id") or prop.get("prop") or "") == entity_id and is_being_prop(prop)
               for prop in spec.get("props") or [])


def _side(label: str, framing: str) -> str:
    match = re.search(re.escape(label) + r"\s+(?:is\s+|stands\s+|sits\s+|kneels\s+)?(?:on|at|to)\s+(?:the\s+)?"
                      r"(?:frame\s+|screen\s+)?(left|right|center|centre)\b", framing, re.IGNORECASE)
    if not match:
        return ""
    side = match.group(1).lower()
    return ", frame centre" if side in {"center", "centre"} else f", frame {side}"


def _windows(indices: list[int], beats: list[dict[str, Any]]) -> list[tuple[float, float]]:
    windows: list[tuple[float, float]] = []
    for index in sorted(indices):
        start, end = float(beats[index]["start_seconds"]), float(beats[index]["end_seconds"])
        if windows and abs(windows[-1][1] - start) < 1e-6:
            windows[-1] = (windows[-1][0], end)
        else:
            windows.append((start, end))
    return windows


def _span(window: tuple[float, float]) -> str:
    return f"{window[0]:g}–{window[1]:g} s"


# ----------------------------------------------------------------------------------------------------------
# camera
# ----------------------------------------------------------------------------------------------------------
def _camera_entry(camera_plan: dict[str, Any], english: dict[str, str], *, one_take: bool = False) -> str:
    family = str(camera_plan.get("motion_family") or "STATIC").upper()
    scale_raw = str(camera_plan.get("shot_scale") or "MEDIUM").upper()
    scale = _SCALE_WORDS.get(scale_raw, scale_raw.lower().replace("_", " "))
    height_raw = str(camera_plan.get("camera_height") or "").upper()
    height = _HEIGHT_WORDS.get(height_raw, height_raw.lower().replace("_", " "))
    head = ", ".join(v for v in (height, scale) if v)
    start, end = (scrub(english.get(k) or "") for k in ("start_framing", "end_framing"))
    start, end = (None if v and v1._BOILERPLATE_FRAMING.match(v) else v for v in (start, end))
    parts: list[str] = []
    locked = family in {"STATIC", "LOCKED"}
    stamped = camera_plan.get("camera_grammar") == "CAMERA_GRAMMAR_V1"
    if locked:
        parts.append(f"Locked camera, {head}." if head else "Locked camera.")
        if stamped:  # provider-expert wording (2026-10-26) replaces the older lock sentence, said once
            parts += [v1.ONE_TAKE] if one_take else []
            parts.append(v1.FIXED_CAMERA_POSITION)
        else:
            parts.append("The camera never moves: no pan, no zoom, no drift.")
    else:
        direction = str(camera_plan.get("motion_direction") or "NONE").upper()
        move = _MOVE_WORDS.get(family, "One motivated " + family.lower().replace("_", " ") + " move")
        dir_words = "" if direction in {"", "NONE"} else f" ({direction.lower().replace('_', ' ')})"
        parts.append(f"{move}{dir_words}, {head}." if head else f"{move}{dir_words}.")
        parts += [v1.ONE_TAKE] if stamped and one_take else []
        if english.get("follow_subject"):
            parts.append(_sentence(f"the camera follows {scrub(english['follow_subject'])}"))
        if english.get("subject_to_keep"):
            parts.append(_sentence(f"keep {scrub(english['subject_to_keep'])} in frame throughout the move"))
    optics = v1._optical(camera_plan).lstrip("; ")
    if optics:
        optics = re.sub(r"estimated (\d+)mm focal length", r"about \1mm lens", optics)
        parts.append(_sentence(optics))
    grammar = v1._camera_grammar_clause(camera_plan).lstrip("; ")
    if grammar:
        parts.append(_sentence(grammar.replace(", no drift", "")))
    if start:
        parts.append(_sentence(f"Framing: {start}" if locked else f"Start framing: {start}"))
    if end and end != start:
        parts.append(_sentence(f"End framing: {end}" if locked else f"The move settles on and holds: {end}"))
    return " ".join(parts)


def camera_section(unit: dict[str, Any], plan: dict[str, Any], contract: dict[str, Any],
                   beats: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    uid = str(plan["unit_id"])
    rows = v1._shot_rows(unit, plan, beats)
    if not rows:
        camera_plan = plan.get("camera_plan") or {}
        failures: list[str] = []
        english = v1._camera_english(uid, "UNIT", camera_plan, contract.get("camera_plan") or {}, failures)
        return _camera_entry(camera_plan, english, one_take=True), [
            {"shot_id": "UNIT", "fields": sorted(english), "untranslated_fields": failures}]
    translated = contract.get("camera_plans") or contract.get("per_shot_camera_plans") or []
    lines, receipt = [], []
    for index, row in enumerate(rows):
        source = translated[index] if index < len(translated) and isinstance(translated[index], dict) else {}
        label = row["shot_id"] or f"SHOT_{index + 1}"
        missing: list[str] = []
        english = v1._camera_english(uid, label, row["camera_plan"], source, missing)
        boundary = "opening shot" if index == 0 else v1._shot_boundary(unit, index - 1, rows[index - 1], row, uid)
        lines.append(f"Shot {index + 1} ({float(row['start']):g}–{float(row['end']):g} s, {boundary}): "
                     + _camera_entry(row["camera_plan"], english))
        receipt.append({"shot_id": label, "boundary": boundary, "fields": sorted(english),
                        "untranslated_fields": missing})
    if len(lines) == 1:
        lines = [lines[0].split("): ", 1)[1]]
        if v1.one_take_applies([rows[0]["camera_plan"]], []):  # one shot: state the take inside its entry
            english = v1._camera_english(uid, receipt[0]["shot_id"], rows[0]["camera_plan"],
                                         translated[0] if translated and isinstance(translated[0], dict) else {}, [])
            lines = [_camera_entry(rows[0]["camera_plan"], english, one_take=True)]
    elif v1.one_take_applies([row["camera_plan"] for row in rows], [row["boundary"] for row in receipt]):
        lines.insert(0, v1.ONE_TAKE)
    return "\n".join(lines), receipt


def locked_camera_conflicts(text: str) -> list[str]:
    match = re.search(r"^Camera:\n(.*?)(?=\n\n)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return []
    findings = []
    for index, entry in enumerate(match.group(1).split("\n"), 1):
        instructions = re.split(r"\b(?:Framing|Start framing|End framing|The move settles on and holds):", entry)[0]
        instructions = _NEGATED_MOVES.sub("", instructions)
        if "Locked camera" in instructions and v1._MOVE_WORDS.search(instructions):
            findings.append(f"LOCKED_CAMERA_WITH_MOVE_INSTRUCTION:{index}:{entry.strip()[:80]}")
    return findings


# ----------------------------------------------------------------------------------------------------------
# render
# ----------------------------------------------------------------------------------------------------------
def _reference_lines(unit: dict[str, Any], plan: dict[str, Any], *, onscreen: set[str], people: int,
                     beings: int, exact_first_frame: bool = False) -> list[str]:
    refs = unit.get("reference_images") or []
    sequence_by_path = {str(row.get("path") or ""): row for row in unit.get("reference_image_sequence") or []
                        if row.get("path") and str(row.get("entity_id") or "").startswith("CHAR-")}
    scope = unit.get("provider_scope_projection") or {}
    scope_bindings = {int(row["reference_index"]): row for row in scope.get("reference_identity_bindings") or []
                      if row.get("reference_index") is not None}
    lines = []
    for index, raw in enumerate(refs, 1):
        ref = raw if isinstance(raw, dict) else {"path": str(raw)}
        bound = scope_bindings.get(index) or sequence_by_path.get(str(ref.get("path") or ""), {})
        ref = {**bound, **ref}
        entity_id = str(ref.get("entity_id") or "").strip()
        role = str(ref.get("role") or "REFERENCE").strip().upper()
        entity = v1._english_label(ref.get("provider_entity_label")) or (
            subject_label(unit, plan, entity_id) if entity_id else "")
        binding_role = str(bound.get("binding_role") or "")
        identity = binding_role == "IDENTITY" or (not binding_role and str(bound.get("entity_id") or entity_id).startswith("CHAR-"))
        if role in _IDENTITY_FREE_REFERENCE_ROLES:
            entity = ""
        if exact_first_frame and index == 1 and role in _OPENING_FRAME_ROLES:
            entity = ""  # the start frame, never an identity line (identity lines only for identity/sheet roles)
        if entity and identity:
            body = "face and body" if entity_id.startswith("CHAR-") or not entity_id else "look"
            line = (f"@Image{index} is {v1.reference_sheet_clause(entity)}." if v1.is_reference_sheet(ref)
                    else f"@Image{index} is {entity}'s {body}.")
            if entity_id and onscreen and entity_id not in onscreen:
                line += f" It is for identity only: {entity} stays out of frame in this clip."
            elif index > 1:
                # a face reference of someone already in the opening frame is that SAME person, not a second
                # one: H3 otherwise sometimes renders the reference as an extra copy (lab E02 2026-10-23)
                line += (f" This is the same {entity} already standing in @Image1 — one person; never draw a "
                         f"second {entity}.")
            lines.append(line)
        elif entity:
            lines.append(f"@Image{index} is the {entity}: match its shape, material and scale only; it shows no face.")
        elif index == 1:
            total = people + beings
            who = ("the objects' places" if total == 0 else "the person's place" if people == 1 and total == 1
                   else "the subject's place" if total == 1 else f"the {number_word(total)} people's places"
                   if people == total and total <= 3 else "everyone's places")
            if exact_first_frame:
                # lab Holmes E05: H3 sometimes opened wider than @Image1 and pushed in to it; pin the first frame
                lines.append(f"@Image1 is the exact first frame: the clip starts on this image with the same shot "
                             f"size, framing, camera position and {who} as shown; never start wider or closer than @Image1. "
                             "Faces come from the face "
                             "references; never freeze its pose.")
            else:
                lines.append(f"@Image1 is the opening frame: match its setting, camera position and {who}. "
                             "Faces come from the face references; never freeze its pose.")
        elif role in _PREVIOUS_FRAME_ROLES:
            lines.append(f"@Image{index} is the previous shot's last frame: continuity of positions, clothing "
                         "and props only; it defines no face.")
        else:
            lines.append(f"@Image{index} is a supporting continuity reference: match only what it shows of the "
                         "setting and props; it defines no face.")
    return lines


def render_director_v2(unit: dict[str, Any], plan: dict[str, Any], contract: dict[str, Any], *,
                       crossmodal_rows: list[dict[str, Any]], language: str, visible_total: int,
                       background_total: int, unbound_total: int) -> tuple[str, dict[str, Any]]:
    uid = str(plan["unit_id"])
    beats = _beats(plan)
    english_beats = contract.get("beats") or []
    scope = unit.get("provider_scope_projection") or {}
    counts = scope.get("visible_entity_instance_counts") or {}
    v2_english = contract.get("director_v2") if isinstance(contract.get("director_v2"), dict) else {}
    evidence: dict[str, str] = {
        "ANCHOR.IDENTITY_PROP": "", "ANCHOR.SPACE_WEATHER": "",
    }
    crossmodal_by_speaker = {str(row.get("speaker") or "").strip(): row for row in crossmodal_rows}
    stamped = v1.director_active(unit, plan)  # CAMERA_GRAMMAR_V1 camera plans

    # --- subjects and per-beat presence ----------------------------------------------------------------
    sources = subject_sources(unit)
    onscreen_ids = set(director_v2_onscreen_entity_ids(unit, scope)) if scope.get("visible_character_ids") else set()
    del visible_total  # the projection total counts offscreen speakers too; V2 counts who is on screen
    partial = v1.beat_visibility_scopes(unit, plan)
    speakers = v1._visible_speaker_ids(plan)
    subjects = []
    for row in sources:
        cid = row["entity_id"]
        present = [i for i, beat in enumerate(beats) if _visible_in_spec(_spec_for(unit, beat), cid)]
        if not present:
            continue
        subjects.append({**row, "label": subject_label(unit, plan, cid, row.get("name")), "present": present,
                         "partial": {i: r["part"] for i, rows in enumerate(partial) for r in rows
                                     if r["entity_id"] == cid and i in present}})
    for index, rows in enumerate(partial):
        for row in rows:
            if row["entity_id"] in speakers[index] or (row["label"] and row["label"] in speakers[index]):
                raise ValueError(f"{uid}:H3_SHOT_SCOPE_CONFLICT:BEAT.{index + 1}:{row['entity_id']}:"
                                 "VISIBLE_LIP_SYNC_SPEAKER_DECLARED_PARTIAL")
    people = [s for s in subjects if s["kind"] == "PERSON"]
    beings = [s for s in subjects if s["kind"] == "BEING"]
    total = (sum(int(counts.get(cid) or 1) for cid in onscreen_ids) if scope.get("visible_character_ids")
             else sum(int(counts.get(s["entity_id"]) or 1) for s in subjects))
    label_by_id = {s["entity_id"]: s["label"] for s in subjects}

    # --- references ------------------------------------------------------------------------------------
    reference_lines = _reference_lines(unit, plan, onscreen=onscreen_ids, people=len(people), beings=len(beings),
                                       exact_first_frame=stamped)
    for index, row in enumerate(crossmodal_rows, 1):
        binding = f"{row['audio_slot']} is {row['provider_entity_label']}'s voice"
        reference_lines.append(binding + ". It gives timbre only — never speak or echo its words.")
        evidence[f"VOICE_BINDING.{index}"] = binding

    # --- who is in frame -------------------------------------------------------------------------------
    framing_text = " ".join(str(v) for v in [
        (contract.get("camera_plan") or {}).get("start_framing"),
        *[(row or {}).get("start_framing") for row in contract.get("camera_plans") or [] if isinstance(row, dict)],
    ] if v)
    who_lines: list[str] = []
    whole = all(len(s["present"]) == len(beats) and not s["partial"] for s in subjects)
    subjects_v2 = (v2_english.get("subjects") or {}) if isinstance(v2_english.get("subjects"), dict) else {}

    def look_of(s: dict[str, Any], compact: bool) -> str:
        if compact:
            return ""
        answer = subjects_v2.get(s["entity_id"]) or subjects_v2.get(s["label"]) or {}
        if s["kind"] == "BEING":
            card = s.get("creature_card") or {}
            gait = {"biped": "moves upright on two legs", "quadruped": "moves on four legs"}.get(
                str(card.get("locomotion") or "").strip().lower(), "")
            look = _en(answer.get("look")) or _en(s.get("look"))
            return "; ".join(v for v in ("a living non-human subject, not a prop", look, gait) if v)
        appearance = _en(answer.get("appearance")) or _en(s.get("appearance"))
        wardrobe = _en(answer.get("wardrobe")) or _en(s.get("wardrobe"))
        if wardrobe and appearance and wardrobe.lower() in appearance.lower():
            wardrobe = ""
        return " ".join(_sentence(v) for v in (appearance, wardrobe) if v).rstrip(".")

    def who_block(compact: bool) -> list[str]:
        if not subjects:
            props = [_en(p.get("english_name") or p.get("prop"), 80) for spec in unit.get("ordered_prompt_specs") or []
                     for p in spec.get("props") or []]
            props = list(dict.fromkeys(p for p in props if p))
            return [f"Who is in frame: nobody — a photographic insert of {_join_names(props) if props else 'the object described below'}; "
                    "no people, no hands, no body parts."]
        noun = ("person" if total == 1 else "people") if not beings else (
            "being" if total == 1 and not people else "beings" if not people else "subjects")
        core = director_v2_population_core(total)
        multi = any(int(counts.get(s["entity_id"]) or 1) > 1 for s in subjects)
        once = "each as listed" if multi else ("exactly once" if total == 1 else "each exactly once")
        if whole:
            presence = ("visible from the first frame to the last" if total == 1 else
                        f"{'both' if total == 2 else 'all'} visible from the first frame to the last")
        else:
            presence = "presence as noted for each"
        background = director_v2_background_clause(unbound_total,
                                                   scope.get("anonymous_role_descriptors") or [])
        header = f"Who is in frame ({core} {noun}, {once}, {presence}" + (f"; {background}" if background else "") + "):"
        lines = [header]
        for s in subjects:
            marker = director_v2_roster_marker(s["label"], int(counts.get(s["entity_id"]) or 1))
            look = look_of(s, compact)
            line = marker + _side(s["label"], framing_text) + (f": {look}." if look else ".")
            if len(s["present"]) != len(beats):
                windows = _windows(s["present"], beats)
                line += f" In frame only {', '.join(_span(w) for w in windows)}."
            for index, part in sorted(s["partial"].items()):
                window = _span((float(beats[index]["start_seconds"]), float(beats[index]["end_seconds"])))
                line += (f" {window}: only {s['label']}'s {part} in frame; {s['label']}'s face is not shown."
                         if part else f" {window}: {s['label']}'s face stays out of frame.")
            lines.append(line)
        tail = []
        if len(people) > 1:
            tail.append("Each keeps only their own clothes.")
        tail.append("Nobody else appears beyond them and the background figures named above." if background else
                    "Nobody else appears — no extra people, figures, reflections of people, or hands entering the frame.")
        lines.append(" ".join(tail))
        return lines

    adult = h3_adult_female_visual_block(unit)
    adult_line = ("Every confirmed adult woman has a mature, naturally fuller silhouette with role-appropriate "
                  "fitted tailoring and a clear waistline; tasteful, non-explicit styling.") if adult else ""

    # --- sound (before the setting: an ambient-motion row that only echoes the sound is stated there) --
    action_echoes = [scrub(b.get("primary_action") or "") for b in english_beats]
    translated_sounds = contract.get("sounds") or {}
    sound_rows: list[str] = []
    for key in ("ambience", "foley", "action_sound"):
        source_rows = (plan.get("sounds") or {}).get(key) or []
        provider_rows = translated_sounds.get(key) or []
        if len(provider_rows) != len(source_rows):
            raise ValueError(f"H3_ENGLISH_CONTRACT_SOUND_COUNT:{uid}:{key}:{len(provider_rows)}!={len(source_rows)}")
        for index, value in enumerate(provider_rows, 1):
            value = scrub(value)
            for echo in action_echoes:  # "... sounds from this action: <the action restated>" -> "... from this action"
                if echo and len(echo) > 12:
                    value = re.sub(r"\s*:\s*" + re.escape(echo) + r"\.?\s*", ". ", value).strip()
            value = _cap(value.rstrip(".;, "))
            evidence[f"SOUND.{key.upper()}.{index}"] = value
            if value and value not in sound_rows:
                sound_rows.append(value)
    sound_line = "Sound: " + (" ".join(_sentence(v) for v in sound_rows) if sound_rows
                              else "native location ambience and foley only.") + " No background music."
    sound_words = set(re.findall(r"[a-z]{3,}", " ".join(sound_rows).lower()))

    # --- setting ---------------------------------------------------------------------------------------
    setting_lines: list[str] = []
    setting_en = _en((v2_english or {}).get("setting"), 600) or _en(setting_source(unit), 600)
    if setting_en:
        setting_lines.append(_sentence(scrub(setting_en)))
    space_weather = _cap(scrub(contract["space_weather_fact"]))
    identity_prop = scrub(contract["identity_prop_fact"])
    evidence["ANCHOR.SPACE_WEATHER"] = space_weather
    if space_weather:
        setting_lines.append(_sentence(space_weather))
    source_env = plan.get("environment_motion") or []
    translated_env = contract.get("environment_motion") or []
    if len(translated_env) != len(source_env):
        raise ValueError(f"H3_ENGLISH_CONTRACT_ENVIRONMENT_COUNT:{uid}:{len(translated_env)}!={len(source_env)}")
    env_rows: list[str] = []
    stated = {c.strip().lower() for c in re.split(r"[;.]\s*", space_weather) if c.strip()}
    for index, value in enumerate(translated_env, 1):
        value = scrub(value)
        clauses = [c for c in re.split(r"\s*;\s*", value) if c.strip()]
        fresh = [c for c in clauses if c.strip().rstrip(".").lower() not in stated]
        words = set(re.findall(r"[a-z]{3,}", value.lower())) - _ECHO_FILLER
        if words and words <= sound_words and sound_rows:
            # "visible subtle motion consistent with <the sound>": the Sound line states it
            evidence[f"ENVIRONMENT_MOTION.{index}"] = sound_rows[0]
            continue
        value = _cap("; ".join(fresh)) if fresh else ""
        if not value:  # every clause already stated by the time/weather line
            evidence[f"ENVIRONMENT_MOTION.{index}"] = space_weather
            continue
        evidence[f"ENVIRONMENT_MOTION.{index}"] = value
        stated.update(c.strip().rstrip(".").lower() for c in fresh)
        if value not in env_rows:
            env_rows.append(value)
    if env_rows:
        setting_lines.append(" ".join(_sentence(v) for v in env_rows))
    look = v1.h3_visual_culture_block(unit)
    if look != v1.H3_AUTHORED_WORLD_LOCK:  # period locks carry real constraints; the authored-world one is filler
        setting_lines.append(_sentence("Look: " + look.rstrip(".")))
    # the identity/prop anchor names the cast (stated in "Who is in frame"), the key props (a setting fact) and
    # a reference-lock boilerplate sentence (the References block): only the props are left to state here
    prop_fact = " ".join(
        sentence for sentence in re.split(r"(?<=[.;])\s+", identity_prop + ".")
        if sentence.strip(" .;") and not re.match(r"(?:Use|Using)\b.*\bsupplied\b|(?:Characters?|Cast|People)\s*[:=]",
                                                  sentence.strip(), re.IGNORECASE)
    ).strip().rstrip(".;")
    prop_fact = _cap(prop_fact)
    evidence["ANCHOR.IDENTITY_PROP"] = prop_fact or ""
    if prop_fact:
        setting_lines.append(_sentence(prop_fact))

    # --- camera ----------------------------------------------------------------------------------------
    camera, camera_receipt = camera_section(unit, plan, contract, beats)
    evidence["CAMERA.PLAN"] = camera

    # --- action + dialogue -----------------------------------------------------------------------------
    duration = float(plan["duration_seconds"])
    action_lines = [f"Action (0–{duration:g} s):"]
    if content_window_clause(plan, "EN"):  # validates the authority; V2 states it in director words
        content = float((plan.get("duration_authority") or {})["authorized_content_seconds"])
        content_window = (f"The story takes {content:g} s of the {duration:g} s clip: play actions and speech at "
                          "their authored times, never slowed to fill it; the remainder is only a spare handle.")
        action_lines.append(content_window)
        evidence["PACING.CONTENT_WINDOW"] = content_window
    transition = plan.get("transition") or {}
    translated_transition = contract.get("transition") or {}
    if transition.get("incoming"):
        incoming = scrub(translated_transition.get("incoming") or "")
        if not incoming:
            raise ValueError(f"H3_ENGLISH_CONTRACT_FIELD_MISSING:{uid}:transition.incoming")
        first_entry = scrub((english_beats[0] or {}).get("entry_state") or "") if english_beats else ""
        if not _same(incoming, first_entry):
            action_lines.append(f"Open directly from the inherited state: {incoming}. Do not reset or replay it.")
        evidence["TRANSITION.INCOMING"] = incoming
        inherited_start = _same(incoming, first_entry)
    else:
        inherited_start = False
    persistent = scrub(contract.get("persistent_state_lock") or "")
    if persistent:
        action_lines.append(_sentence(f"Throughout: {persistent}"))
    shot_states = [scrub(v) for v in contract.get("shot_state_locks") or []]
    dialogue_rows: list[dict[str, Any]] = []
    last_exit = ""
    multi_beat = len(beats) > 1
    for number, (source, translated) in enumerate(zip(beats, english_beats), 1):
        prefix = f"BEAT.{number}"
        spec = _spec_for(unit, source)
        role = spec.get("role_semantic_disambiguation") or {}
        entry = scrub(translated["entry_state"])
        action = _cap(scrub(translated["primary_action"]))
        exit_state = scrub(translated["exit_state"])
        force = scrub(translated.get("force_origin") or "") or entry
        parts = [_sentence(("Start, inherited from the previous shot with no reset or replay: " if inherited_start
                            and number == 1 else "Start: ") + entry)]
        evidence[f"{prefix}.ENTRY"] = entry
        if _same(force, entry):
            evidence[f"{prefix}.FORCE_ORIGIN"] = entry
        else:
            parts.append(_sentence(f"The movement starts from {force}"))
            evidence[f"{prefix}.FORCE_ORIGIN"] = force
        parts.append(_sentence(action))
        evidence[f"{prefix}.ACTION"] = action
        mode = str(source.get("interaction_mode") or "NONE")
        timed = source.get("contact_time_seconds") is not None
        if plan.get("combat_execution_required") or timed or mode in {"EVASION", "THREAT_THRESHOLD"}:
            label = {"CONTACT": "physical contact", "EVASION": "clear evasion",
                     "THREAT_THRESHOLD": "pre-contact threat threshold"}.get(mode, "no person-to-person interaction")
            contact = f"Contact ({label}" + (f", at {float(source['contact_time_seconds']):g}s" if timed else "") + ")"
            if mode != "NONE":
                evidence[f"{prefix}.INTERACTION_MODE"] = label
            if timed:
                evidence[f"{prefix}.CONTACT_TIME"] = f"{float(source['contact_time_seconds']):g}s"
            if source.get("contact_point"):
                point = scrub(translated.get("contact_point") or "")
                contact += f": {point}"
                evidence[f"{prefix}.CONTACT_POINT"] = point
            parts.append(_sentence(contact))
            if source.get("primary_feedback"):
                feedback = scrub(translated.get("primary_feedback") or translated.get("force_feedback") or "")
                parts.append(_sentence(f"Feedback: {feedback}"))
                evidence[f"{prefix}.PRIMARY_FEEDBACK"] = feedback
            for k, value in enumerate(translated.get("secondary_feedback") or [], 1):
                value = scrub(value)
                parts.append(_sentence(f"Then: {value}"))
                evidence[f"{prefix}.SECONDARY_FEEDBACK.{k}"] = value
        speaker_label = ""
        raw = str(source.get("dialogue") or "").strip()
        if raw:
            speaker, separator, words = v1._dialogue_partition(raw, language)
            binding = crossmodal_by_speaker.get(speaker.strip())
            if binding is None:
                raise ValueError(f"H3_DIALOGUE_CROSSMODAL_BINDING_MISSING:{uid}:{speaker.strip()}")
            if not separator or not words.strip():
                raise ValueError(f"DIALOGUE_SPEAKER_BINDING_INVALID:{raw}")
            speaker_label = str(binding["provider_entity_label"])
            literal = f"<d>[{v1.DIALOGUE_LANGUAGE_TAGS[language]}] {words.strip()}</d>"
            evidence[f"{prefix}.DIALOGUE"] = literal
            performance = ((spec.get("action") or {}).get("performance"))
            direction = v1._performance_direction(performance)
            if direction:
                body = re.sub(r"^Performance: ", "", direction).split(" Natural human speech")[0].rstrip(".")
                delivery = f"Delivery: {body}. Natural breathing, clear rises and falls, never a flat read."
            else:
                delivery = delivery_clause(source, "EN")
            if delivery:
                evidence[f"{prefix}.DIALOGUE_DELIVERY"] = delivery
            dialogue_rows.append({"label": speaker_label, "literal": literal, "delivery": delivery,
                                  "visible": bool(binding.get("visible_speaker")),
                                  "gaze": v1.speaker_gaze_clause(unit, binding) if stamped else "",
                                  "window": (float(source["start_seconds"]), float(source["end_seconds"]))})
            evidence[f"{prefix}.DIALOGUE_SPEAKER"] = speaker.strip()
            parts.append(_sentence(f"{speaker_label} speaks" + (f" line {len(dialogue_rows)}" if multi_beat else "")
                                   + ("" if binding.get("visible_speaker") else " from offscreen")))
        parts.append(_sentence(f"End: {exit_state}"))
        evidence[f"{prefix}.EXIT"] = exit_state
        last_exit = exit_state
        if source.get("internal_transition_after"):
            bridge = scrub(translated.get("internal_transition_after") or "")
            parts.append(_sentence(f"Then bridge into the next beat: {bridge}"))
            evidence[f"{prefix}.INTERNAL_TRANSITION_AFTER"] = bridge
        if number <= len(shot_states) and shot_states[number - 1]:
            parts.append(_sentence(f"Hold: {shot_states[number - 1]}"))
        line = " ".join(parts)
        if multi_beat:
            line = f"{float(source['start_seconds']):g}–{float(source['end_seconds']):g} s: " + line
        action_lines.append(line)
        # what everybody else in frame does during this beat
        actor_id = str(role.get("primary_actor_id") or (spec.get("action") or {}).get("subject_id") or "")
        speaker_id = str(role.get("dialogue_speaker_id") or "") if raw else ""
        reactions = (spec.get("action") or {}).get("listener_reaction_en")
        index = number - 1
        for s in subjects:
            cid = s["entity_id"]
            if cid in {actor_id, speaker_id} or (speaker_label and s["label"] == speaker_label):
                continue
            if index not in s["present"] or index in s["partial"]:
                continue
            authored = (reactions.get(cid) or reactions.get(s["label"])) if isinstance(reactions, dict) else reactions
            authored = scrub(authored) if _en(authored) else ""
            if authored:
                action_lines.append(_sentence(authored if authored.lower().startswith(s["label"].lower())
                                              else f"{s['label']}: {authored}"))
            elif speaker_label:
                action_lines.append(f"{s['label']} listens without speaking, holding {speaker_label}'s gaze.")
            elif actor_id and label_by_id.get(actor_id):
                action_lines.append(f"{s['label']} stays silent, watching {label_by_id[actor_id]}.")
            else:
                action_lines.append(f"{s['label']} stays silent in place.")
    if transition.get("outgoing"):
        outgoing = scrub(translated_transition.get("outgoing") or "")
        if not outgoing:
            raise ValueError(f"H3_ENGLISH_CONTRACT_FIELD_MISSING:{uid}:transition.outgoing")
        if not _same(outgoing, last_exit):
            action_lines.append(f"Hand off to the next shot on: {outgoing}.")
        evidence["TRANSITION.OUTGOING"] = outgoing if not _same(outgoing, last_exit) else last_exit
    if plan.get("interaction_topology_required"):
        action_lines.append(TOPOLOGY_V2 + ".")
        evidence["PHYSICAL.INTERACTION_TOPOLOGY"] = TOPOLOGY_V2
    if plan.get("combat_execution_required"):
        combat = ("Execute each combat beat in real time as setup and displacement, one contact or clear evasion, "
                  "force feedback, and a new position; no posing, push-hands contact, or still-frame interpolation")
        action_lines.append(combat + ".")
        evidence["COMBAT.EXECUTION_RULE"] = combat
    wuxia = plan.get("wuxia_combat_profile_selection") or {}
    if wuxia.get("status") == "SELECTED":
        module = ("Wuxia action-camera profile: " + str(wuxia.get("prompt_module_en") or "")
                  + " It only expresses the action above and adds no moves, hits, injuries, effects or outcomes")
        action_lines.append(_sentence(module))
        evidence["COMBAT.WUXIA_PROFILE_MODULE"] = module

    if not dialogue_rows:
        dialogue_lines = ([f"Dialogue: none. {v1.NO_VOICE_SILENT} Every visible person keeps their mouth closed."]
                          if stamped else
                          ["Dialogue: none. Nobody speaks; every visible person keeps their mouth closed."])
    elif len(dialogue_rows) == 1:
        row = dialogue_rows[0]
        dialogue_lines = [f"Dialogue ({row['label']} only, once, lips in sync):" if row["visible"] else
                          f"Dialogue ({row['label']}, offscreen and not shown, once; every visible person keeps "
                          "their mouth closed):", row["literal"]]
        if row["delivery"]:
            dialogue_lines.append(row["delivery"])
        if row.get("gaze"):
            dialogue_lines.append(row["gaze"])
        dialogue_lines.append(v1.ONLY_THIS_LINE if stamped else
                              "After the line nobody speaks; the remaining time is room tone.")
    else:
        dialogue_lines = ["Dialogue (in this order, each line exactly once, lips in sync; only the named speaker "
                          "talks):"]
        for number, row in enumerate(dialogue_rows, 1):
            who = row["label"] + ("" if row["visible"] else " (offscreen, not shown)")
            dialogue_lines.append(f"{number}. {who}, {_span(row['window'])}: {row['literal']}"
                                  + (f" {row['delivery']}" if row["delivery"] else "")
                                  + (f" {row['gaze']}" if row.get("gaze") else ""))
        dialogue_lines.append(v1.ONLY_THESE_LINES if stamped else
                              "After the last line nobody speaks; the remaining time is room tone.")

    # --- never -----------------------------------------------------------------------------------------
    negatives = [NEVER_V2, "any person, hand or body part" if not subjects else
                 ("anyone beyond the listed people and background figures" if (unbound_total or background_total)
                  else "anyone else in frame")]
    for value in contract.get("negative_constraints") or []:
        value = scrub(value)
        if value:
            negatives.append(value[0].lower() + value[1:])
    if wuxia.get("status") == "SELECTED":
        negatives.extend(scrub(v) for v in wuxia.get("negative_constraints_en") or [] if scrub(v))
    negatives.append("music")
    never_line = "Never: " + "; ".join(dict.fromkeys(negatives)) + "."
    if stamped and subjects:  # provider expert: the anti-duplicate rule is the prompt's last sentence (no person: none)
        never_line += "\n" + v1.NO_DUPLICATE_PEOPLE

    def assemble(compact: bool) -> str:
        who = who_block(compact)
        if adult_line and subjects:
            who.append(adult_line)
        blocks = [
            "References:\n" + "\n".join(reference_lines),
            "\n".join(who),
            "Setting:\n" + "\n".join(setting_lines),
            "Camera:\n" + camera,
            "\n".join(action_lines),
            "\n".join(dialogue_lines),
            sound_line,
            never_line,
        ]
        return "\n\n".join(blocks) + "\n"

    constraint_language = v1.h3_constraint_language(unit) if stamped else "en"
    text = v1.localize_constraints(assemble(False), constraint_language)
    if len(text) > v1._PROVIDER_RUNE_LIMIT:
        text = v1.localize_constraints(assemble(True), constraint_language)
    if constraint_language == "zh":
        evidence = {key: v1.localize_constraints(value, "zh") for key, value in evidence.items()}
    if not evidence["ANCHOR.IDENTITY_PROP"]:  # no key props: the cast fact is the "Who is in frame" header
        evidence["ANCHOR.IDENTITY_PROP"] = text.split("\n\n")[1].split("\n")[0]

    boundary = validate_provider_prompt_boundary(text, source_id=uid, model_family="MINIMAX_H3")
    h3_boundary = validate_h3_provider_text_boundary(text, source_id=uid)
    failures = [*boundary["failures"], *h3_boundary["failures"]]
    if failures:
        raise ValueError(";".join(failures))
    coverage = build_semantic_coverage_receipt(plan=plan, prompt_text=text, model_family="MINIMAX_H3",
                                               clause_evidence={k: v for k, v in evidence.items() if v},
                                               prompt_style=DIRECTOR_PROMPT_V2)
    if coverage["status"] != "PASS":
        raise ValueError(";".join(coverage["failures"]))
    self_check = director_v2_self_check(text, unit, plan)
    if self_check:
        raise ValueError(f"{uid}:H3_DIRECTOR_V2_SELF_CHECK:" + ";".join(self_check))
    return text, {
        "schema": v1.SCHEMA,
        "status": "PASS",
        "unit_id": uid,
        "model_family": "MINIMAX_H3",
        "h3_prompt_profile": str(unit.get("h3_prompt_profile") or "").strip() or "STANDARD",
        "h3_prompt_style": DIRECTOR_PROMPT_V2,
        "director_prompt_schema": SCHEMA,
        "immutable_contract_sha256": plan["immutable_contract_sha256"],
        "execution_semantics_sha256": plan["execution_semantics_sha256"],
        "camera_language_selection": plan["camera_language_selection"],
        "wuxia_combat_profile_selection": wuxia,
        "motion_density_gate": plan["motion_density_gate"],
        "provider_semantic_coverage_receipt": coverage,
        "provider_boundary": boundary,
        "h3_english_boundary": h3_boundary,
        "prompt_budget": measure_prompt(text, source_id=uid, model_family="MINIMAX_H3"),
        "shot_scope": {
            "schema": v1.SHOT_SCOPE_SCHEMA,
            "status": "PASS",
            "partial_visibility_rules": [row for rows in partial for row in rows],
            "camera_shots": camera_receipt,
        },
        **({"h3_constraint_language": "zh"} if constraint_language == "zh" else {}),
    }


def director_v2_self_check(text: str, unit: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    """The V2 counterpart of the V1 shot-scope self check (partial clauses, locked camera) plus the
    V2 shape promises: no machine ids, no V1 templates, no CJK outside the dialogue tags."""
    findings: list[str] = []
    beats = _beats(plan)
    for index, rows in enumerate(v1.beat_visibility_scopes(unit, plan)):
        if index >= len(beats):
            break
        window = _span((float(beats[index]["start_seconds"]), float(beats[index]["end_seconds"])))
        for row in rows:
            label = row["label"] or subject_label(unit, plan, row["entity_id"])
            expected = (f"{window}: only {label}'s {row['part']} in frame" if row["part"]
                        else f"{window}: {label}'s face stays out of frame")
            if expected not in text:
                findings.append(f"PARTIAL_CLAUSE_MISSING:BEAT.{index + 1}:{label}")
    findings.extend(locked_camera_conflicts(text))
    outside = re.sub(r"<d>\[[A-Za-z]+\].*?</d>", "", text, flags=re.S)
    for match in INTERNAL_ID.finditer(outside):
        findings.append(f"INTERNAL_ID_IN_PROMPT:{match.group(0)}")
    for phrase in _FORBIDDEN_V2_PHRASES:
        if phrase.lower() in outside.lower():
            findings.append(f"V1_TEMPLATE_IN_PROMPT:{phrase}")
    return list(dict.fromkeys(findings))
