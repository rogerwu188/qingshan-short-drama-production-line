#!/usr/bin/env python3
"""S1 pre-generation gate: is the script/storyboard contract *structurally* a story?

Reads a ``qingshan.generation_contract.v3`` contract (plus the writer manifest
and an optional period lexicon) and answers the questions an audience asks in
the first minute: is there a hook, do people talk, do action beats end in an
outcome, do antagonists have a readable motive, do props have a source shot,
are new entities set up or paid off, and is the dialogue free of modern words.

Shot timeline = cumulative ``target_seconds`` in ``shots`` order.  Every check
returns ``{"failures": [...], "warnings": [...], "measurements": {...}}`` with
string failure codes; :func:`evaluate` merges them into one gate report.

Stdlib only.  Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional


SCHEMA = "qingshan.script_structure_contract_gate.v1"
LEXICON_SCHEMA = "qingshan.lexicon.v1"

HOOK_TYPES = ("dialogue", "shock", "question")
HOOK_WINDOW_SECONDS = 5.0
SHOCK_DIMENSIONS = {"MOMENTUM", "CONTACT"}

DIALOGUE_DENSITY_DEFAULTS = {
    "max_silent_run_seconds": 15.0,
    "max_silent_run_action_seconds": 25.0,
    "min_coverage": 0.35,
}
DEFAULT_DIALOGUE_CPS = 4.0

BEAT_TYPES = ("dialogue", "action", "transition", "reveal")
OUTCOME_KINDS = ("winner", "escape", "injury", "loss")
OUTCOME_EVIDENCE_GRACE_SECONDS = 10.0

MOTIVE_KINDS = ("line", "shot", "recap")
ANTAGONIST_TRIGGER_WORDS = ("伏击", "埋伏", "截")

PROP_RECAP_LEAD_SECONDS = 10.0

INTRO_SETUP_KINDS = ("line", "shot", "recap", "prior_episode")

_RANGE_SEPARATORS = ("至", "~", "-", "到", "—", "–")
_SHOT_ID_RE = re.compile(r"E\d+-S\d+-\d+")


# --------------------------------------------------------------------------- helpers


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(seconds: float) -> str:
    return str(int(seconds)) if float(seconds).is_integer() else f"{seconds:.1f}"


def _dedupe(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def spoken_text(dialogue: Any) -> str:
    """Strip the ``说话人：`` prefix and all punctuation/whitespace from a line."""
    text = _clean(dialogue)
    if not text:
        return ""
    for separator in ("：", ":"):
        head, sep, tail = text.partition(separator)
        if sep and len(head) <= 12:
            text = tail
            break
    return "".join(
        ch for ch in text
        if not unicodedata.category(ch).startswith(("P", "Z", "C"))
    )


def _spoken_chars(text: Any) -> int:
    return len([
        ch for ch in _clean(text)
        if not unicodedata.category(ch).startswith(("P", "Z", "C"))
    ])


def _voice_over_split(contract: dict[str, Any]) -> dict[int, tuple[str, int]]:
    """``shots`` index -> (in-video spoken text, V.O. spoken characters) for shots carrying V.O. narration.

    A VOICE_ONLY_NO_PLATE narrator's line is not bound to its shot: voice_over_narration.window_failures
    lets it run on over the following shots that carry no line.  Empty when the contract has no V.O.
    speaker or the split is off (legacy profile), so every other contract is measured as before.
    """
    try:
        from tools import voice_over_narration as _vo
    except ImportError:  # run as a script from tools/
        import voice_over_narration as _vo  # type: ignore
    entities = contract.get("character_entities") or []
    ids = _vo.voice_over_character_ids(entities)
    if not ids:
        return {}
    language = _vo.contract_language(contract)
    out: dict[int, tuple[str, int]] = {}
    for index, shot in enumerate(contract.get("shots") or []):
        if not isinstance(shot, dict):
            continue
        dialogue = _clean((shot.get("prompt_spec") or {}).get("dialogue"))
        in_video, rows = _vo.separate_voice_over(dialogue, entities, language, vo_ids=ids)
        if rows:
            out[index] = (spoken_text(in_video), sum(_spoken_chars(row.get("text")) for row in rows))
    return out


def _shot_prose(shot: dict[str, Any]) -> str:
    spec = shot.get("prompt_spec") or {}
    action = spec.get("action") or {}
    role = spec.get("role_semantic_disambiguation") or {}
    states = role.get("entity_states") or {}
    parts = [
        _clean(shot.get("blocking")),
        _clean(shot.get("entry_state")),
        _clean(shot.get("completion_state")),
        _clean(action.get("primary_action")),
    ]
    if isinstance(states, dict):
        parts.extend(_clean(v) for v in states.values())
    return " ".join(p for p in parts if p)


def build_timeline(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Cumulative shot timeline in ``shots`` order."""
    rows: list[dict[str, Any]] = []
    cursor = 0.0
    for index, shot in enumerate(contract.get("shots") or []):
        if not isinstance(shot, dict):
            continue
        seconds = max(_num(shot.get("target_seconds")), 0.0)
        spec = shot.get("prompt_spec") or {}
        dialogue = _clean(spec.get("dialogue"))
        cast_ids = [
            _clean(c.get("character_id"))
            for c in spec.get("cast") or []
            if isinstance(c, dict) and _clean(c.get("character_id"))
        ]
        prop_ids = [
            _clean(p.get("prop_id"))
            for p in spec.get("props") or []
            if isinstance(p, dict) and _clean(p.get("prop_id"))
        ]
        rows.append(
            {
                "index": index,
                "shot_id": _clean(shot.get("shot_id")) or f"SHOT-{index + 1}",
                "scene_id": _clean(shot.get("scene_id")),
                "start": cursor,
                "end": cursor + seconds,
                "seconds": seconds,
                "dialogue": dialogue,
                "spoken": spoken_text(dialogue),
                "dimensions": {
                    _clean(d).upper() for d in shot.get("state_delta_dimensions") or []
                },
                "cast_ids": cast_ids,
                "prop_ids": prop_ids,
                "prose": _shot_prose(shot),
            }
        )
        cursor += seconds
    return rows


def _by_id(timeline: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["shot_id"]: row for row in timeline}


def _expand_landed_at(value: Any, timeline: list[dict[str, Any]]) -> list[str]:
    """``"E04-S02-01 至 E04-S02-02"`` → every shot id in that inclusive range."""
    ids = _SHOT_ID_RE.findall(_clean(value))
    if not ids:
        return []
    order = {row["shot_id"]: row["index"] for row in timeline}
    if len(ids) == 1 or ids[0] not in order or ids[-1] not in order:
        return [i for i in ids if i in order]
    lo, hi = sorted((order[ids[0]], order[ids[-1]]))
    return [row["shot_id"] for row in timeline if lo <= row["index"] <= hi]


def beat_shot_ids(
    beat: dict[str, Any],
    manifest: Optional[dict[str, Any]],
    timeline: list[dict[str, Any]],
) -> list[str]:
    """Shots of a ``structure[]`` row: explicit ``shot_ids`` → ``beat_disposition``
    ``landed_at`` ranges of its ``source_events`` → every shot of its ``scene_id``."""
    explicit = [_clean(s) for s in beat.get("shot_ids") or [] if _clean(s)]
    if explicit:
        return explicit
    landed: list[str] = []
    events = {_clean(e) for e in beat.get("source_events") or []}
    if events and manifest:
        for row in manifest.get("beat_disposition") or []:
            if isinstance(row, dict) and _clean(row.get("event_id")) in events:
                for sid in _expand_landed_at(row.get("landed_at"), timeline):
                    if sid not in landed:
                        landed.append(sid)
    if landed:
        return landed
    scene = _clean(beat.get("scene_id"))
    return [row["shot_id"] for row in timeline if row["scene_id"] == scene]


def _dialogue_texts(contract: dict[str, Any], timeline: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(shot_id, text) for every dialogue unit and every shot dialogue string."""
    out: list[tuple[str, str]] = []
    audio = contract.get("audio_contract") or {}
    for unit in audio.get("dialogue_units") or []:
        if isinstance(unit, dict) and _clean(unit.get("text")):
            out.append((_clean(unit.get("shot_id")) or "UNIT", _clean(unit.get("text"))))
    for row in timeline:
        if row["dialogue"]:
            out.append((row["shot_id"], row["dialogue"]))
    return out


def _result(
    failures: Optional[list[str]] = None,
    warnings: Optional[list[str]] = None,
    measurements: Optional[dict[str, Any]] = None,
    unverified: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "failures": _dedupe(failures or []),
        "warnings": _dedupe(warnings or []),
        "measurements": measurements or {},
        "unverified": unverified or [],
    }


# --------------------------------------------------------------------------- A1 hook


def check_hook(contract: dict[str, Any], timeline: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    timeline = timeline if timeline is not None else build_timeline(contract)
    failures: list[str] = []
    first_dialogue = next((row["start"] for row in timeline if row["spoken"]), None)
    measurements: dict[str, Any] = {"first_dialogue_seconds": first_dialogue}
    hook = (contract.get("pacing") or {}).get("hook")
    if not isinstance(hook, dict):
        return _result(["HOOK_MISSING"], measurements=measurements)

    kind = _clean(hook.get("type")).lower()
    measurements["hook_type"] = kind
    if kind not in HOOK_TYPES:
        failures.append(f"HOOK_TYPE_INVALID:{kind or 'EMPTY'}")
        return _result(failures, measurements=measurements)
    if hook.get("at_seconds") is None:
        failures.append("HOOK_AT_SECONDS_MISSING")
        return _result(failures, measurements=measurements)
    at_seconds = _num(hook.get("at_seconds"), HOOK_WINDOW_SECONDS + 1)
    measurements["hook_at_seconds"] = at_seconds
    if at_seconds > HOOK_WINDOW_SECONDS:
        failures.append("HOOK_NOT_IN_FIRST_5S")
        return _result(failures, measurements=measurements)

    if kind == "dialogue":
        if not any(row["spoken"] and row["start"] <= at_seconds for row in timeline):
            failures.append("HOOK_NOT_IN_FIRST_5S")
    elif kind == "question":
        if not any(
            row["start"] <= at_seconds and ("？" in row["dialogue"] or "?" in row["dialogue"])
            for row in timeline
        ):
            failures.append("HOOK_NOT_IN_FIRST_5S")
    else:  # shock
        shot = _by_id(timeline).get(_clean(hook.get("line_or_shot_id")))
        if shot is None:
            failures.append("HOOK_SHOT_MISSING")
        else:
            if shot["start"] > at_seconds:
                failures.append("HOOK_NOT_IN_FIRST_5S")
            if not shot["dimensions"] & SHOCK_DIMENSIONS:
                failures.append("HOOK_SHOT_NOT_SHOCK")
    return _result(failures, measurements=measurements)


# --------------------------------------------------------------------------- A5 density


def check_dialogue_density(
    contract: dict[str, Any],
    manifest: Optional[dict[str, Any]] = None,
    timeline: Optional[list[dict[str, Any]]] = None,
    *,
    dialogue_cps: float = DEFAULT_DIALOGUE_CPS,
) -> dict[str, Any]:
    timeline = timeline if timeline is not None else build_timeline(contract)
    policy = dict(DIALOGUE_DENSITY_DEFAULTS)
    declared = (contract.get("pacing") or {}).get("dialogue_density")
    if isinstance(declared, dict):
        for key in DIALOGUE_DENSITY_DEFAULTS:
            if declared.get(key) is not None:
                policy[key] = _num(declared.get(key), policy[key])
    verdict = _clean(declared.get("verdict") if isinstance(declared, dict) else "").upper() or "FAIL"
    cps = dialogue_cps if dialogue_cps > 0 else DEFAULT_DIALOGUE_CPS

    action_shots: set[str] = set()
    if manifest:
        for beat in manifest.get("structure") or []:
            if isinstance(beat, dict) and _clean(beat.get("type")).lower() == "action":
                action_shots.update(beat_shot_ids(beat, manifest, timeline))

    total = sum(row["seconds"] for row in timeline)
    speech_total = 0.0
    per_shot: list[dict[str, Any]] = []
    silent_runs: list[dict[str, Any]] = []
    run_start: Optional[float] = None
    run_shots: list[str] = []

    def close_run(end: float) -> None:
        if run_start is None or end <= run_start:
            return
        in_action = bool(run_shots) and all(s in action_shots for s in run_shots)
        limit = policy["max_silent_run_action_seconds"] if in_action else policy["max_silent_run_seconds"]
        silent_runs.append(
            {
                "start": run_start,
                "end": end,
                "seconds": end - run_start,
                "shots": list(run_shots),
                "in_action_beat": in_action,
                "limit": limit,
            }
        )

    voice_over = _voice_over_split(contract)
    carry = 0.0  # V.O. seconds still to be heard after the shot that carries the line
    for row in timeline:
        if row["index"] in voice_over:
            in_video, vo_chars = voice_over[row["index"]]
            speech = min(len(in_video) / cps, row["seconds"])
            narration = vo_chars / cps
            heard = min(narration, row["seconds"] - speech)
            speech += heard
            carry = narration - heard
        elif row["spoken"]:
            speech = min(len(row["spoken"]) / cps, row["seconds"])
            carry = 0.0
        else:
            speech = min(carry, row["seconds"]) if carry > 1e-9 else 0.0
            carry -= speech
        speech_total += speech
        per_shot.append({"shot_id": row["shot_id"], "speech_seconds": round(speech, 2)})
        if speech > 0:
            close_run(row["start"])
            run_start, run_shots = None, []
        else:
            if run_start is None:
                run_start = row["start"]
            run_shots.append(row["shot_id"])
    if timeline:
        close_run(timeline[-1]["end"])

    coverage = (speech_total / total) if total > 0 else 0.0
    codes: list[str] = []
    for run in silent_runs:
        if run["seconds"] > run["limit"]:
            codes.append(f"DIALOGUE_STARVATION_SILENT_RUN:{_fmt(run['start'])}-{_fmt(run['end'])}")
    if coverage < policy["min_coverage"]:
        codes.append(f"DIALOGUE_STARVATION_COVERAGE:{coverage:.3f}")

    measurements = {
        "total_seconds": total,
        "speech_seconds_estimate": round(speech_total, 2),
        "coverage": round(coverage, 4),
        "dialogue_cps": cps,
        "policy": policy,
        "verdict": verdict,
        "first_dialogue_seconds": next((r["start"] for r in timeline if r["spoken"]), None),
        "silent_runs": silent_runs,
        "largest_silent_run_seconds": max((r["seconds"] for r in silent_runs), default=0.0),
        "per_shot_speech": per_shot,
    }
    if verdict == "WARN":
        return _result(warnings=codes, measurements=measurements)
    return _result(failures=codes, measurements=measurements)


# --------------------------------------------------------------------------- A2 action outcome


def check_action_outcome(
    contract: dict[str, Any],
    manifest: Optional[dict[str, Any]],
    timeline: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    timeline = timeline if timeline is not None else build_timeline(contract)
    if not manifest:
        return _result(unverified=["action_outcome: MANIFEST_NOT_PROVIDED"])
    rows = [r for r in manifest.get("structure") or [] if isinstance(r, dict)]
    if not rows:
        return _result(["BEAT_STRUCTURE_MISSING"])
    if not any("type" in r for r in rows):
        return _result(["BEAT_TYPE_UNDECLARED"], measurements={"beat_count": len(rows)})

    failures: list[str] = []
    shots = _by_id(timeline)
    action_beats: list[dict[str, Any]] = []
    for row in rows:
        beat_id = _clean(row.get("beat_id")) or _clean(row.get("scene_id")) or "BEAT"
        kind = _clean(row.get("type")).lower()
        if not kind:
            failures.append(f"BEAT_TYPE_MISSING:{beat_id}")
            continue
        if kind not in BEAT_TYPES:
            failures.append(f"BEAT_TYPE_INVALID:{beat_id}:{kind}")
            continue
        if kind != "action":
            continue
        ids = beat_shot_ids(row, manifest, timeline)
        beat_end = max((shots[s]["end"] for s in ids if s in shots), default=None)
        entry = {"beat_id": beat_id, "shot_ids": ids, "beat_end_seconds": beat_end}
        action_beats.append(entry)
        outcome = row.get("outcome")
        if not isinstance(outcome, dict) or _clean(outcome.get("kind")).lower() not in OUTCOME_KINDS:
            failures.append(f"ACTION_NO_OUTCOME:{beat_id}")
            continue
        evidence = shots.get(_clean(outcome.get("evidence_shot_id")))
        if evidence is None:
            failures.append(f"ACTION_OUTCOME_EVIDENCE_MISSING_SHOT:{beat_id}")
            continue
        entry["evidence_start_seconds"] = evidence["start"]
        if beat_end is None:
            failures.append(f"ACTION_BEAT_SHOTS_UNRESOLVED:{beat_id}")
        elif evidence["start"] > beat_end + OUTCOME_EVIDENCE_GRACE_SECONDS:
            failures.append(f"ACTION_OUTCOME_EVIDENCE_LATE:{beat_id}")
    return _result(failures, measurements={"beat_count": len(rows), "action_beats": action_beats})


def _episode_no(value: Any) -> Optional[int]:
    m = re.search(r"(\d+)", str(value or ""))
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- A3 antagonist motive


def check_antagonist_motive(
    contract: dict[str, Any], timeline: Optional[list[dict[str, Any]]] = None
) -> dict[str, Any]:
    timeline = timeline if timeline is not None else build_timeline(contract)
    shots = _by_id(timeline)
    groups = contract.get("antagonist_groups")
    declared_roles = any(
        _clean(c.get("role")).lower() == "antagonist"
        for c in contract.get("character_entities") or []
        if isinstance(c, dict)
    )
    trigger_shots = [
        row["shot_id"] for row in timeline if any(w in row["prose"] for w in ANTAGONIST_TRIGGER_WORDS)
    ]
    measurements = {"antagonist_role_declared": declared_roles, "trigger_shots": trigger_shots}
    if not isinstance(groups, list) or not groups:
        if declared_roles or trigger_shots:
            return _result(["ANTAGONIST_GROUPS_UNDECLARED"], measurements=measurements)
        return _result(measurements=measurements)

    failures: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        gid = _clean(group.get("group_id")) or "GROUP"
        first = shots.get(_clean(group.get("first_action_shot_id")))
        if first is None:
            failures.append(f"ANTAGONIST_FIRST_ACTION_SHOT_MISSING:{gid}")
            continue
        setup = group.get("motive_setup")
        if not isinstance(setup, dict) or _clean(setup.get("kind")).lower() not in MOTIVE_KINDS:
            failures.append(f"ANTAGONIST_NO_MOTIVE:{gid}")
            continue
        kind = _clean(setup.get("kind")).lower()
        ref = setup.get("ref")
        if kind == "recap":
            if not isinstance(ref, dict) or not _clean(ref.get("episode")) or not _clean(ref.get("shot_id")):
                failures.append(f"ANTAGONIST_NO_MOTIVE:{gid}")
                continue
            anchor = shots.get(_clean(ref.get("recap_shot_id")))
        else:
            anchor = shots.get(_clean(ref))
        # a recap of an EARLIER episode was set up before this episode began: the carry-in shot that opens on the
        # previous episode's end state may itself be the recap anchor (lab 化神 E03: E02's antagonist opens E03)
        carried_in = (kind == "recap" and _episode_no(ref.get("episode")) is not None
                      and _episode_no(contract.get("episode") or contract.get("episode_id")) is not None
                      and _episode_no(ref.get("episode")) < _episode_no(contract.get("episode") or contract.get("episode_id")))
        if anchor is None:
            failures.append(f"ANTAGONIST_NO_MOTIVE:{gid}")
        elif anchor["start"] > first["start"] or (anchor["start"] == first["start"] and not carried_in):
            failures.append(f"ANTAGONIST_MOTIVE_AFTER_ACTION:{gid}")
    return _result(failures, measurements=measurements)


# --------------------------------------------------------------------------- A4 prop source


def check_prop_source(
    contract: dict[str, Any], timeline: Optional[list[dict[str, Any]]] = None
) -> dict[str, Any]:
    timeline = timeline if timeline is not None else build_timeline(contract)
    shots = _by_id(timeline)
    episode = _clean(contract.get("episode")).upper()
    texts = _dialogue_texts(contract, timeline)
    cards = (contract.get("props") or {}).get("reference_cards") or []
    failures: list[str] = []
    checked: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        pid = _clean(card.get("entity_id")) or _clean(card.get("prop_id")) or _clean(card.get("name"))
        name = _clean(card.get("name"))
        payoff_ids = [_clean(s) for s in card.get("payoff_shot_ids") or [] if _clean(s)]
        named_in = [sid for sid, text in texts if name and name in text]
        if not payoff_ids and not named_in:
            continue
        first_payoff = min(
            (shots[s]["start"] for s in payoff_ids + named_in if s in shots), default=None
        )
        checked.append({"prop_id": pid, "payoff_shot_ids": payoff_ids, "named_in": named_in,
                        "first_payoff_seconds": first_payoff})
        acquired = card.get("acquired")
        if not isinstance(acquired, dict) or not _clean(acquired.get("episode")) or not _clean(acquired.get("shot_id")):
            failures.append(f"PROP_NO_SOURCE:{pid}")
            continue
        if _clean(acquired.get("episode")).upper() == episode:
            if _clean(acquired.get("shot_id")) not in shots:
                failures.append(f"PROP_SOURCE_SHOT_MISSING:{pid}")
            continue
        recap = shots.get(_clean(card.get("recap_shot_id")))
        if recap is None:
            failures.append(f"PROP_RECAP_MISSING:{pid}")
        elif first_payoff is not None and recap["start"] > first_payoff - PROP_RECAP_LEAD_SECONDS:
            failures.append(f"PROP_RECAP_MISSING:{pid}")
    return _result(failures, measurements={"props_checked": checked})


# --------------------------------------------------------------------------- B3′ entity introduction


def _carry_in_entity_ids(contract: dict[str, Any]) -> set[str]:
    carry = contract.get("carry_in") or {}
    ids: set[str] = set()
    for key in ("entities", "entity_ids", "carry_in_entities"):
        for item in carry.get(key) or []:
            if isinstance(item, dict):
                ids.add(_clean(item.get("entity_id")) or _clean(item.get("character_id")))
            else:
                ids.add(_clean(item))
    ids.discard("")
    return ids


def check_entity_introduction(
    contract: dict[str, Any], timeline: Optional[list[dict[str, Any]]] = None
) -> dict[str, Any]:
    timeline = timeline if timeline is not None else build_timeline(contract)
    shots = _by_id(timeline)
    intros: dict[str, dict[str, Any]] = {}
    for row in contract.get("entity_introductions") or []:
        if isinstance(row, dict) and _clean(row.get("entity_id")):
            intros[_clean(row.get("entity_id"))] = row

    def introduced(eid: str) -> bool:
        row = intros.get(eid)
        if row is None:
            return False
        setup = row.get("setup")
        if isinstance(setup, dict) and _clean(setup.get("kind")).lower() in INTRO_SETUP_KINDS and setup.get("ref"):
            return True
        return _clean(row.get("payoff_shot_id")) in shots

    carry_in = _carry_in_entity_ids(contract)
    characters = [c for c in contract.get("character_entities") or [] if isinstance(c, dict)]
    protagonists = {_clean(p) for p in contract.get("protagonist_ids") or [] if _clean(p)}
    if not protagonists and characters:
        protagonists = {_clean(characters[0].get("character_id"))}

    required: list[str] = []
    for row in contract.get("non_character_entities") or []:
        if not isinstance(row, dict):
            continue
        eid = _clean(row.get("entity_id"))
        first = shots.get(_clean(row.get("first_shot")))
        if not eid or first is None or eid in carry_in:
            continue
        if first["start"] > HOOK_WINDOW_SECONDS:
            required.append(eid)
    for row in characters:
        cid = _clean(row.get("character_id"))
        if cid and cid not in protagonists and cid not in carry_in:
            required.append(cid)

    failures = [f"ENTITY_NO_SETUP_OR_PAYOFF:{eid}" for eid in required if not introduced(eid)]
    return _result(
        failures,
        measurements={"protagonist_ids": sorted(protagonists), "required_entities": required,
                      "carry_in_entities": sorted(carry_in)},
    )


# --------------------------------------------------------------------------- A6 lexicon


def check_lexicon(
    contract: dict[str, Any],
    lexicon: Optional[dict[str, Any]],
    timeline: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    if not lexicon:
        return _result(unverified=["lexicon: NOT_PROVIDED"])
    if _clean(lexicon.get("schema")) != LEXICON_SCHEMA:
        return _result([f"LEXICON_SCHEMA_INVALID:{_clean(lexicon.get('schema')) or 'EMPTY'}"])
    timeline = timeline if timeline is not None else build_timeline(contract)
    texts = _dialogue_texts(contract, timeline)
    forbidden = [_clean(t) for t in lexicon.get("forbidden_terms") or [] if _clean(t)]
    variants: dict[str, str] = {}
    for canonical, spellings in (lexicon.get("canonical_names") or {}).items():
        for variant in spellings or []:
            if _clean(variant) and _clean(variant) != _clean(canonical):
                variants[_clean(variant)] = _clean(canonical)
    failures: list[str] = []
    for sid, text in texts:
        for term in forbidden:
            if term in text:
                failures.append(f"MODERN_LEXICON:{term}:{sid}")
        for variant in variants:
            if variant in text:
                failures.append(f"NAME_VARIANT:{variant}:{sid}")
    return _result(
        failures,
        measurements={"texts_scanned": len(texts), "forbidden_terms": len(forbidden),
                      "name_variants": len(variants)},
    )


# --------------------------------------------------------------------------- S1 integrity: schema / episode ids / source


#: the writer contract schema (agent_factory/claude_writer_v2/schemas); the CLI validates every contract against it
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "agent_factory" / "claude_writer_v2" / "schemas" / \
    "generation_contract.schema.json"
SCHEMA_ERROR_LIMIT = 12


def load_contract_schema(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    candidate = Path(path) if path else SCHEMA_PATH
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer())
    if kind == "null":
        return value is None
    return isinstance(value, {"object": dict, "array": list, "string": str, "boolean": bool}.get(kind, object))


def schema_errors(value: Any, schema: Any, path: str = "$", out: Optional[list[str]] = None) -> list[str]:
    """The JSON-Schema subset the writer contract schema uses (type, const, enum, pattern, minLength, minimum,
    maximum, exclusiveMinimum, required, properties, additionalProperties, items, minItems, oneOf, anyOf).
    Stdlib only: the fleet venv carries no jsonschema.  Keywords outside the subset are ignored."""
    out = [] if out is None else out
    if not isinstance(schema, dict):
        return out
    kind = schema.get("type")
    if kind and not any(_type_ok(value, k) for k in ([kind] if isinstance(kind, str) else kind)):
        out.append(f"{path}:TYPE_NOT_{kind if isinstance(kind, str) else '_'.join(kind)}")
        return out
    if "const" in schema and value != schema["const"]:
        out.append(f"{path}:CONST")
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}:ENUM:{str(value)[:40]}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{path}:PATTERN:{value[:40]}")
        if len(value) < int(schema.get("minLength") or 0):
            out.append(f"{path}:MIN_LENGTH")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{path}:MINIMUM")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{path}:MAXIMUM")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            out.append(f"{path}:EXCLUSIVE_MINIMUM")
    if isinstance(value, dict):
        for key in schema.get("required") or []:
            if key not in value:
                out.append(f"{path}:REQUIRED:{key}")
        props = schema.get("properties") or {}
        extra = schema.get("additionalProperties")
        for key, item in value.items():
            if key in props:
                schema_errors(item, props[key], f"{path}.{key}", out)
            elif isinstance(extra, dict):
                schema_errors(item, extra, f"{path}.{key}", out)
            elif extra is False:
                out.append(f"{path}:ADDITIONAL:{key}")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems") or 0):
            out.append(f"{path}:MIN_ITEMS")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                schema_errors(item, schema["items"], f"{path}[{index}]", out)
    if isinstance(schema.get("oneOf"), list):
        matched = sum(1 for branch in schema["oneOf"] if not schema_errors(value, branch, path, []))
        if matched != 1:
            out.append(f"{path}:ONE_OF:{matched}")
    if isinstance(schema.get("anyOf"), list):
        if not any(not schema_errors(value, branch, path, []) for branch in schema["anyOf"]):
            out.append(f"{path}:ANY_OF")
    return out


def check_schema(contract: dict[str, Any], schema: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The contract validates against generation_contract.schema.json (E24 2026-11-23: the schema existed but S1
    never applied it).  ``schema`` None = not requested (library callers); an unreadable schema file is UNVERIFIED,
    never a pass."""
    if schema is None:
        return _result(unverified=["schema: NOT_REQUESTED"])
    if not schema:
        return _result(unverified=["schema: UNREADABLE"])
    errors = schema_errors(contract, schema)
    return _result([f"SCHEMA_INVALID:{e}" for e in errors[:SCHEMA_ERROR_LIMIT]],
                   measurements={"schema_error_count": len(errors)})


_ANY_SHOT_ID_RE = re.compile(r"^(E\d+)-S\d+-\d+$")
#: subtrees whose shot ids are, by meaning, about OTHER episodes (the previous episode's end state, a recap source)
CARRY_IN_KEYS = frozenset({"carry_in", "carry_in_from", "previous_episode", "prior_episode", "arc_ledger",
                           "continuity_from_previous", "carry_in_entities"})
_CARRY_IN_MARKERS = ("carry_in", "carried_in", "is_carry_in", "cross_episode")


def _shot_id_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def check_episode_shot_ids(contract: dict[str, Any]) -> dict[str, Any]:
    """Every ``*shot_id`` / ``*shot_ids`` value belongs to THIS episode unless the row marks it as a carry-in.

    E24 (device 1101, 2026-11-23): ``internal_transition_authoring`` was copied from E18 (E18-S01-01 -> E18-S01-02),
    so the transition rows described another episode's shots.  A cross-episode reference is legitimate only when the
    row says so: the row carries ``episode: <that episode>`` (a recap / prop acquired earlier), a truthy
    ``carry_in`` / ``cross_episode`` marker, or it sits under a carry-in key (``carry_in``, ``arc_ledger`` ...)."""
    episode = _clean(contract.get("episode") or contract.get("episode_id")).upper()
    failures: list[str] = []
    checked = 0
    if not episode:
        return _result(unverified=["episode_shot_ids: EPISODE_UNDECLARED"])

    def walk(node: Any, path: str, carried: bool) -> None:
        nonlocal checked
        if isinstance(node, dict):
            row_episode = _clean(node.get("episode") or node.get("source_episode")).upper()
            row_carried = carried or any(node.get(k) is True for k in _CARRY_IN_MARKERS)
            for key, value in node.items():
                key_l = str(key).lower()
                if key_l in CARRY_IN_KEYS:
                    walk(value, f"{path}.{key}", True)
                    continue
                if key_l.endswith("shot_id") or key_l.endswith("shot_ids"):
                    for sid in _shot_id_values(value):
                        match = _ANY_SHOT_ID_RE.match(_clean(sid))
                        if not match:
                            continue
                        checked += 1
                        owner = match.group(1).upper()
                        if owner != episode and not row_carried and owner != row_episode:
                            failures.append(f"FOREIGN_EPISODE_SHOT_ID:{path}.{key}:{_clean(sid)}")
                    if isinstance(value, (dict, list)) and not _shot_id_values(value):
                        walk(value, f"{path}.{key}", row_carried)
                    continue
                walk(value, f"{path}.{key}", row_carried)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]", carried)

    walk(contract, "$", False)
    compact = [re.sub(r"\[\d+\]", "[]", f) for f in failures]
    return _result(_dedupe(compact)[:SCHEMA_ERROR_LIMIT],
                   measurements={"episode": episode, "shot_ids_checked": checked,
                                 "foreign_shot_ids": len(failures)})


_CHAPTER_FILE_RE = re.compile(r"ch(?:apter)?[_-]?0*(\d+)", re.IGNORECASE)


def _chapter_no(value: Any) -> Optional[int]:
    text = _clean(value)
    is_file = "/" in text or "." in text
    match = _CHAPTER_FILE_RE.search(Path(text).name if is_file else text)
    if match:
        return int(match.group(1))
    if is_file:  # a file without a chapter number in its name (a narrative, a whole-book file) binds no chapter
        return None
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits and len(digits) <= 5 else None


def check_source_binding(contract: dict[str, Any], craft_profile: Optional[str] = None) -> dict[str, Any]:
    """``source_binding.source_file`` (and every ``source_files[].path``) is one of ``source_binding.source_chapters``.

    E24: source_chapters 21-25 while source_file was ch0018.md -- the script was bound to a chapter it does not
    adapt, so every source check (key quotes, dialogue register, action beats) read the wrong text.

    BILI_V1 (CHANGE_SPEC WP1 item 10): ``adaptation_plan.source_chapters`` is authoritative -- the binding's
    chapters and files must lie inside it (E25 2026-11-23: the plan still named E24's chapters 21-25)."""
    if craft_profile == "BILI_V1":
        return _check_source_binding_bili_v1(contract)
    binding = contract.get("source_binding")
    if not isinstance(binding, dict):
        return _result(measurements={"declared": False})
    chapters = {_chapter_no(c) for c in binding.get("source_chapters") or []}
    chapters.discard(None)
    primary = _chapter_no(binding.get("primary_source_chapter")) if binding.get("primary_source_chapter") else None
    files = [_clean(binding.get("source_file"))] + [
        _clean(row.get("path")) if isinstance(row, dict) else _clean(row) for row in binding.get("source_files") or []]
    failures: list[str] = []
    if primary is not None and chapters and primary not in chapters:
        failures.append(f"SOURCE_PRIMARY_CHAPTER_NOT_IN_SOURCE_CHAPTERS:{primary}")
    for path in dict.fromkeys(f for f in files if f):
        number = _chapter_no(path)
        if number is None or not chapters:
            continue
        if number not in chapters:
            failures.append(f"SOURCE_FILE_NOT_IN_SOURCE_CHAPTERS:{Path(path).name}:{sorted(chapters)[:8]}")
    return _result(failures, measurements={"declared": True, "source_chapters": sorted(chapters),
                                           "files": [Path(f).name for f in files if f]})


def _check_source_binding_bili_v1(contract: dict[str, Any]) -> dict[str, Any]:
    plan = contract.get("adaptation_plan") if isinstance(contract.get("adaptation_plan"), dict) else {}
    plan_chapters = {_chapter_no(c) for c in plan.get("source_chapters") or []}
    plan_chapters.discard(None)
    if not plan_chapters:
        result = check_source_binding(contract)
        result["measurements"]["authority"] = "source_binding"
        return result
    binding = contract.get("source_binding") if isinstance(contract.get("source_binding"), dict) else {}
    bound = {_chapter_no(c) for c in binding.get("source_chapters") or []}
    bound.discard(None)
    files = [_clean(binding.get("source_file"))] + [
        _clean(row.get("path")) if isinstance(row, dict) else _clean(row) for row in binding.get("source_files") or []]
    files.append(_clean(contract.get("source_text")))
    failures: list[str] = []
    outside = sorted(c for c in bound if c not in plan_chapters)
    if outside:
        failures.append(f"SOURCE_BINDING_CHAPTERS_NOT_IN_ADAPTATION_PLAN:{outside[:8]}:{sorted(plan_chapters)[:8]}")
    for path in dict.fromkeys(f for f in files if f):
        number = _chapter_no(path)
        if number is not None and number not in plan_chapters:
            failures.append(f"SOURCE_FILE_NOT_IN_ADAPTATION_PLAN:{Path(path).name}:{sorted(plan_chapters)[:8]}")
    return _result(failures, measurements={"declared": True, "authority": "adaptation_plan",
                                           "source_chapters": sorted(plan_chapters),
                                           "files": [Path(f).name for f in files if f]})


# --------------------------------------------------------------------------- evaluate


def evaluate(
    contract: dict[str, Any],
    manifest: Optional[dict[str, Any]] = None,
    lexicon: Optional[dict[str, Any]] = None,
    *,
    dialogue_cps: float = DEFAULT_DIALOGUE_CPS,
    schema: Optional[dict[str, Any]] = None,
    craft_profile: Optional[str] = None,
) -> dict[str, Any]:
    """``schema``: the generation-contract JSON schema to validate against (the CLI always passes the repo schema;
    a library caller that passes none gets ``schema: NOT_REQUESTED`` in ``unverified``)."""
    timeline = build_timeline(contract)
    checks = {
        "hook": check_hook(contract, timeline),
        "dialogue_density": check_dialogue_density(contract, manifest, timeline, dialogue_cps=dialogue_cps),
        "action_outcome": check_action_outcome(contract, manifest, timeline),
        "antagonist_motive": check_antagonist_motive(contract, timeline),
        "prop_source": check_prop_source(contract, timeline),
        "entity_introduction": check_entity_introduction(contract, timeline),
        "lexicon": check_lexicon(contract, lexicon, timeline),
        # S1 integrity (E24 2026-11-23): never part of a taste loop -- a contract that fails these is not a script
        "schema": check_schema(contract, schema),
        "episode_shot_ids": check_episode_shot_ids(contract),
        "source_binding": check_source_binding(contract, craft_profile),
    }
    if _bili_v1(contract, craft_profile):
        # BILI_V1 (CHANGE_SPEC WP4 item 1): every Chinese field the H3 prompt needs has its literal English twin
        checks["en_twins"] = _en_twin_check(contract)
    failures: list[str] = []
    warnings: list[str] = []
    unverified: list[str] = []
    measurements: dict[str, Any] = {
        "episode": _clean(contract.get("episode")),
        "shot_count": len(timeline),
        "total_seconds": timeline[-1]["end"] if timeline else 0.0,
    }
    if not timeline:
        failures.append("SHOTS_MISSING")
    for name, result in checks.items():
        failures.extend(result["failures"])
        warnings.extend(result["warnings"])
        unverified.extend(result["unverified"])
        measurements[name] = result["measurements"]
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    return {
        "schema": SCHEMA,
        "status": status,
        "failures": _dedupe(failures),
        "warnings": _dedupe(warnings),
        "unverified": unverified,
        "measurements": measurements,
    }


def _bili_v1(contract: dict[str, Any], craft_profile: Optional[str]) -> bool:
    """BILI_V1 when the caller passes it (the pipeline resolves the series profile) or the contract declares it."""
    try:
        try:
            from tools import craft_profile as _cp
        except ModuleNotFoundError:
            import craft_profile as _cp  # type: ignore
        return _cp.is_bili_v1(craft_profile) if craft_profile else _cp.is_bili_v1(contract)
    except Exception:  # noqa: BLE001 - an unreadable profile is LEGACY
        return False


def _en_twin_check(contract: dict[str, Any]) -> dict[str, Any]:
    try:
        from tools import bili_carry as _bili
    except ModuleNotFoundError:
        import bili_carry as _bili  # type: ignore
    return _bili.en_twin_check(contract)


def _load(path: Optional[str]) -> Optional[dict[str, Any]]:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contract", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--lexicon")
    parser.add_argument("--dialogue-cps", type=float, default=DEFAULT_DIALOGUE_CPS)
    parser.add_argument("--schema", default=str(SCHEMA_PATH),
                        help="generation-contract JSON schema (default: the repo schema)")
    parser.add_argument("--no-schema", action="store_true", help="skip the schema validation")
    parser.add_argument("--craft-profile",
                        help="the series craft profile (LEGACY | BILI_V1; default: the contract's). BILI_V1: "
                             "EN twins required (WP4) and adaptation_plan.source_chapters is authoritative (WP1)")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    schema = None if args.no_schema else (load_contract_schema(Path(args.schema)) or {})
    # normalised BILI_V1 for WP1's exact check; any other explicit value (LEGACY) is passed through for WP4's
    # _bili_v1 so it still overrides the contract; no flag -> None (the contract decides)
    profile = ("BILI_V1" if str(args.craft_profile or "").strip().upper().replace("-", "_") == "BILI_V1"
               else (args.craft_profile or None))
    report = evaluate(_load(args.contract) or {}, _load(args.manifest), _load(args.lexicon),
                      dialogue_cps=args.dialogue_cps, schema=schema, craft_profile=profile)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
