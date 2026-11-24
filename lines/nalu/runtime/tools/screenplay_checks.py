#!/usr/bin/env python3
"""Anti-template checks v2 (BILI_V1; CHANGE_SPEC WP2): distinctness, periodicity and similarity instead of the
ever-growing phrase blacklists.

The blacklists (``performance_variety`` ``_GENERIC_GESTURE`` / ``_STOCK_*``, ``script_pacing_check``
``KNOWN_BOILERPLATE_PHRASES`` / ``placeholder_acting``) caught one wording at a time; the generator script simply
switched wording ("gesture variation 1..30", emotions rotating sad -> confident -> fearful -> surprised).  These
checks measure the SHAPE of templated writing instead:

1. ``SCENE_CARD_REPEATED:<field>:<a>,<b>`` -- two scenes' goal / obstacle / turn (``pacing.scene_plan`` objective /
   conflict / physical_action) are the same after masking names and scene numbers (char-trigram Jaccard >= 0.6);
2. ``ACTION_LINES_THIN:<scene>`` -- fewer than 1 action line per 3 dialogue lines in a scene (screenplay only, taste);
3. ``NO_TOUCH_IN_TWO_PERSON_SCENE:<scene>`` -- a scene with >= 2 characters has no action line with a contact /
   handover verb naming both people (screenplay only, taste);
4. ``PROP_UNDECLARED:<noun>`` / ``PROP_UNUSED:<id>`` -- a prop noun in an action line nobody declared, a declared
   prop no action line uses (screenplay only, advisory);
5. ``EMOTION_PERIODIC:<period>:<score>`` -- the per-line emotion sequence repeats with period 3-6 (autocorrelation
   >= 0.8, or one 3-6 word cycle covering >= 60 % of the lines -- E11's cycle with an occasional extra word);
6. ``ACTION_TEXT_TEMPLATE:<a>,<b>`` -- two shots' authored primary_action are >= 0.6 similar with names and the line
   text masked (the "<Name> grabs the prop ... in response to the exact line: <line>" family);
7. ``GENERATOR_SCRIPT_PRESENT:<file>`` -- ``build_<ep>_layers.py`` exists for a SCREENPLAY_V1 episode (the writer
   must not script the content; raised by the pipeline, which knows the file system).

Severity: INTEGRITY for 1, 5, 6, 7 under ``writer_format: SCREENPLAY_V1`` (never admitted inside the taste loop;
the S1 integrity loop is bounded and then admits + records, owner rule "never stall the line"); the same codes are
TASTE (the pacing revise loop) for a BILI_V1 contract written as CONTRACT_JSON.  LEGACY: nothing runs -- the
caller (``script_pacing_check.evaluate``) only calls ``evaluate`` when ``active(contract)``.

Pure functions over the contract (the compiler's ``screenplay_v1`` block carries the screenplay lines).
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
LEXICON_PATH = _HERE.parent / "configs" / "SCREENPLAY_LEXICON_V1.json"
SCHEMA = "nalu.screenplay_checks.v1"
SIMILAR = 0.6
PERIODIC = 0.8
CYCLE_COVER = 0.6
MIN_EMOTIONS = 9
MAX_PAIRS = 4
INTEGRITY_CODES = frozenset({"SCENE_CARD_REPEATED", "EMOTION_PERIODIC", "ACTION_TEXT_TEMPLATE",
                             "GENERATOR_SCRIPT_PRESENT"})
FIXES = {
    "SCENE_CARD_REPEATED": "every scene card is its own: a different goal (what THIS person wants from THAT person "
                           "here), a different obstacle and a different turn -- if two scenes really want the same "
                           "thing, merge them",
    "ACTION_LINES_THIN": "write at least one action line per three dialogue lines: who, which hand, what object, "
                         "what changes (\"白桃停下令牌，嗒地磕在扶手上\")",
    "NO_TOUCH_IN_TWO_PERSON_SCENE": "give every scene with two or more people one touch or handover that names both "
                                    "(grab a sleeve, press a hand down, hand over the token, pat the back of a hand)",
    "PROP_UNDECLARED": "declare the prop (CAST_PROPS props or {道具 名 @人.手}) with its owner and hand",
    "PROP_UNUSED": "use the declared prop in an action line, or drop it",
    "EMOTION_PERIODIC": "the emotions cycle (the same 3-6 word sequence over and over): emotions come from the line "
                        "and the scene -- write the parenthetical of each line from what THIS person wants right "
                        "now; never assign emotions by rotation or script",
    "ACTION_TEXT_TEMPLATE": "two shots carry the same action sentence with the names / line swapped: write each "
                            "action from that moment (which hand, what object, what changes) -- never a template",
    "GENERATOR_SCRIPT_PRESENT": "SCREENPLAY_V1: delete the build_<ep>_layers.py generator; write OUTLINE + SCREENPLAY "
                                "+ CAST_PROPS by hand and run screenplay_compile.py",
}


def _clean(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


_LEX: dict[str, Any] | None = None


def lexicon() -> dict[str, Any]:
    global _LEX
    if _LEX is None:
        try:
            _LEX = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _LEX = {}
    return _LEX


def _profile():
    try:
        from tools import craft_profile as _cp  # noqa: PLC0415
    except ModuleNotFoundError:  # pragma: no cover - runtime tools dir only
        import craft_profile as _cp  # noqa: PLC0415
    return _cp


def active(contract: Any) -> bool:
    """BILI_V1 declared by the contract itself (the compiler stamps it; a hand-written BILI_V1 contract too)."""
    try:
        return isinstance(contract, dict) and _profile().is_bili_v1(contract)
    except Exception:  # noqa: BLE001
        return False


def screenplay(contract: Any) -> bool:
    try:
        return isinstance(contract, dict) and _profile().writer_format(contract) == "SCREENPLAY_V1"
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- text helpers
def names(contract: dict[str, Any]) -> list[str]:
    out: set[str] = set()
    for row in contract.get("character_entities") or []:
        if isinstance(row, dict):
            for key in ("canonical_name", "english_name", "name_en", "character_id"):
                out.add(_clean(row.get(key)))
            out |= {_clean(a) for a in row.get("aliases") or []}
            name = _clean(row.get("canonical_name"))
            if len(name) >= 3:
                out.add(name[:2])  # 白桃帝姬 -> 白桃 (the screenplay's short form)
    for row in (contract.get("screenplay_v1") or {}).get("scenes") or []:
        for line in row.get("lines") or []:
            out.add(_clean(line.get("speaker")))
    return sorted((n for n in out if len(n) >= 2), key=len, reverse=True)


def mask(text: Any, name_list: list[str], extra: list[str] | None = None) -> str:
    value = _clean(text)
    for item in sorted([e for e in extra or [] if _clean(e)], key=len, reverse=True):
        value = value.replace(_clean(item), " <L> ")
    for name in name_list:
        value = value.replace(name, "<N>")
    value = re.sub(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*", "<N>", value)
    value = re.sub(r"\bS\d+\b|\d+", "#", value)
    value = re.sub(r"[\s\W_]+", " ", value.lower(), flags=re.UNICODE)
    return value.strip()


def trigrams(text: str) -> set[str]:
    compact = text.replace(" ", "")
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[i:i + 3] for i in range(len(compact) - 2)}


def similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    if a.replace(" ", "") == b.replace(" ", ""):
        return 1.0
    return len(ta & tb) / len(ta | tb)


# --------------------------------------------------------------------------- 1. scene cards
CARD_FIELDS = (("goal", "objective"), ("obstacle", "conflict"), ("turn", "physical_action"))


def _plan(contract: dict[str, Any]) -> list[dict[str, Any]]:
    pacing = contract.get("pacing") if isinstance(contract.get("pacing"), dict) else {}
    rows = pacing.get("scene_plan") or contract.get("pacing_scene_plan") or []
    return [r for r in rows if isinstance(r, dict)]


def scene_card_repeats(contract: dict[str, Any]) -> list[str]:
    rows = _plan(contract)
    found: list[str] = []
    name_list = names(contract)
    for label, key in CARD_FIELDS:
        texts = [(_clean(r.get("scene_id")), mask(r.get(key), name_list)) for r in rows]
        texts = [(sid, t) for sid, t in texts if t]
        pairs = [(texts[i][0], texts[j][0]) for i in range(len(texts)) for j in range(i + 1, len(texts))
                 if similarity(texts[i][1], texts[j][1]) >= SIMILAR]
        found += [f"SCENE_CARD_REPEATED:{label}:{a},{b}" for a, b in pairs[:2]]
        if len(pairs) > 2:
            found.append(f"SCENE_CARD_REPEATED:{label}:pairs={len(pairs)}")
    return found


# --------------------------------------------------------------------------- 5. emotion periodicity
def _emotion_sequence(contract: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for shot in contract.get("shots") or []:
        spec = shot.get("prompt_spec") if isinstance(shot, dict) and isinstance(shot.get("prompt_spec"), dict) else {}
        if not _clean(spec.get("dialogue")):
            continue
        action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
        perf = action.get("performance") if isinstance(action.get("performance"), dict) else {}
        emotion = _clean(perf.get("emotion")).lower()
        if emotion:
            out.append(emotion)
    return out


def periodicity(seq: list[str]) -> tuple[int, float, str]:
    """(period, score, basis): the best of the lag-p autocorrelation (p = 3..6) and the coverage of one repeated
    3-6 word cycle (>= 3 distinct words, >= 3 non-overlapping occurrences)."""
    n = len(seq)
    best = (0, 0.0, "")
    if n < MIN_EMOTIONS or len(set(seq)) < 3:
        return best
    for p in range(3, 7):
        if n - p < p + 2:
            continue
        window = seq[:]
        score = sum(window[i] == window[i + p] for i in range(n - p)) / (n - p)
        if len(set(seq[:p])) >= 3 and score > best[1]:
            best = (p, round(score, 3), "autocorrelation")
    for k in range(3, 7):
        for start in range(0, n - k + 1):
            gram = seq[start:start + k]
            if len(set(gram)) < 3:
                continue
            i, hits = 0, 0
            while i <= n - k:
                if seq[i:i + k] == gram:
                    hits += 1
                    i += k
                else:
                    i += 1
            if hits >= 3:
                cover = round(hits * k / n, 3)
                if cover >= CYCLE_COVER and cover > best[1] and (best[2] != "autocorrelation" or best[1] < PERIODIC):
                    best = (k, cover, "cycle")
    return best


def emotion_periodic(contract: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    seq = _emotion_sequence(contract)
    period, score, basis = periodicity(seq)
    hit = (basis == "autocorrelation" and score >= PERIODIC) or (basis == "cycle" and score >= CYCLE_COVER)
    return ([f"EMOTION_PERIODIC:{period}:{score:.2f}"] if hit else []), \
        {"emotions": len(seq), "period": period, "score": score, "basis": basis or None}


# --------------------------------------------------------------------------- 6. action-text similarity
def action_templates(contract: dict[str, Any]) -> list[str]:
    name_list = names(contract)
    rows: list[tuple[str, str]] = []
    for shot in contract.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
        if _clean(action.get("source")).lower() == "fallback":
            continue  # the compiler's own last-resort text is not authored (WP7 reports its share)
        text = _clean(action.get("primary_action"))
        if not text:
            continue
        line = _clean(spec.get("dialogue"))
        spoken = line.split("：", 1)[-1] if line else ""
        normalised = mask(text, name_list, [spoken, line] if spoken else [])
        if len(normalised.replace(" ", "")) >= 8:
            rows.append((_clean(shot.get("shot_id")), normalised))
    pairs: list[str] = []
    total = 0
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if similarity(rows[i][1], rows[j][1]) >= SIMILAR:
                total += 1
                if len(pairs) < MAX_PAIRS:
                    pairs.append(f"ACTION_TEXT_TEMPLATE:{rows[i][0]},{rows[j][0]}")
    if total > len(pairs):
        pairs.append(f"ACTION_TEXT_TEMPLATE:pairs={total}")
    return pairs


# --------------------------------------------------------------------------- 2-4. screenplay detail checks
def _scenes(contract: dict[str, Any]) -> list[dict[str, Any]]:
    block = contract.get("screenplay_v1") if isinstance(contract.get("screenplay_v1"), dict) else {}
    return [s for s in block.get("scenes") or [] if isinstance(s, dict)]


def _contact_verb(text: str) -> bool:
    return any(v in (text or "") for v in lexicon().get("contact_verbs_zh") or []) or bool(
        re.search(r"\b(?:" + "|".join(lexicon().get("contact_verbs_en") or ["grab"]) + r")\w*\b", text or "", re.I))


def detail_checks(contract: dict[str, Any]) -> tuple[list[str], list[str], dict[str, Any]]:
    """(taste, advisory, metrics) for the screenplay block."""
    taste: list[str] = []
    advisory: list[str] = []
    touches: dict[str, int] = {}
    props_per_scene: dict[str, int] = {}
    block = contract.get("screenplay_v1") if isinstance(contract.get("screenplay_v1"), dict) else {}
    declared = [p for p in block.get("props") or [] if isinstance(p, dict)]
    prop_names = {_clean(p.get("name")) for p in declared}
    for row in ((contract.get("props") or {}).get("reference_cards") or []) if isinstance(contract.get("props"),
                                                                                          dict) else []:
        if isinstance(row, dict):
            prop_names.add(_clean(row.get("name")))
            prop_names |= {_clean(a) for a in row.get("aliases") or []}
    for p in declared:
        prop_names |= {_clean(a) for a in p.get("aliases") or []}
    prop_names.discard("")
    used: set[str] = set()
    undeclared: set[str] = set()
    for scene in _scenes(contract):
        sid = _clean(scene.get("scene_id"))
        lines = [ln for ln in scene.get("lines") or [] if isinstance(ln, dict)]
        actions = [ln for ln in lines if ln.get("kind") == "action"]
        dialogue = [ln for ln in lines if ln.get("kind") == "dialogue"]
        if dialogue and len(actions) * 3 < len(dialogue):
            taste.append(f"ACTION_LINES_THIN:{sid}:{len(actions)}/{len(dialogue)}")
        present = [c for c in scene.get("present") or [] if c]
        n_touch = 0
        for ln in actions:
            people = set(ln.get("named") or []) | ({ln.get("subject")} if ln.get("subject") else set())
            if _contact_verb(ln.get("text") or "") and len(people) >= 2:
                n_touch += 1
        touches[sid] = n_touch
        if len(present) >= 2 and n_touch == 0:
            taste.append(f"NO_TOUCH_IN_TWO_PERSON_SCENE:{sid}")
        scene_props = set()
        for ln in actions + [ln for ln in lines if ln.get("kind") == "reaction"]:
            text = ln.get("text") or ""
            for name in prop_names:
                if name and name in text:
                    used.add(name)
                    scene_props.add(name)
            for noun in lexicon().get("prop_nouns_zh") or []:
                if noun in text and not any(noun in n or n in noun for n in prop_names):
                    undeclared.add(noun)
        props_per_scene[sid] = len(scene_props)
    advisory += [f"PROP_UNDECLARED:{n}" for n in sorted(undeclared)]
    for p in declared:
        aliases = {_clean(p.get("name"))} | {_clean(a) for a in p.get("aliases") or []}
        if not (aliases & used):
            advisory.append(f"PROP_UNUSED:{_clean(p.get('id'))}")
    return taste, advisory, {"touches_per_scene": touches, "props_per_scene": props_per_scene,
                             "action_fallback_share": fallback_share(contract)}


def fallback_share(contract: dict[str, Any]) -> float | None:
    rows = [((s.get("prompt_spec") or {}).get("action") or {}) for s in contract.get("shots") or []
            if isinstance(s, dict)]
    marked = [r for r in rows if isinstance(r, dict) and r.get("source")]
    if not marked:
        return None
    return round(sum(1 for r in marked if _clean(r.get("source")).lower() == "fallback") / len(marked), 3)


# --------------------------------------------------------------------------- 7. generator script
def generator_scripts(episode: str, tools_dir: Path | None = None) -> list[str]:
    folder = Path(tools_dir) if tools_dir else _HERE
    candidate = folder / f"build_{_clean(episode).lower()}_layers.py"
    return [str(candidate)] if _clean(episode) and candidate.is_file() else []


# --------------------------------------------------------------------------- entry point
def evaluate(contract: dict[str, Any], *, generator_files: list[str] | None = None) -> dict[str, Any]:
    """{integrity, taste, advisory, fixes, metrics} for a BILI_V1 contract (empty lists when not active)."""
    if not active(contract):
        return {"schema": SCHEMA, "active": False, "integrity": [], "taste": [], "advisory": [], "fixes": {},
                "metrics": {}}
    sp = screenplay(contract)
    shape = scene_card_repeats(contract)
    periodic, emotion_metrics = emotion_periodic(contract)
    shape += periodic + action_templates(contract)
    shape += [f"GENERATOR_SCRIPT_PRESENT:{Path(f).name}" for f in generator_files or []] if sp else []
    taste: list[str] = []
    advisory: list[str] = []
    metrics: dict[str, Any] = {"emotion": emotion_metrics, "writer_format": "SCREENPLAY_V1" if sp else
                               "CONTRACT_JSON"}
    if sp:
        t, a, m = detail_checks(contract)
        taste += t
        advisory += a
        metrics.update(m)
    integrity = shape if sp else []
    if not sp:
        taste = shape + taste
    codes = {c.split(":", 1)[0] for c in integrity + taste + advisory}
    return {"schema": SCHEMA, "active": True, "integrity": integrity, "taste": taste, "advisory": advisory,
            "fixes": {c: FIXES[c] for c in sorted(codes) if c in FIXES}, "metrics": metrics}


__all__ = ["active", "screenplay", "evaluate", "scene_card_repeats", "emotion_periodic", "periodicity",
           "action_templates", "detail_checks", "generator_scripts", "similarity", "mask", "fallback_share",
           "INTEGRITY_CODES", "FIXES"]
