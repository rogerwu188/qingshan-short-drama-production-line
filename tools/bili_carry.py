#!/usr/bin/env python3
"""BILI_V1 L5 carry-through (CHANGE_SPEC WP4): what the screenplay says reaches the H3 English prompt.

Owner 2026-11-23 (Bilibili benchmark ep2 + ep3): the action, prop, listener reaction, lead-in reaction and delivery
the writer authors in Chinese reach MiniMax-H3 as the writer's own literal English twin (``*_en``), never a mood
paraphrase and never dropped.  Everything here is used only when the unit / contract runs the ``BILI_V1`` craft
profile (``craft_profile.py``); a LEGACY series never reaches these helpers, so its prompts stay byte-identical.

Fields (all optional for LEGACY; under BILI_V1 every Chinese one needs its ``_en`` twin, ``EN_TWIN_MISSING``):

* ``prompt_spec.action.primary_action`` (zh)       -> ``action.business_en`` (or ``action.performance.business_en``)
* ``prompt_spec.action.listener_reaction`` (zh)    -> ``action.listener_reaction_en`` (str or {id/name: str})
* ``prompt_spec.action.lead_in_reaction`` (zh)     -> ``action.lead_in_reaction_en`` (str or {id/name: str}): what the
  next speaker visibly does in the first ~1.5 s of the unit, before the line (the owner's cheap reaction rule b)
* ``prompt_spec.action.performance.delivery`` (zh) -> ``action.performance.delivery_en``
* ``prompt_spec.props[]`` / ``non_character_entities[]`` ``description`` (zh) -> ``description_en``; a shot prop row
  may name who holds it: ``holder_id`` (or ``owner_id`` / ``held_by``) and ``hand`` (left | right | both).

Pure functions, stdlib only.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

try:
    from tools import craft_profile as _cp
except ModuleNotFoundError:  # pragma: no cover - flat tools/ on sys.path
    import craft_profile as _cp  # type: ignore

CJK = re.compile(r"[㐀-鿿]")
#: owner rule (b): the next speaker's reaction plays in the first 1-2 s of their own unit, before the line
LEAD_IN_SECONDS = 1.5
LEAD_IN_TEMPLATE = "For the first {seconds:g} seconds, before speaking, {label} {reaction}."
#: the instruction every EN_TWIN_MISSING finding carries back to the writer
TRANSLATE_RULE = ("translate literally; keep the object, the hand, the verb; no paraphrase into mood words")
HOLDER_KEYS = ("holder_id", "owner_id", "held_by", "holder")
#: action fields whose Chinese text is a template the preproduction builder wrote when the writer gave none
FALLBACK_FIELDS = ("motion_direction", "physical_causality", "microexpression_design", "physical_action_design",
                   "contact_point")


def active(payload: Any) -> bool:
    """True when a compiled unit / contract dict runs BILI_V1 (the grouped compiler stamps ``craft_profile``)."""
    try:
        return isinstance(payload, dict) and _cp.is_bili_v1(payload)
    except Exception:  # noqa: BLE001 - a prompt render never fails on the profile lookup
        return False


def english(value: Any, limit: int = 300) -> str:
    """One clean English sentence body ('' for empty or Chinese text)."""
    text = " ".join(str(value or "").split()).strip().rstrip(".;,")
    if not text or CJK.search(text):
        return ""
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;")


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text and not text[:2].isupper() else text


def _strip_label(text: str, label: str) -> str:
    return re.sub(rf"^{re.escape(label)}(?:'s)?\s+", "", text, flags=re.IGNORECASE) if label else text


def _per_subject(value: Any, subjects: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """[(label, english text)] of an authored ``*_en`` value for the given [(entity id, label)].

    A string goes to the only subject (or to every one when several are given); a dict is keyed by id or label."""
    if isinstance(value, dict):
        out = []
        for cid, label in subjects:
            text = english(value.get(cid) or value.get(label) or value.get(label.lower()))
            if text:
                out.append((label, text))
        return out
    text = english(value)
    if not text or not subjects:
        return []
    return [(label, text) for _, label in subjects]


# --------------------------------------------------------------------------- lead-in reaction (rule b)
def lead_in_sentences(action: Any, subjects: list[tuple[str, str]]) -> list[str]:
    """"For the first 1.5 seconds, before speaking, <label> <reaction>." for each authored lead-in reaction.

    ``subjects``: [(entity id, label)] who may carry it; a plain string belongs to the first (the beat's speaker)."""
    value = action.get("lead_in_reaction_en") if isinstance(action, dict) else None
    if not value:
        return []
    rows = _per_subject(value, subjects if isinstance(value, dict) else subjects[:1])
    out = []
    for label, text in rows:
        if text.lower().startswith("for the first"):
            out.append(text[:1].upper() + text[1:] + ".")
            continue
        out.append(LEAD_IN_TEMPLATE.format(seconds=LEAD_IN_SECONDS, label=label,
                                           reaction=_lower_first(_strip_label(text, label))))
    return out


# --------------------------------------------------------------------------- listener reaction (V1 renderer)
def listener_reaction_sentences(action: Any, listeners: list[tuple[str, str]]) -> list[str]:
    """The authored listener reaction for the visible listeners: "<Label>: <reaction>." (V2's own wording)."""
    value = action.get("listener_reaction_en") if isinstance(action, dict) else None
    if not value or not listeners:
        return []
    if not isinstance(value, dict) and len(listeners) > 1:
        text = english(value)
        return [f"{_join([label for _, label in listeners])}: {text}."] if text else []
    out = []
    for label, text in _per_subject(value, listeners):
        out.append(f"{text[:1].upper() + text[1:]}." if text.lower().startswith(label.lower())
                   else f"{label}: {text}.")
    return out


# --------------------------------------------------------------------------- micro-performance timeline (E27)
#: E28 2026-11-26 (device 1101, RELEASE_HELD:BURN_UNRESOLVED): the time-coded timeline ("1.8–2.4 s, Alpha: on the
#: stressed word at about 1.8 s: ... the word comes out ...") reads like a subtitle track -- H3 burned the spoken line
#: as large mid-frame text and as a second subtitle row in 12 of 31 speaking units (E27, same lines without the
#: timeline: none).  The performance is now rendered as an untimed face-and-body sequence: no seconds, no reference
#: to the line, its words, syllables or voice, no FACS codes (letters + digits); the voice belongs to "Delivery:".
_SPOKEN_CLAUSE = re.compile(r"\{trigger\}|\b(?:words?|lines?|syllables?|sentences?|speech|speak\w*|spoken|says?|said|"
                            r"talk\w*|voice[sd]?|stress(?:ed)?|trigger\w*|pronounc\w*|utter\w*|subtitles?|captions?)\b",
                            re.I)
_FACS = re.compile(r"\s*\((?:one-sided\s+)?AU\s*\d+[A-E]?(?:\s*\+\s*AU\s*\d+[A-E]?)*\)|\bAU\s*\d+[A-E]?\b", re.I)
_BEAT_PREFIX = re.compile(r"^(?:on \{trigger\}|during the line|end frame|carried over from the (?:last line|previous "
                          r"shot))\s*:\s*", re.I)


def silent_performance_text(text: str) -> str:
    """One beat's English with every clause that names the spoken line (its words, syllables, voice, the trigger
    word) dropped, FACS codes removed and time / trigger prefixes stripped: what the face and body do, only."""
    text = _FACS.sub("", " ".join(str(text or "").split()))
    while True:
        stripped = _BEAT_PREFIX.sub("", text)
        if stripped == text:
            break
        text = stripped
    clauses = [c.strip() for c in re.split(r"[;,]\s+", text) if c.strip()]
    kept = list(dict.fromkeys(re.sub(r"\s+with it$", "", c) for c in clauses if not _SPOKEN_CLAUSE.search(c)))
    return ", ".join(kept).strip().rstrip(".;,: ")


def performance_timeline_sentences(action: Any, who: str, listener: str = "",
                                   window: tuple[float, float] | None = None) -> list[str]:
    """The compiled micro-performance (``action.performance.timeline``, lines/nalu/runtime/tools/
    performance_timeline.py) as an untimed sequence of visible face / body states: entry -> change -> end frame.

    ``who``: the speaker's English label; ``listener``: the listener's label ("" -> "the other person");
    ``window`` is accepted for call compatibility and ignored (E28: no seconds in the performance).  [] when there
    is no timeline or the text is not English."""
    del window
    performance = action.get("performance") if isinstance(action, dict) else None
    timeline = performance.get("timeline") if isinstance(performance, dict) else None
    beats = timeline.get("beats") if isinstance(timeline, dict) else None
    if not who or not isinstance(beats, list) or not beats:
        return []
    other = listener or "the other person"
    out: list[str] = []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        raw = str(beat.get("en") or "").replace("{listener}", other).replace("{who}", who)
        text = silent_performance_text(raw)
        if not text or CJK.search(text):
            continue
        out.append(text)
    return out


def performance_timeline_line(action: Any, who: str, listener: str = "",
                              window: tuple[float, float] | None = None) -> str:
    """"<who>'s face and body, as visible changes ...: at first ...; then ...; at the end ..." ('' when none)."""
    rows = performance_timeline_sentences(action, who, listener, window)
    if not rows:
        return ""
    steps = ["at first", "then", "at the end"] if len(rows) == 3 else (["at first", "at the end"] if len(rows) == 2
                                                                        else ["throughout"])
    if len(rows) > 3:
        steps = ["at first"] + ["then"] * (len(rows) - 2) + ["at the end"]
    body = "; ".join(f"{step}, {row}" for step, row in zip(steps, rows))
    return f"{who}'s face and body change visibly, never a held pose: {body}."


# --------------------------------------------------------------------------- 脑补: what the viewer must see (E27)
#: all visual sentences of one beat together (the H3 boundary is 10 000 runes; a typical BILI unit renders ~4-6 k)
VISUAL_MAX_CHARS = 600
#: identity comes from the reference images (#342): appearance words are dropped from the visual sentences
_APPEARANCE = re.compile(r"\b(?:handsome|beautiful|pretty|gorgeous|cute|complexion|skin|jawline|cheekbones?|"
                         r"facial features|face shape|features|make-?up|freckles?|eye colou?r|hair colou?r|"
                         r"hairstyle|slender|delicate|youthful|aged|wrinkled|appearance|looks like)\b", re.I)
#: E28: never "while the line is spoken ... the first word ... the last" -- it points H3 at the words (burned text)
FOLDED_WHILE_SPEAKING = ("All of this action flows on without a pause from the first frame to the last; nothing "
                         "waits for a still moment.")


def _no_appearance(text: str) -> str:
    """Drop the clauses that re-describe a face or a look (the references own identity)."""
    clauses = [c for c in re.split(r"(?<=[;,])\s+", text) if c.strip()]
    kept = [c for c in clauses if not _APPEARANCE.search(c)]
    return " ".join(kept).strip().rstrip(".;,")


#: E28: a visual clause that refers to the spoken words or to writing (H3 renders it as text) is dropped; "line"
#: (a red line, a line of soldiers) and "speaking" (timing a gesture against the speech act) are kept here
_SPOKEN_VISUAL = re.compile(r"\b(?:words?|syllables?|sentences?|says?|said|spoken|subtitles?|captions?|lettering|written|"
                            r"inscri\w*|reads? aloud)\b", re.I)


def _not_spoken(text: str) -> str:
    clauses = [c for c in re.split(r"(?<=[;,])\s+", text) if c.strip()]
    return " ".join(c for c in clauses if not _SPOKEN_VISUAL.search(c)).strip().rstrip(".;,")


def visual_sentences(spec: Any, subjects: list[tuple[str, str]], *, speaking: bool = False,
                     skip: Iterable[str] = ()) -> list[tuple[str, str]]:
    """[(key, sentence)] from ``prompt_spec.visual`` (screenplay ``@see`` / ``（画面）``, the writer's English twins):
    the stakes made visible, the shot's concrete detail, each visible character's own business, the environment;
    plus, on a speaking beat that absorbed a silent step (``action.folded_silent``), that it plays during the line.

    ``subjects``: [(entity id, label)] in frame; ``skip``: keys already stated in this unit (the environment is
    said once).  Appearance clauses are dropped; the sentences stop at VISUAL_MAX_CHARS.  [] without the block."""
    spec = spec if isinstance(spec, dict) else {}
    visual = spec.get("visual") if isinstance(spec.get("visual"), dict) else {}
    action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
    skip = set(skip)
    rows: list[tuple[str, str]] = []
    stakes = _not_spoken(_no_appearance(english(visual.get("stakes_en"), 420)))
    if stakes:
        rows.append(("STAKES", f"In the frame: {stakes}."))  # E28: no "viewer must see" (burned text)
    detail = _not_spoken(_no_appearance(english(visual.get("detail_en"), 420)))
    if detail:
        rows.append(("DETAIL", f"Visible detail: {detail}."))
    if speaking and action.get("folded_silent"):
        rows.append(("FOLDED", FOLDED_WHILE_SPEAKING))
    business = visual.get("business_en")
    if isinstance(business, dict):
        for label, text in _per_subject(business, subjects):
            text = _not_spoken(_no_appearance(_strip_label(text, label)))
            if text:
                rows.append((f"BUSINESS.{label}", f"{label}'s own way of moving here: {_lower_first(text)}."))
    environment = _no_appearance(english(visual.get("environment_en"), 320))
    if environment:
        rows.append(("ENVIRONMENT", f"Around them: {_lower_first(environment)}."))
    out: list[tuple[str, str]] = []
    used = 0
    for key, sentence in rows:
        if key in skip or CJK.search(sentence):
            continue
        if used + len(sentence) > VISUAL_MAX_CHARS:
            continue
        out.append((key, sentence))
        used += len(sentence) + 1
    return out


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# --------------------------------------------------------------------------- props in hand (roster)
def _hand_words(hand: Any) -> str:
    value = str(hand or "").strip().lower()
    return {"left": "left hand", "l": "left hand", "right": "right hand", "r": "right hand",
            "both": "hands", "two": "hands", "both_hands": "hands"}.get(value, "hand")


def held_prop_sentences(unit: dict[str, Any], labels: dict[str, str]) -> list[str]:
    """"<Owner>'s <hand> holds <description_en>" for each declared prop of the unit that names its holder.

    ``labels``: entity id -> English label of the people in frame; a holder not in frame is skipped (H3 would invent
    the person).  One sentence per prop, first declaration wins."""
    out: list[str] = []
    seen: set[str] = set()
    for spec in unit.get("ordered_prompt_specs") or []:
        for prop in (spec.get("props") or []) if isinstance(spec, dict) else []:
            if not isinstance(prop, dict):
                continue
            key = str(prop.get("prop_id") or prop.get("prop") or "")
            holder = next((str(prop[k]) for k in HOLDER_KEYS if prop.get(k)), "")
            label = labels.get(holder, "")
            if not key or key in seen or not label:
                continue
            what = english(prop.get("description_en"), 160) or english(prop.get("english_name"), 60)
            if not what:
                continue
            seen.add(key)
            what = re.sub(r"^(?:a|an|the)\s+", "", what, flags=re.IGNORECASE)
            out.append(f"{label}'s {_hand_words(prop.get('hand'))} holds the {_lower_first(what)}")
    return out


# --------------------------------------------------------------------------- authored vs fallback
def field_source(action: Any, field: str) -> str:
    """"authored" | "fallback" | "" (unknown: a LEGACY editorial manifest never records it)."""
    sources = action.get("field_sources") if isinstance(action, dict) else None
    return str((sources or {}).get(field) or "") if isinstance(sources, dict) else ""


def authored(action: Any, field: str) -> bool:
    return field_source(action, field) == "authored"


def field_sources(source_action: dict[str, Any]) -> dict[str, str]:
    """For the editorial builder: which template-backed action fields the writer authored (BILI_V1 only)."""
    return {field: ("authored" if str(source_action.get(field) or "").strip() else "fallback")
            for field in FALLBACK_FIELDS}


# --------------------------------------------------------------------------- S1: EN_TWIN_MISSING
def _has_cjk(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_cjk(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_cjk(v) for v in value)
    return bool(CJK.search(str(value or "")))


def _is_english(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value) and all(_is_english(v) for v in value.values())
    return bool(english(value))


def _twin_rows(action: dict[str, Any], spec: dict[str, Any]) -> Iterable[tuple[Any, list[Any], str]]:
    performance = action.get("performance") if isinstance(action.get("performance"), dict) else {}
    spec_perf = spec.get("performance") if isinstance(spec.get("performance"), dict) else {}
    yield (action.get("primary_action"),
           [action.get("business_en"), performance.get("business_en"), spec_perf.get("business_en")], "business_en")
    yield action.get("listener_reaction"), [action.get("listener_reaction_en")], "listener_reaction_en"
    yield action.get("lead_in_reaction"), [action.get("lead_in_reaction_en")], "lead_in_reaction_en"
    yield (performance.get("delivery") or action.get("delivery") or spec_perf.get("delivery"),
           [performance.get("delivery_en"), action.get("delivery_en"), spec_perf.get("delivery_en")], "delivery_en")


def en_twin_failures(contract: dict[str, Any]) -> list[str]:
    """``EN_TWIN_MISSING:<shot or entity>:<field>`` for every Chinese field the H3 prompt needs whose English twin is
    missing or not English (BILI_V1, S1 integrity; the caller decides the profile)."""
    failures: list[str] = []
    for shot in contract.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        sid = str(shot.get("shot_id") or "?")
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
        for source, twins, field in _twin_rows(action, spec):
            if _has_cjk(source) and not any(_is_english(t) for t in twins if t):
                failures.append(f"EN_TWIN_MISSING:{sid}:{field}")
        for prop in spec.get("props") or []:
            if isinstance(prop, dict) and _has_cjk(prop.get("description")) and not _is_english(prop.get("description_en")):
                failures.append(f"EN_TWIN_MISSING:{sid}:props[{prop.get('prop_id') or prop.get('prop') or '?'}]"
                                ".description_en")
    for row in [*(contract.get("non_character_entities") or []),
                *((contract.get("props") or {}).get("reference_cards") or []
                  if isinstance(contract.get("props"), dict) else [])]:
        if isinstance(row, dict) and _has_cjk(row.get("description")) and not _is_english(row.get("description_en")):
            failures.append(f"EN_TWIN_MISSING:{row.get('entity_id') or '?'}:description_en")
    return list(dict.fromkeys(failures))


def en_twin_check(contract: dict[str, Any]) -> dict[str, Any]:
    """The structure-gate check row (failures block as S1 integrity; the writer gets ``TRANSLATE_RULE``)."""
    failures = en_twin_failures(contract)
    return {"failures": failures, "warnings": [], "unverified": [],
            "measurements": {"missing": len(failures), "rule": TRANSLATE_RULE} if failures else {"missing": 0}}


__all__ = [
    "active", "english", "lead_in_sentences", "listener_reaction_sentences", "held_prop_sentences",
    "field_source", "authored", "field_sources", "en_twin_failures", "en_twin_check", "LEAD_IN_SECONDS",
    "TRANSLATE_RULE", "FALLBACK_FIELDS", "performance_timeline_sentences", "performance_timeline_line",
    "visual_sentences", "VISUAL_MAX_CHARS", "FOLDED_WHILE_SPEAKING", "silent_performance_text",
]
