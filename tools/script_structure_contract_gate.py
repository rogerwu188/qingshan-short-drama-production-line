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

    for row in timeline:
        speech = min(len(row["spoken"]) / cps, row["seconds"]) if row["spoken"] else 0.0
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
        if anchor is None:
            failures.append(f"ANTAGONIST_NO_MOTIVE:{gid}")
        elif anchor["start"] >= first["start"]:
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


# --------------------------------------------------------------------------- evaluate


def evaluate(
    contract: dict[str, Any],
    manifest: Optional[dict[str, Any]] = None,
    lexicon: Optional[dict[str, Any]] = None,
    *,
    dialogue_cps: float = DEFAULT_DIALOGUE_CPS,
) -> dict[str, Any]:
    timeline = build_timeline(contract)
    checks = {
        "hook": check_hook(contract, timeline),
        "dialogue_density": check_dialogue_density(contract, manifest, timeline, dialogue_cps=dialogue_cps),
        "action_outcome": check_action_outcome(contract, manifest, timeline),
        "antagonist_motive": check_antagonist_motive(contract, timeline),
        "prop_source": check_prop_source(contract, timeline),
        "entity_introduction": check_entity_introduction(contract, timeline),
        "lexicon": check_lexicon(contract, lexicon, timeline),
    }
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
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    report = evaluate(_load(args.contract) or {}, _load(args.manifest), _load(args.lexicon),
                      dialogue_cps=args.dialogue_cps)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
