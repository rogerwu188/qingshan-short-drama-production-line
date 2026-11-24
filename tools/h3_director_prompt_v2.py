#!/usr/bin/env python3
"""DIRECTOR_PROMPT_V2: an opt-in MiniMax-H3 prompt that reads like a director briefing camera and actors.

Opt-in only: a generation contract declares ``"h3_prompt_style": "DIRECTOR_PROMPT_V2"`` (top level), the grouped
compiler stamps the field on its H3 units, the transaction task carries it and the paid boundary re-renders
from it (``submit_giggle_video_manifest_v2.provider_prompt_unit``).  Every other unit renders the V1
``subject_definitions:`` prompt byte-identically (tools/h3_provider_prompt_renderer.py).

Sections, in order: References / Who is in frame / Setting / Camera / Action / Dialogue / Sound / Never.
CAMERA_GRAMMAR_V1 single-take locked-camera units get the strict camera lock by default (owner 2026-10-26): one
plain tripod sentence at the end of Camera (no all-caps block: H3 read it aloud, owner 2026-11-01) and push-in Never items;
``h3_camera_lock: "standard"`` opts out, moving cameras keep their wording, unstamped units render byte-identically.
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
    from tools.h3_provider_english_contract import (
        ALL_CAPS_LABEL,
        CAMERA_LOCK_NEVER,
        CAMERA_LOCK_TRIPOD,
        h3_camera_lock,
        redo_finding_sentences,
        strict_camera_lock_applies,
        validate_h3_provider_text_boundary,
    )
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
    from h3_provider_english_contract import (  # type: ignore
        ALL_CAPS_LABEL,
        CAMERA_LOCK_NEVER,
        CAMERA_LOCK_TRIPOD,
        h3_camera_lock,
        redo_finding_sentences,
        strict_camera_lock_applies,
        validate_h3_provider_text_boundary,
    )
    from provider_semantic_coverage import build_semantic_coverage_receipt  # type: ignore
    from prompt_budget_observability import measure_prompt  # type: ignore
    from editorial_pacing_contract import content_window_clause, delivery_clause  # type: ignore
    from wardrobe_identity_contract import h3_adult_female_visual_block  # type: ignore

try:
    from tools import h3_provider_prompt_renderer as v1
    from tools import speaking_unit_duration as _sud
except ModuleNotFoundError:  # pragma: no cover
    import h3_provider_prompt_renderer as v1  # type: ignore
    import speaking_unit_duration as _sud  # type: ignore
try:
    from tools import render_style as _render_style
except ModuleNotFoundError:  # pragma: no cover
    import render_style as _render_style  # type: ignore
try:
    from tools import performance_variety as _pv
except ModuleNotFoundError:  # pragma: no cover
    import performance_variety as _pv  # type: ignore
try:
    from tools import visual_culture_contract as _vcc
except ModuleNotFoundError:  # pragma: no cover
    import visual_culture_contract as _vcc  # type: ignore


def _pointing_scripted(unit: dict[str, Any]) -> bool:
    """A beat of this unit was given pointing business because its script asks for it (then the Never line must not
    forbid it)."""
    for spec in unit.get("ordered_prompt_specs") or []:
        action = (spec.get("action") if isinstance(spec, dict) else None) or {}
        if action.get("performance_business_family") == _pv.POINT_FAMILY:
            return True
    return False


def _voice_gender_module():
    """lines/nalu/runtime/tools/voice_gender.py (the casting-gender authority), or None where it is not shipped."""
    try:
        import voice_gender as module  # type: ignore
        return module
    except ModuleNotFoundError:
        import sys
        from pathlib import Path
        runtime_tools = Path(__file__).resolve().parents[1] / "lines/nalu/runtime/tools"
        if runtime_tools.is_dir() and str(runtime_tools) not in sys.path:
            sys.path.append(str(runtime_tools))
        try:
            import voice_gender as module  # type: ignore
            return module
        except ModuleNotFoundError:  # pragma: no cover
            return None


def speaker_voice_gender(unit: dict[str, Any], character_id: str) -> str | None:
    """male / female of a speaking character (character_entities: explicit field, else appearance words)."""
    module = _voice_gender_module()
    if module is None:
        return None
    row = next((r for r in unit.get("character_entities") or []
                if isinstance(r, dict) and str(r.get("character_id") or r.get("entity_id") or "") == str(character_id)),
               None)
    return module.character_gender(row)["gender"] if row else None

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
#: fleet 2026-11-13 (device 1037 E06: 7 of 21 units PLOT_DEFECT_P1:BURNED_IN_SUBTITLES): H3 writes the spoken line into
#: the frame.  The V1 renderer states its anti-text rule first (E12 K031/K143); V2 must start with "References:", so
#: the rule is named in full here and repeated right after the dialogue literal (SPOKEN_NOT_WRITTEN_*).
NEVER_V2 = "captions, subtitles, letters or logos on screen; a second copy of anyone"
#: KO E05 on device ...0080 (2026-11-21): "the camera shakes along with a character's small movements -- the person AND
#: the background move together".  A locked-off plan states the stillness of the SET, not only of the camera position;
#: a deliberate move keeps its wording and is told to stay steady.  Plain sentences (no all-caps label H3 could voice).
LOCKED_OFF_STILL = "The set behind the people stays perfectly still; only the people move, never the frame."
STEADY_MOVE = ("Apart from that one move the camera is steady: the frame never shakes, sways or bobs with a "
               "person's movement.")
FRAME_WOBBLE_NEVER = "the frame moving with a person"
#: CAMERA_GRAMMAR_V1 (stamped) units; unstamped units stay byte-identical
NEVER_V2_STAMPED = ("captions, subtitles, speech bubbles or any written words, letters or numbers on screen; logos or "
                    "watermarks; a second copy of anyone")  # keeps the scope-gate marker "captions, subtitles"
#: live-action skin / hair finish on stamped units (v1.SKIN_FINISH_NEGATIVE in "Never:" wording)
SKIN_FINISH_NEVER = "oily, glossy or sweaty skin sheen, wet-looking hair or over-sharpened skin texture"
#: anime skin / hair finish on stamped anime units (v1.ANIME_FINISH_NEGATIVE in "Never:" wording; JA-01 E01 2026-11-20)
ANIME_FINISH_NEVER = ("glossy, oily or wet-looking shine on skin or hair, or 3D-rendered skin shading (keep flat matte "
                      "cel shading)")
#: identity lock (line owner 2026-11-20, JA-01 anime E01: with the scene and angle unchanged, the person on screen
#: transformed in place into the character who speaks).  Stamped units with people, said once after the references.
IDENTITY_LOCK_V2 = ("Each person keeps their own reference face, hair and outfit to the last frame and never turns into "
                    "another character, even the speaker.")
#: said once after the dialogue literal(s): the words exist as sound only.  No all-caps label (H3 voices labels).
SPOKEN_NOT_WRITTEN_ONE = ("The line is only heard: the picture stays clean, with no subtitle, caption or written "
                          "word of it.")
SPOKEN_NOT_WRITTEN_MANY = ("The lines are only heard: the picture stays clean, with no subtitles, captions or "
                           "written words of them.")


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


#: stamped prompts (owner 2026-11-02, lab 化神 E01-VU-002): a quoted sentence outside the dialogue tags is a known
#: trigger for H3 to voice the text; a "Only for shot <id> :" scope prefix may arrive with a space or an empty id
_SCOPE_PREFIX_ANY = re.compile(r"^\s*Only for shot\s*[A-Za-z0-9_-]*\s*:\s*", re.IGNORECASE)
_QUOTED = re.compile(r"[\"“]([^\"”]*)[\"”]")
QUOTED_WORDS_MAX = 6
_BRIDGE_RESTATEMENT = re.compile(r"Previous beat end state\b.*\bNext beat entry state\b", re.IGNORECASE | re.S)


def _unquote_long(text: str) -> str:
    """Drop the quote marks around any quoted span longer than QUOTED_WORDS_MAX words (the words stay)."""
    return _QUOTED.sub(lambda m: m.group(0) if len(m.group(1).split()) <= QUOTED_WORDS_MAX
                       else m.group(1).strip().rstrip(".;, "), text)


def sound_row_v2(value: Any) -> str:
    """A stamped Sound row in plain words: no shot-scope prefix, no quoted action / dialogue / meta-instruction
    ('contact sounds from "<the action>" through clothing ...' -> 'contact sounds of clothing ...')."""
    text = _SCOPE_PREFIX_ANY.sub("", " ".join(str(value or "").split()))
    text = re.sub(r"\s*\bfrom\s+[\"“][^\"”]*[\"”]\s*(?:through\s+)?", " of ", text)
    text = re.sub(r"\bEmphasi([sz])e only\s+[\"“][^\"”]*[\"”]\s*", r"Emphasi\1e only ", text)
    text = _QUOTED.sub(lambda m: m.group(0) if len(m.group(1).split()) <= QUOTED_WORDS_MAX else "the action", text)
    return " ".join(text.split())


def long_quoted_spans(text: str) -> list[str]:
    """Double-quoted spans longer than QUOTED_WORDS_MAX words outside the <d> dialogue tags."""
    outside = re.sub(r"<d>\[[A-Za-z]+\].*?</d>", "", text, flags=re.S)
    return [m.group(1) for m in _QUOTED.finditer(outside) if len(m.group(1).split()) > QUOTED_WORDS_MAX]


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
            # a per-shot wardrobe STATE (prompt_spec.wardrobe_state_overrides) replaces the base wardrobe, as the
            # keyframe compiler already does (build_keyframe_manifest); …1324 E05-S04-26: the keyframe showed the
            # clean change of clothes while the video prompt still asked for the patched tunic
            overrides = spec.get("wardrobe_state_overrides") if isinstance(spec.get("wardrobe_state_overrides"), dict) else {}
            override = overrides.get(cid) or overrides.get(str(member.get("character") or ""))
            rows[cid] = {"entity_id": cid, "kind": "PERSON",
                         "name": str(member.get("character") or entity.get("canonical_name") or ""),
                         "appearance": str(appearance or ""),
                         "wardrobe": str(override or dress.get("authored_description") or "").strip()}
        for prop in spec.get("props") or []:
            pid = str(prop.get("prop_id") or prop.get("prop") or "")
            if not pid or pid in rows or not is_being_prop(prop):
                continue
            rows[pid] = {"entity_id": pid, "kind": "BEING", "name": str(prop.get("english_name") or prop.get("prop") or ""),
                         "look": str(prop.get("note") or ""), "creature_card": prop.get("creature_card") or {}}
    return list(rows.values())


_LOCATION_ID_PREFIX = re.compile(r"^(?:(?:LOC|LOCATION|SCENE|PLACE|SET|SPACE)[-_])+(?:E\d+[-_])?", re.IGNORECASE)


def location_id_words(location_id: Any) -> str:
    """``LOC-ANCHENG-TEAHOUSE`` -> ``Ancheng teahouse`` (an id made readable; '' for none / UNKNOWN_LOCATION)."""
    text = str(location_id or "").strip()
    if not text or text.upper() in {"UNKNOWN_LOCATION", "UNSPECIFIED"}:
        return ""
    words = " ".join(w for w in re.split(r"[-_\s]+", _LOCATION_ID_PREFIX.sub("", text)) if w)
    if CJK.search(words):
        return words
    words = words.lower()
    return words[:1].upper() + words[1:]


def scene_location_words(unit: dict[str, Any]) -> str:
    """The unit's own scene location in words (H3_LOCATION_FIRST, device 1101 E24 2026-11-23): an authored English /
    Chinese place name on the first shot (``space.location_en`` / ``location_name`` / ``scene_state.room``) when
    present, else the scene's location id made readable.  '' when the unit declares no location."""
    specs = unit.get("ordered_prompt_specs") or []
    first = specs[0] if specs and isinstance(specs[0], dict) else {}
    space = first.get("space") if isinstance(first.get("space"), dict) else {}
    scene = first.get("scene_state") if isinstance(first.get("scene_state"), dict) else {}
    for value in (space.get("location_en"), space.get("location_name"), space.get("location_label"),
                  scene.get("room_en"), scene.get("room")):
        text = " ".join(str(value or "").split())
        if text and not INTERNAL_ID.fullmatch(text):
            return text
    return location_id_words(space.get("location"))


def setting_source(unit: dict[str, Any]) -> str:
    """Authored location + light words for the Setting line (any language).

    H3_LOCATION_FIRST (device 1101 E24, 2026-11-23: every shot of a teahouse / rouge-shop / boat episode came out as
    the series' "mountain gate and broad spirit fields"): the unit's OWN scene location leads; the series-wide
    story_world follows as era context, and the series-wide production_design (which names the series' standing
    places) is left out whenever the unit has a location of its own."""
    vcc = unit.get("visual_culture_contract") if isinstance(unit.get("visual_culture_contract"), dict) else {}
    specs = unit.get("ordered_prompt_specs") or []
    first = specs[0] if specs else {}
    scene = first.get("scene_state") or {}
    design = first.get("visual_design") or {}
    # the middle-ground layer restates the beat's action: the Action section owns that
    layers = [row for row in design.get("depth_layers") or []
              if isinstance(row, str) and not re.match(r"\s*(?:中景|middle ?ground)", row, re.IGNORECASE)]
    location = scene_location_words(unit)
    parts = [location, *layers, design.get("key_light") or scene.get("lighting"), vcc.get("story_world")]
    if not location:
        parts.append(vcc.get("production_design"))
    seen: list[str] = []
    for value in parts:
        value = " ".join(str(value or "").split())
        if value and not INTERNAL_ID.fullmatch(value) and value not in seen:
            seen.append(value)
    return "；".join(seen)


#: CAMERA_GRAMMAR_V1 dialogue Delivery (owner 2026-11-04, lab 化神 E04 "语音声调起伏不够大，没有感情"): the
#: writer's delivery_en filled up with anti-error meta ("say it once / start immediately / do not echo the
#: reference / keep the same timbre", redo notes) and the renderer appended the same generic tail to every line,
#: so the emotion and the contour were a minority of the words H3 read.  Delivery now leads with the emotion and
#: the authored contour only; once/no-extra-words is said by the Dialogue header and ONLY_THIS_LINE, timbre by the
#: @Audio1 reference line, and a redo note ("The previous take ...") is said once per prompt after the dialogue.
_EMOTION_EXTRA = (("倦", "weary"), ("懒", "lazy"), ("坚", "resolute"), ("慌", "panicked"), ("狠", "fierce"),
                  ("傲", "haughty"), ("得意", "smug"), ("乐", "amused"), ("委屈", "aggrieved"))
_DELIVERY_META = re.compile(
    r"reference|timbre|\becho|\bquote|\bsample\b|same voice|\bonce\b|immediately|right away|at the (?:very )?start"
    r"|introductory|invented|extra (?:words|syllables|speech)|unwanted|no other words|authored line"
    r"|natural breathing|never a flat read|clear rises and falls|this take|lips? (?:in )?sync",
    re.IGNORECASE)
_REDO_NOTE = re.compile(r"\b(?:previous|last|earlier) take\b", re.IGNORECASE)
DELIVERY_EN_LIMIT = 240


def _emotion_words(emotion: Any) -> list[str]:
    text, found = str(emotion or ""), []
    for key, word in sorted(v1._EMOTION_EN + _EMOTION_EXTRA, key=lambda kv: -len(kv[0])):
        at = text.find(key)
        if at >= 0 and word not in [w for _, w in found]:
            found.append((at, word))
            text = text.replace(key, " " * len(key))
    return [word for _, word in sorted(found)]


def stamped_delivery(performance: Any) -> tuple[str, list[str]]:
    """(``Delivery: <emotion>: <contour>.``, redo notes) for a CAMERA_GRAMMAR_V1 dialogue beat; ("", []) when
    the writer gave neither an English contour nor a mappable emotion (the caller keeps the canned clause)."""
    if not isinstance(performance, dict):
        return "", []
    raw = re.sub(r"[<>\[\]]", "", str(performance.get("delivery_en") or ""))
    raw = "" if CJK.search(raw) else " ".join(raw.split())
    kept, redo = [], []
    for sentence in re.split(r"(?<=[.!?])\s+", raw):
        if _REDO_NOTE.search(sentence):
            note = re.split(r";|,? this take\b", sentence, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,;.")
            if note:
                redo.append(note[0].upper() + note[1:] + ".")
            continue
        clauses = [c.strip() for c in re.split(r"[;,]\s*|\s+-+\s+|\.\s*$", sentence) if c.strip(" .")]
        clauses = [c.strip(" .") for c in clauses if not _DELIVERY_META.search(c)]
        clauses = [re.sub(r"^(?:and|then|but)\s+(?=\S)", "", c) if i == 0 else c for i, c in enumerate(clauses)]
        if clauses:
            kept.append(", ".join(clauses))
    contour = "; ".join(kept)
    if len(contour) > DELIVERY_EN_LIMIT:
        contour = contour[:DELIVERY_EN_LIMIT].rsplit(",", 1)[0].rsplit(";", 1)[0].strip(" ,;")
    emotions = [w for w in _emotion_words(performance.get("emotion")) if w not in contour.lower()]
    lead = " and ".join(emotions[:2])
    if contour and lead:
        body = f"{lead} — " + (contour if re.match(r"I\b|[A-Z]{2}", contour) else contour[:1].lower() + contour[1:])
    elif contour:
        body = contour
    elif lead:
        body = f"{lead}, the pitch and volume rising and falling with the meaning, the key word stressed"
    else:
        return "", redo
    return _sentence("Delivery: " + body[0].upper() + body[1:]), redo


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


def offscreen_only_entity_ids(unit: dict[str, Any]) -> set[str]:
    """Entities a shot of this unit declares offscreen (cast OFFSCREEN_VOICE_ONLY or an OFFSCREEN
    presence) and no shot of it shows."""
    specs = [spec for spec in unit.get("ordered_prompt_specs") or [] if isinstance(spec, dict)]
    declared: set[str] = set()
    for spec in specs:
        role = spec.get("role_semantic_disambiguation") or {}
        declared |= {str(cid) for cid, presence in (role.get("entity_presence") or {}).items()
                     if "OFFSCREEN" in str(presence or "").upper()}
        declared |= {str(member.get("character_id") or member.get("character") or "")
                     for member in spec.get("cast") or []
                     if str(member.get("face_visibility") or "").upper() == "OFFSCREEN_VOICE_ONLY"}
    return {cid for cid in declared if cid and not any(_visible_in_spec(spec, cid) for spec in specs)}


# ----------------------------------------------------------------------------------------------------------
# who / what the action names (device 1101 E24 review, 2026-11-23)
# ----------------------------------------------------------------------------------------------------------
def frame_entity_ids(unit: dict[str, Any]) -> set[str]:
    """The subjects "Who is in frame" lists: every cast member / carded being some shot of the unit shows."""
    specs = [spec for spec in unit.get("ordered_prompt_specs") or [] if isinstance(spec, dict)]
    return {row["entity_id"] for row in subject_sources(unit)
            if any(_visible_in_spec(spec, row["entity_id"]) for spec in specs)}


def _name_key(value: Any) -> str:
    text = str(value or "")
    return re.sub(r"[^a-z]", "", text.lower()) if text.isascii() else ""


def _person_name_keys(unit: dict[str, Any], plan: dict[str, Any] | None, cid: str, row: dict[str, Any]) -> set[str]:
    labels = v1._entity_labels(unit, plan or {})
    values = [row.get("english_name"), row.get("canonical_name"), *(row.get("aliases") or []), labels.get(cid),
              _id_label(cid)]
    return {key for key in (_name_key(v) for v in values) if len(key) >= 4}


_OFFSCREEN_WORDS = re.compile(r"off-?screen|out of (?:the )?frame|unseen|\bvoice\b", re.IGNORECASE)


def people_named_outside_frame(unit: dict[str, Any], plan: dict[str, Any] | None, texts: list[Any]) -> list[str]:
    """Names of episode characters that the given English action texts name although "Who is in frame" does not list
    them (H3 then draws them: E24-VU-001 "Lingyao presses a dagger to Wang Defa's throat" with only Lingyao cast
    rendered a stranger's hand holding a blade to HER throat).  A capitalised 1-3 word span is matched against each
    absent character's English name / pinyin aliases / id; a declared offscreen speaker may be named in a sentence
    that says so (offscreen / out of frame / voice)."""
    in_frame = frame_entity_ids(unit)
    catalog = _catalog(unit)
    # a cast row may carry only the Chinese name: the catalog entry of that name / alias is in frame too
    in_frame |= {cid for cid, row in catalog.items()
                 if {str(row.get("canonical_name") or ""), *map(str, row.get("aliases") or [])} & in_frame}
    keys_in_frame: set[str] = set()
    for cid in in_frame:
        keys_in_frame |= _person_name_keys(unit, plan, cid, catalog.get(cid) or {})
    offscreen = offscreen_only_entity_ids(unit)
    absent = {cid: _person_name_keys(unit, plan, cid, row) - keys_in_frame
              for cid, row in catalog.items() if cid not in in_frame}
    found: list[str] = []
    for text in texts:
        for sentence in re.split(r"(?<=[.!?;])\s+", " ".join(str(text or "").split())):
            words = re.findall(r"[A-Za-z][A-Za-z'’-]*", sentence)
            spans = {}
            for i, word in enumerate(words):
                if not word[:1].isupper():
                    continue
                for n in (1, 2, 3):
                    if i + n <= len(words):
                        spans[_name_key("".join(re.sub(r"['’]s$", "", w) for w in words[i:i + n]))] = \
                            " ".join(words[i:i + n])
            for cid, keys in absent.items():
                hit = next((spans[k] for k in keys if k in spans), None)
                if not hit or (cid in offscreen and _OFFSCREEN_WORDS.search(sentence)):
                    continue
                label = re.sub(r"['’]s$", "", hit)
                if label not in found:
                    found.append(label)
    return found


#: object nouns an action can name without the contract declaring the prop (en word -> zh source words)
PROP_NOUNS: dict[str, tuple[str, ...]] = {
    "dagger": ("匕首", "短刀"), "knife": ("小刀", "刀子"), "sword": ("长剑", "宝剑", "佩剑"), "blade": ("刀刃", "刀锋"),
    "talisman": ("符纸", "符箓", "符咒", "灵符"), "scroll": ("卷轴",), "skull": ("骷髅", "头骨"),
    "box": ("盒子", "木盒", "锦盒"), "letter": ("信笺", "书信"), "token": ("令牌",), "pendant": ("玉佩",),
    "hairpin": ("发簪", "簪子"), "handkerchief": ("手帕", "丝帕"), "mirror": ("镜子", "铜镜"), "lantern": ("灯笼",),
    "spear": ("长枪",), "whip": ("鞭子",), "chain": ("锁链", "铁链"), "tray": ("托盘",), "gourd": ("葫芦",),
    "pill": ("丹药",), "teacup": ("茶杯",), "bowl": ("碗",), "bottle": ("药瓶", "瓶子"), "rouge": ("胭脂",),
    "ledger": ("账本", "账簿"),
}


def _prop_rows(unit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for spec in unit.get("ordered_prompt_specs") or []:
        for prop in (spec.get("props") or []) if isinstance(spec, dict) else []:
            pid = str(prop.get("prop_id") or prop.get("prop") or "")
            if pid and pid not in rows and not is_being_prop(prop):
                rows[pid] = prop
    return rows


def _prop_names(pid: str, prop: dict[str, Any]) -> list[str]:
    names = [_en(prop.get("english_name"), 60), _en(prop.get("prop"), 60), _id_label(pid).lower()]
    return [n.lower() for n in dict.fromkeys(n for n in names if n and len(n) >= 3)]


def _prop_description(prop: dict[str, Any]) -> str:
    for key in ("description_en", "appearance_en", "look_en", "physical_description_en", "note", "physical_function"):
        text = _en(prop.get(key), 200)
        if text:
            return text
    return ""


def named_props(unit: dict[str, Any], texts: list[Any]) -> list[dict[str, Any]]:
    """Objects the action names (H3_PROP_NAMED_DESCRIBED, device 1101 E24: the talisman became a placard, the dagger a
    sword and then another blade, the skull a toy on a tray).  One row per object: declared props first
    ({key: prop id, name, description, declared: True}), then PROP_NOUNS the text names that no declared prop covers
    ({key: the noun, declared: False}).  Source texts may be Chinese (the zh words of PROP_NOUNS) or English."""
    joined = " ".join(" ".join(str(t or "").split()) for t in texts)
    low = joined.lower()
    out: list[dict[str, Any]] = []
    covered: set[str] = set()
    for pid, prop in _prop_rows(unit).items():
        names = _prop_names(pid, prop)
        zh = str(prop.get("prop") or "")
        if any(re.search(r"\b" + re.escape(n) + r"s?\b", low) for n in names) or (zh and CJK.search(zh) and zh in joined):
            out.append({"key": pid, "name": names[0] if names else pid, "description": _prop_description(prop),
                        "declared": True})
            covered |= {w for n in names for w in n.split()}
            covered |= {noun for noun, zh_words in PROP_NOUNS.items() if zh and any(z in zh for z in zh_words)}
    for noun, zh_words in PROP_NOUNS.items():
        if noun in covered:
            continue
        if re.search(r"\b" + noun + r"s?\b", low) or any(z in joined for z in zh_words):
            out.append({"key": noun, "name": noun, "description": "", "declared": False})
    return out


def _source_action_texts(unit: dict[str, Any], plan: dict[str, Any] | None) -> list[str]:
    texts: list[str] = []
    for beat in _beats(plan or {}):
        texts += [str(beat.get(k) or "") for k in ("entry_state", "primary_action", "exit_state", "contact_point")]
    for spec in unit.get("ordered_prompt_specs") or []:
        action = spec.get("action") if isinstance(spec, dict) and isinstance(spec.get("action"), dict) else {}
        texts += [str(action.get(k) or "") for k in ("primary_action", "start_state", "completion_state")]
    return texts


def english_action_texts(contract: dict[str, Any]) -> list[str]:
    """Every English action-side text of a bound contract (beats, holds, transitions)."""
    texts: list[str] = []
    for beat in contract.get("beats") or []:
        if isinstance(beat, dict):
            texts += [str(beat.get(k) or "") for k in ("entry_state", "primary_action", "exit_state", "force_origin",
                                                       "contact_point", "primary_feedback", "force_feedback",
                                                       "internal_transition_after")]
            texts += [str(v or "") for v in beat.get("secondary_feedback") or []]
    texts += [str(contract.get("persistent_state_lock") or "")]
    texts += [str(v or "") for v in contract.get("shot_state_locks") or []]
    texts += [str(v or "") for v in (contract.get("transition") or {}).values()]
    return texts


def period_setting(unit: dict[str, Any]) -> bool:
    """The unit's world is pre-modern (PERIOD_TRAIT_LOCK; visual_culture_contract.is_premodern_period)."""
    return _vcc.is_premodern_period(unit.get("visual_culture_contract"), dialogue_language=unit.get("dialogue_language"))


#: H3 Never items of a pre-modern world (PERIOD_TRAIT_LOCK, device 1101 E24: round eyeglasses on a xianxia demon)
PERIOD_NEVER_V2 = "; ".join(_vcc.PERIOD_FORBIDDEN_ITEMS_EN)
#: Look line of a pre-modern AUTHORED_WORLD unit (its world lock is otherwise left out as filler)
PERIOD_LOOK_V2 = ("Look: keep the period, architecture, dress and props of this pre-modern world exactly as the "
                  "references and the described facts show; real materials, soft motivated light; no modern object "
                  "or accessory anywhere in frame.")


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
    elif camera_plan.get(v1.BILI_PUSH_IN_MARK):  # BILI_V1: the scene's one slow push-in (director_pass)
        parts.append(f"{v1.BILI_PUSH_IN_CLAUSE[0].upper()}{v1.BILI_PUSH_IN_CLAUSE[1:]}, {head}." if head
                     else f"{v1.BILI_PUSH_IN_CLAUSE[0].upper()}{v1.BILI_PUSH_IN_CLAUSE[1:]}.")
        parts += [v1.ONE_TAKE] if stamped and one_take else []
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
    if one_setup_take(unit, rows, uid):
        # one speaker's consecutive lines in one unchanged locked setup (owner 2026-11-01, monologue groups):
        # ONE camera entry for the whole clip, never a per-line shot list H3 could read as cuts
        english = v1._camera_english(uid, rows[0]["shot_id"] or "SHOT_1", rows[0]["camera_plan"],
                                     translated[0] if translated and isinstance(translated[0], dict) else {}, [])
        return _camera_entry(rows[0]["camera_plan"], english, one_take=True), [
            {"shot_id": row["shot_id"] or f"SHOT_{i + 1}",
             "boundary": "opening shot" if i == 0 else "same take, unchanged camera setup",
             "fields": sorted(english), "untranslated_fields": []} for i, row in enumerate(rows)]
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


def one_setup_take(unit: dict[str, Any], rows: list[dict[str, Any]], uid: str) -> bool:
    """CAMERA_GRAMMAR_V1: several shots joined without a cut that all keep one locked camera setup
    (speaking_unit_duration.setup_key) -- a speaker's monologue group -- are one camera entry."""
    if len(rows) < 2:
        return False
    plans = [row.get("camera_plan") or {} for row in rows]
    if not all(p.get("camera_grammar") == "CAMERA_GRAMMAR_V1" and _sud.locked_setup(p) for p in plans):
        return False
    if len({_sud.setup_key(p) for p in plans}) != 1:
        return False
    try:
        boundaries = [v1._shot_boundary(unit, i - 1, rows[i - 1], rows[i], uid) for i in range(1, len(rows))]
    except ValueError:
        return False
    return all(b.startswith("no cut") for b in boundaries)


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
                     beings: int, exact_first_frame: bool = False,
                     face_hidden: dict[str, str] | None = None) -> list[str]:
    refs = unit.get("reference_images") or []
    sequence_by_path = {str(row.get("path") or ""): row for row in unit.get("reference_image_sequence") or []
                        if row.get("path") and str(row.get("entity_id") or "").startswith("CHAR-")}
    scope = unit.get("provider_scope_projection") or {}
    scope_bindings = {int(row["reference_index"]): row for row in scope.get("reference_identity_bindings") or []
                      if row.get("reference_index") is not None}
    face_only = v1.face_only_identity_paths(unit)  # PIXEL_CROP transports
    # field E11 2026-11-15 (device 1101, VU-005/006): an object insert with an offscreen line has NOBODY on
    # screen, so ``onscreen`` is empty and the speaker's sheet was described as "already in @Image1" next to
    # "Who is in frame: nobody".  A declared offscreen-only entity is out of frame whatever ``onscreen`` holds.
    offscreen_only = offscreen_only_entity_ids(unit)
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
            face_crop = index > 1 and str(ref.get("path") or "") in face_only
            line = (f"@Image{index} is {v1.reference_sheet_clause(entity)}." if v1.is_reference_sheet(ref)
                    else f"@Image{index} is {entity}'s face only: a face crop; clothing and headwear come from "
                         "@Image1 and the wardrobe text, never from this crop." if face_crop
                    else f"@Image{index} is {entity}'s {body}.")
            hidden = (face_hidden or {}).get(entity_id) if entity_id else None
            if hidden and not ((onscreen and entity_id not in onscreen) or entity_id in offscreen_only):
                # a partial-visibility listener: an unqualified "face and body" pulls a front face in
                line = (f"@Image{index} is {entity}'s identity reference: use @Image{index} only for {entity}'s "
                        + ("hair, build and wardrobe from behind" if hidden == "BEHIND" else "build and wardrobe")
                        + f"; {entity}'s face is not shown.")
            if entity_id and ((onscreen and entity_id not in onscreen) or entity_id in offscreen_only):
                line += (f" It is for identity only: {entity} stays out of frame in this clip; nobody on screen takes "
                         f"on {entity}'s face, hair or outfit.")
            elif index > 1:
                # a face reference of someone already in the opening frame is that SAME person, not a second
                # one: H3 otherwise sometimes renders the reference as an extra copy (lab E02 2026-10-23)
                line += (f" This is the same {entity} already {'in' if exact_first_frame else 'standing in'} @Image1 — one person; never draw a "
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
        elif role == v1.SCENE_LOCATION_REFERENCE_ROLE:  # SCENE_LOCATION_LOCK_V1 (JA-01 E08)
            lines.append(f"@Image{index} is this scene's location, for the background and location only: keep the same "
                         "place, background, set dressing and light for the whole clip; it defines no face and puts "
                         "nobody in frame.")
        else:
            lines.append(f"@Image{index} is a supporting continuity reference: match only what it shows of the "
                         "setting and props; it defines no face.")
    return lines


def _bili_v1_parts(unit: dict[str, Any], plan: dict[str, Any], source: dict[str, Any], translated: dict[str, Any],
                   spec: dict[str, Any], parts: list[str], evidence: dict[str, str], prefix: str,
                   label_by_id: dict[str, str], speaker_label: str, kept: list[str], scrub: Any) -> list[str]:
    """BILI_V1 only (CHANGE_SPEC WP4 items 2-3): the beat's authored lead-in reaction first ("For the first 1.5
    seconds, before speaking, ..."), then the authored micro-expression / body-sync / contact the writer wrote
    (field_sources "authored"; a preproduction fallback template stays omitted as before)."""
    action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
    role = spec.get("role_semantic_disambiguation") or {}
    owner_id = str(role.get("dialogue_speaker_id") or "") if speaker_label else str(
        role.get("primary_actor_id") or action.get("subject_id") or "")
    owner_label = speaker_label or label_by_id.get(owner_id, "")
    owners = ([(owner_id, owner_label)] if owner_label else []) + [
        (cid, label) for cid, label in label_by_id.items() if label != owner_label]
    lead = v1._bili.lead_in_sentences(action, owners)
    if lead:
        evidence[f"{prefix}.LEAD_IN_REACTION"] = " ".join(lead)
        parts = [*lead, *parts]
    authored_rows = (
        ("MICROEXPRESSION", "microexpression_cue", "Face", v1._bili.authored(action, "microexpression_design")),
        ("BODY_SYNC", "body_sync_cue", "Body", True),  # performance.body_sync: writer-authored only, no template
        ("CONTACT_POINT", "contact_point", "Contact", v1._bili.authored(action, "contact_point")),
    )
    for fact, key, head, is_authored in authored_rows:
        fact_id = f"{prefix}.{fact}"
        if not is_authored or not source.get(key) or evidence.get(fact_id):
            continue
        text = scrub(translated.get(key) or "")
        if not v1._bili.english(text):
            continue
        sentence = _sentence(f"{head}: {text}")
        parts.append(sentence)
        evidence[fact_id] = sentence
        kept.append(fact_id)
    return parts


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
    bili = v1._bili.active(unit)  # BILI_V1 carry-through (CHANGE_SPEC WP4); False on every LEGACY unit
    kept_fact_ids: list[str] = []  # BILI_V1: authored facts V2 states instead of omitting (coverage receipt)

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
    # H3_ACTION_NAMES_ONLY_FRAME (device 1101 E24): an action that names someone "Who is in frame" does not list makes
    # H3 invent that person (a stranger's hand, a kneeling armoured figure).  Refused here; the English-contract
    # binding (h3_english_contract_io.apply_answers) sends the same finding back to the writer first.
    listener_texts = [str((spec.get("action") or {}).get("listener_reaction_en") or "")
                      for spec in unit.get("ordered_prompt_specs") or [] if isinstance(spec, dict)
                      and isinstance(spec.get("action"), dict) and not isinstance(
                          (spec.get("action") or {}).get("listener_reaction_en"), dict)]
    outside = people_named_outside_frame(unit, plan, english_action_texts(contract) + listener_texts)
    if outside:
        raise ValueError(f"{uid}:H3_ACTION_NAMES_PERSON_NOT_IN_FRAME:" + ",".join(outside))
    background_declared = bool(director_v2_background_clause(unbound_total,
                                                             scope.get("anonymous_role_descriptors") or []))

    # --- references ------------------------------------------------------------------------------------
    # OTS_LISTENER_V1: someone whose face is hidden in every beat they are in uses the sheet for the look only
    face_hidden = {s["entity_id"]: ("BEHIND" if any(p.startswith("back") or "shoulder" in p
                                                    for p in s["partial"].values()) else "PARTIAL")
                   for s in subjects if s["partial"] and len(s["partial"]) == len(s["present"])
                   and set(s["partial"].values()) != {v1.SOFT_PROFILE_PART}}  # a soft profile shows the face
    reference_lines = _reference_lines(unit, plan, onscreen=onscreen_ids, people=len(people), beings=len(beings),
                                       exact_first_frame=stamped, face_hidden=face_hidden)
    if stamped and people and any("'s face and body." in line or "'s face only" in line or "character sheet of one" in line
                                  for line in reference_lines):
        reference_lines.append(IDENTITY_LOCK_V2)
    for index, row in enumerate(crossmodal_rows, 1):
        binding = f"{row['audio_slot']} is {row['provider_entity_label']}'s voice"
        # casting gender (2026-11-20, JA-01 E02 / 摄政王 E18: a woman on screen spoke with a man's voice): say whose
        # voice it is in plain words, so a youthful or disguised look never pulls H3 to the other voice
        gender = speaker_voice_gender(unit, str(row.get("character_id") or "")) if stamped else None
        voice_kind = ("a woman's voice" if gender == "female" else "a man's voice" if gender == "male" else "")
        reference_lines.append(binding + (f", {voice_kind}" if voice_kind else "")
                               + ". It gives timbre only — never speak or echo its words.")
        evidence[f"VOICE_BINDING.{index}"] = binding

    # --- who is in frame -------------------------------------------------------------------------------
    framing_text = " ".join(str(v) for v in [
        (contract.get("camera_plan") or {}).get("start_framing"),
        *[(row or {}).get("start_framing") for row in contract.get("camera_plans") or [] if isinstance(row, dict)],
    ] if v)
    who_lines: list[str] = []
    whole = all(len(s["present"]) == len(beats) and not s["partial"] for s in subjects)
    ots_labels = [s["label"] for s in subjects if v1.OTS_PART in s["partial"].values()]
    subjects_v2 = (v2_english.get("subjects") or {}) if isinstance(v2_english.get("subjects"), dict) else {}

    def look_of(s: dict[str, Any], compact: bool) -> str:
        if compact:
            return ""
        answer = subjects_v2.get(s["entity_id"]) or subjects_v2.get(s["label"]) or {}
        if s["kind"] == "BEING":
            card = s.get("creature_card") or {}
            gait = {"biped": "moves upright on two legs", "quadruped": "moves on four legs",
                    "slithering": "has no legs and slithers along the ground", "flying": "flies on its wings"}.get(
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
            insert = "an anime insert" if _render_style.is_anime(unit) else "a photographic insert"
            return [f"Who is in frame: nobody — {insert} of {_join_names(props) if props else 'the object described below'}; "
                    "no people, no hands, no body parts."]
        noun = ("person" if total == 1 else "people") if not beings else (
            "being" if total == 1 and not people else "beings" if not people else "subjects")
        core = director_v2_population_core(total)
        multi = any(int(counts.get(s["entity_id"]) or 1) > 1 for s in subjects)
        once = "each as listed" if multi else ("exactly once" if total == 1 else "each exactly once")
        if whole:
            presence = ("visible from the first frame to the last" if total == 1 else
                        f"{'both' if total == 2 else 'all'} visible from the first frame to the last")
        elif ots_labels:
            # OTS_LISTENER_V1: say plainly who faces the camera and who is the back-of-head foreground figure
            facing = [s["label"] for s in people if s["label"] not in ots_labels]
            ots_whole = all(len(s["present"]) == len(beats) and (
                s["label"] not in ots_labels and not s["partial"]
                or s["label"] in ots_labels and len(s["partial"]) == len(beats)
                and all(p == v1.OTS_PART for p in s["partial"].values())) for s in subjects)
            presence = ((f"{_join_names(facing)} face{'s' if len(facing) == 1 else ''} camera; " if facing else "")
                        + f"{_join_names(ots_labels)} in the foreground from behind (face not shown)"
                        + ("" if ots_whole else "; presence as noted for each"))
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
                line += (f" {window}: {v1.ots_clause(s['label'])}." if part == v1.OTS_PART else
                         f" {window}: {v1.soft_profile_clause(s['label'])}." if part == v1.SOFT_PROFILE_PART else
                         f" {window}: only {s['label']}'s {part} in frame; {s['label']}'s face is not shown."
                         if part else f" {window}: {s['label']}'s face stays out of frame.")
            lines.append(line)
        held = v1._bili.held_prop_sentences(unit, label_by_id) if bili else []
        if held:  # BILI_V1 (WP4 item 5): declared props in hand, not only when an action names them
            lines.append("In hand: " + "; ".join(held) + ".")
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
            value = scrub(sound_row_v2(value) if stamped else value)
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
    anime = _render_style.is_anime(unit)
    if anime:  # render_style=anime: the art style first, as an ordinary sentence (no all-caps label)
        setting_lines.insert(0, _sentence("Art style: " + _render_style.H3_ART_STYLE_LINE.split(": ", 1)[1].replace("NOT ", "not ")))
    look = v1.h3_visual_culture_block(unit)
    neutral_lock = _render_style.anime_lock(v1.H3_NEUTRAL_PERIOD_LOCK) if anime else v1.H3_NEUTRAL_PERIOD_LOCK
    world_lock = _render_style.anime_lock(v1.H3_AUTHORED_WORLD_LOCK) if anime else v1.H3_AUTHORED_WORLD_LOCK
    if stamped and look == neutral_lock:  # no all-caps label H3 could voice (owner 2026-11-01)
        look = _cap(ALL_CAPS_LABEL.sub("", look, count=1).strip())
    period = period_setting(unit)
    if look != world_lock:  # period locks carry real constraints; the authored-world one is filler
        setting_lines.append(_sentence("Look: " + look.rstrip(".")))
    elif period:  # ... except in a pre-modern authored world (PERIOD_TRAIT_LOCK, device 1101 E24)
        setting_lines.append(PERIOD_LOOK_V2)
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
    # H3_PROP_NAMED_DESCRIBED (device 1101 E24): every object the action names is described in words; a carded prop
    # also rides as a reference (append_h3_prop_plates); a named prop without a card is logged (S1 owns that rule)
    props_v2 = v2_english.get("props") if isinstance(v2_english.get("props"), dict) else {}
    reference_entities = {str((r if isinstance(r, dict) else {}).get("entity_id") or "")
                          for r in [*(unit.get("reference_images") or []), *(unit.get("reference_image_sequence") or [])]}
    prop_sentences: list[str] = []
    props_log: dict[str, list[str]] = {"named": [], "without_card": [], "without_description": []}
    for row in named_props(unit, english_action_texts(contract)):
        props_log["named"].append(row["key"])
        description = row["description"] or _en((props_v2.get(row["key"]) or {}).get("description"), 200)
        if not row["declared"] or row["key"] not in reference_entities:
            props_log["without_card"].append(row["key"])
        if not description:
            props_log["without_description"].append(row["key"])
        elif row["name"].lower() not in prop_fact.lower():
            prop_sentences.append(f"the {row['name']} is {description[:1].lower() + description[1:]}")
    if prop_sentences:
        setting_lines.append(_sentence("Props: " + "; ".join(prop_sentences)))

    # --- camera ----------------------------------------------------------------------------------------
    camera, camera_receipt = camera_section(unit, plan, contract, beats)
    # strict camera lock: default on stamped single-take locked units, "standard" opts out (owner 2026-10-26)
    all_locked = all("Locked camera" in line for line in camera.split("\n") if line != v1.ONE_TAKE)
    if stamped and h3_camera_lock(unit) == "strict" and not all_locked:
        raise ValueError(f"{uid}:H3_CAMERA_LOCK_STRICT_ON_MOVING_CAMERA")
    camera_lock = strict_camera_lock_applies(unit, stamped=stamped,
                                             locked_single_take=all_locked and v1.ONE_TAKE in camera)
    if stamped and all_locked:  # the set stays still, only the people move (KO E05 2026-11-21: camera wobble)
        camera += "\n" + LOCKED_OFF_STILL
    elif stamped and "handheld" not in camera.lower():  # a deliberate move stays explicit and steady
        camera += "\n" + STEADY_MOVE
    if camera_lock:  # an ordinary sentence, never an all-caps label H3 could voice (owner 2026-11-01, lab E12)
        camera += "\n" + CAMERA_LOCK_TRIPOD
    # engine redo after an objective Q2 push-in FAIL (q2_auto_redo, owner 2026-10-29): state the measured problem
    if stamped and all_locked:
        for sentence in redo_finding_sentences(unit):
            camera += "\n" + sentence
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
    redo_notes: list[str] = []
    last_exit = ""
    multi_beat = len(beats) > 1
    said_once: set[str] = set()
    business_rendered = False
    for number, (source, translated) in enumerate(zip(beats, english_beats), 1):
        prefix = f"BEAT.{number}"
        spec = _spec_for(unit, source)
        role = spec.get("role_semantic_disambiguation") or {}
        # PERFORMANCE_VARIETY_V1 (JA-01 E08 2026-11-22): a generic placeholder action ("delivers the line with a clear
        # anime gesture and visible posture change") is rebuilt from this beat's own business, never sent as is
        placeholder_replaced = False
        raw_line = str(source.get("dialogue") or "").strip()
        beat_business = (spec.get("action") or {}).get("performance_business_en")
        if raw_line and beat_business:
            line_binding = crossmodal_by_speaker.get(v1._dialogue_partition(raw_line, language)[0].strip()) or {}
            translated, placeholder_replaced = _pv.deplaceholder_beat(
                translated, str(line_binding.get("provider_entity_label") or ""), beat_business)
        entry = scrub(translated["entry_state"])
        action = _cap(scrub(translated["primary_action"]))
        if stamped:  # a sentence repeated in every beat (an engine redo instruction) is said once per prompt
            sentences = re.split(r"(?<=[.!?])\s+", action)
            kept = [x for x in sentences if not (len(x.split()) >= 6 and x.strip() in said_once)]
            said_once.update(x.strip() for x in sentences if len(x.split()) >= 6)
            action = _cap(" ".join(kept).strip()) or action
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
            # visible in THIS beat (the binding's visible_speaker is unit-wide): a speaker shown in another shot of
            # the unit but not in this one speaks from offscreen here, and the people on screen keep their lips
            # closed (2026-11-20 voice/lip-owner review)
            speaker_cid = str(binding.get("character_id") or role.get("dialogue_speaker_id") or "")
            beat_visible = bool(binding.get("visible_speaker")) and (
                not speaker_cid or not spec or _visible_in_spec(spec, speaker_cid))
            literal = f"<d>[{v1.DIALOGUE_LANGUAGE_TAGS[language]}] {words.strip()}</d>"
            evidence[f"{prefix}.DIALOGUE"] = literal
            performance = ((spec.get("action") or {}).get("performance"))
            direction = "" if stamped else v1._performance_direction(performance)
            delivery, redo = stamped_delivery(performance) if stamped else ("", [])
            redo_notes.extend(n for n in redo if n not in redo_notes)
            if stamped:
                delivery = delivery or delivery_clause(source, "EN")
            elif direction:
                body = re.sub(r"^Performance: ", "", direction).split(" Natural human speech")[0].rstrip(".")
                delivery = f"Delivery: {body}. Natural breathing, clear rises and falls, never a flat read."
            else:
                delivery = delivery_clause(source, "EN")
            if delivery:
                evidence[f"{prefix}.DIALOGUE_DELIVERY"] = delivery
            on_screen = [s["label"] for s in subjects if s["kind"] == "PERSON" and (number - 1) in s["present"]
                         and s["label"] != speaker_label and s["entity_id"] != speaker_cid]
            dialogue_rows.append({"label": speaker_label, "literal": literal, "delivery": delivery,
                                  "visible": beat_visible, "listeners": on_screen,
                                  "gaze": v1.speaker_gaze_clause(unit, binding) if stamped and beat_visible else "",
                                  "window": (float(source["start_seconds"]), float(source["end_seconds"]))})
            evidence[f"{prefix}.DIALOGUE_SPEAKER"] = speaker.strip()
            parts.append(_sentence(f"{speaker_label} speaks" + (f" line {len(dialogue_rows)}" if multi_beat else "")
                                   + ("" if beat_visible else " from offscreen")))
            if not beat_visible and on_screen:
                parts.append(_sentence(f"{_join_names(on_screen)} only listen{'s' if len(on_screen) == 1 else ''} "
                                       f"with lips closed; the voice comes from outside the frame"))
            business = (spec.get("action") or {}).get("performance_business_en") if beat_visible else ""
            business_line = _pv.business_sentence(speaker_label, business)
            if business_line and placeholder_replaced:
                business_rendered = True  # the action sentence above already is this business
            elif business_line:
                parts.append(business_line)
                evidence[f"{prefix}.PERFORMANCE_BUSINESS"] = business_line
                business_rendered = True
        if bili:
            parts = _bili_v1_parts(unit, plan, source, translated, spec, parts, evidence, prefix, label_by_id,
                                   speaker_label, kept_fact_ids, scrub)
        parts.append(_sentence(f"End: {exit_state}"))
        evidence[f"{prefix}.EXIT"] = exit_state
        last_exit = exit_state
        if source.get("internal_transition_after"):
            bridge = scrub(translated.get("internal_transition_after") or "")
            if stamped and _BRIDGE_RESTATEMENT.search(bridge):  # the next beat's Start states the entry already
                bridge = "continue the action without resetting"
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
        listener_business = (spec.get("action") or {}).get("listener_business_en")
        listener_business = listener_business if isinstance(listener_business, dict) else {}
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
            elif speaker_label and _pv.listener_sentence(s["label"], listener_business.get(cid)):
                # PERFORMANCE_VARIETY_V1: reactive business instead of a frozen pose
                action_lines.append(_pv.listener_sentence(s["label"], listener_business.get(cid)))
                business_rendered = True
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
        listeners = row.get("listeners") or []
        offscreen_head = (f"Dialogue ({row['label']}, offscreen and not shown, once; "
                          + (f"{_join_names(listeners)} on screen keep{'s' if len(listeners) == 1 else ''} the lips "
                             "closed and only listen" if listeners else "every visible person keeps their mouth closed")
                          + "):")
        dialogue_lines = [f"Dialogue ({row['label']} only, once, lips in sync):" if row["visible"] else
                          offscreen_head, row["literal"]]
        if row["delivery"]:
            dialogue_lines.append(row["delivery"])
        if row.get("gaze"):
            dialogue_lines.append(row["gaze"])
        dialogue_lines.append(v1.ONLY_THIS_LINE if stamped else
                              "After the line nobody speaks; the remaining time is room tone.")
        if stamped:
            dialogue_lines.append(SPOKEN_NOT_WRITTEN_ONE)
    else:
        any_offscreen = any(not row["visible"] for row in dialogue_rows)
        dialogue_lines = ["Dialogue (in this order, each line exactly once, lips in sync; only the named speaker "
                          "talks" + ("; during an offscreen line everyone on screen keeps the lips closed"
                                     if any_offscreen else "") + "):"]
        for number, row in enumerate(dialogue_rows, 1):
            who = row["label"] + ("" if row["visible"] else " (offscreen, not shown)")
            dialogue_lines.append(f"{number}. {who}, {_span(row['window'])}: {row['literal']}"
                                  + (f" {row['delivery']}" if row["delivery"] else "")
                                  + (f" {row['gaze']}" if row.get("gaze") else ""))
        dialogue_lines.append(v1.ONLY_THESE_LINES if stamped else
                              "After the last line nobody speaks; the remaining time is room tone.")
        if stamped:
            dialogue_lines.append(SPOKEN_NOT_WRITTEN_MANY)
    if redo_notes and dialogue_rows:  # a redo note is said once per prompt, never inside each Delivery
        dialogue_lines.append(" ".join(redo_notes))

    # --- never -----------------------------------------------------------------------------------------
    # background figures are allowed only when the projection declares extras (H3_ACTION_NAMES_ONLY_FRAME, E24)
    negatives = [NEVER_V2_STAMPED if stamped else NEVER_V2, "any person, hand or body part" if not subjects else
                 ("anyone beyond the listed people and background figures" if background_declared
                  else "anyone else in frame")]
    if period:
        negatives.append(PERIOD_NEVER_V2)
    for value in contract.get("negative_constraints") or []:
        value = scrub(value)
        if value:
            negatives.append(value[0].lower() + value[1:])
    if wuxia.get("status") == "SELECTED":
        negatives.extend(scrub(v) for v in wuxia.get("negative_constraints_en") or [] if scrub(v))
    if stamped and v1.skin_finish_applies(unit, plan, anime=anime, has_people=bool(subjects)):
        negatives.append(SKIN_FINISH_NEVER)  # live-action skin / hair finish (line owner 2026-11-20, KO E01)
    if stamped and all_locked:  # KO E05 2026-11-21: the set never moves with the actor
        negatives.append(FRAME_WOBBLE_NEVER)
    negatives.append("music")
    if stamped and v1.anime_finish_applies(unit, plan, anime=anime, has_people=bool(subjects)):
        negatives.append(ANIME_FINISH_NEVER)  # anime skin / hair finish (line owner 2026-11-20, JA-01 E01)
    if anime:
        negatives.extend(_render_style.H3_NEGATIVES)
    if camera_lock:
        negatives.append(CAMERA_LOCK_NEVER)
    if business_rendered:  # PERFORMANCE_VARIETY_V1 (line owner 2026-11-20, JA-01 E02)
        negatives.append(_pv.NEVER_STOCK)
        if not _pointing_scripted(unit):  # JA-01 E08 2026-11-22: the same raised index finger on every line
            negatives.append(_pv.NEVER_POINTING)
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
    if stamped:  # no long quoted span outside the dialogue tags (owner 2026-11-02, lab 化神 E01-VU-002)
        text = "".join(part if part.startswith("<d>") else _unquote_long(part)
                       for part in re.split(r"(<d>\[[A-Za-z]+\].*?</d>)", text, flags=re.S))
        evidence = {key: _unquote_long(value) for key, value in evidence.items()}
    if not evidence["ANCHOR.IDENTITY_PROP"]:  # no key props: the cast fact is the "Who is in frame" header
        evidence["ANCHOR.IDENTITY_PROP"] = text.split("\n\n")[1].split("\n")[0]

    boundary = validate_provider_prompt_boundary(text, source_id=uid, model_family="MINIMAX_H3")
    h3_boundary = validate_h3_provider_text_boundary(text, source_id=uid)
    failures = [*boundary["failures"], *h3_boundary["failures"]]
    if failures:
        raise ValueError(";".join(failures))
    coverage = build_semantic_coverage_receipt(plan=plan, prompt_text=text, model_family="MINIMAX_H3",
                                               clause_evidence={k: v for k, v in evidence.items() if v},
                                               prompt_style=DIRECTOR_PROMPT_V2,
                                               **({"keep_fact_ids": kept_fact_ids} if kept_fact_ids else {}))
    if coverage["status"] != "PASS":
        raise ValueError(";".join(coverage["failures"]))
    self_check = director_v2_self_check(text, unit, plan, stamped=stamped)
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
        **({"h3_camera_lock": "strict"} if camera_lock else {}),
        **({"props_named": props_log} if props_log["named"] else {}),
        **({"period_lock": "PRE_MODERN"} if period else {}),
    }


#: the one all-caps label a stamped prompt may still carry: the E54+ qingshan period block, whose token the
#: visual-culture validator requires verbatim (visual_culture_contract.validate_visual_culture_contract)
_REQUIRED_CAPS_LABELS = ("EAST-ASIAN PERIOD VISUAL LOCK:",)


def director_v2_self_check(text: str, unit: dict[str, Any], plan: dict[str, Any], *,
                           stamped: bool = False) -> list[str]:
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
            expected = (f"{window}: {v1.ots_clause(label)}" if row["part"] == v1.OTS_PART
                        else f"{window}: {v1.soft_profile_clause(label)}" if row["part"] == v1.SOFT_PROFILE_PART
                        else f"{window}: only {label}'s {row['part']} in frame" if row["part"]
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
    # owner 2026-11-01 (lab E12 long take): H3 voiced the all-caps "CAMERA LOCK — ABSOLUTE RULE:" label;
    # stamped (CAMERA_GRAMMAR_V1) prompts carry no all-caps label H3 could read aloud
    if stamped:
        findings.extend(f"ALL_CAPS_LABEL_IN_PROMPT:{m.group(0)[:40]}" for m in ALL_CAPS_LABEL.finditer(outside)
                        if m.group(0) not in _REQUIRED_CAPS_LABELS)
        # owner 2026-11-02 (lab 化神 E01-VU-002): a quoted sentence outside <d> is a trigger for H3 to voice it
        findings.extend(f"QUOTED_SENTENCE_IN_PROMPT:{q[:40]}" for q in long_quoted_spans(text))
    return list(dict.fromkeys(findings))
