#!/usr/bin/env python3
"""S1 pre-generation gate: is the contract's *continuity state* declared and consistent?

Reads a ``qingshan.generation_contract.v3`` contract and checks the things an
audience reads as continuity errors: a character who is dead and then alive
(B1), a group whose head-count changes without a note (B1), a creature that is
biped in one shot and quadruped in another (B2), an ambush where the person
being ambushed enters the hideout before the reveal (B4), and costume state
that silently changes across an INT/EXT scene change (B5, warning only).

Every check returns ``{"failures", "warnings", "measurements"}``;
:func:`evaluate` merges them.  Stdlib only.  Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional


SCHEMA = "qingshan.continuity_state_contract_gate.v1"

LIFE_STATES = ("alive", "injured", "unconscious", "dead")

CREATURE_KIND = "CREATURE"
CREATURE_ID_HINTS = ("PROP-MUTANT",)
CREATURE_ID_SUBSTRINGS = ("BEAST",)
LOCOMOTION_KINDS = ("biped", "quadruped")
LOCOMOTION_WORDS = {
    "biped": ("直立", "站立奔", "两足"),
    "quadruped": ("四足", "四肢着地", "匍匐"),
}

AMBUSH_TRIGGER_WORDS = ("伏击", "埋伏", "雪窟窿", "藏身")
ENTER_VERBS = ("钻进", "没入", "爬进", "进入", "跳进", "扑进", "钻入", "爬入")

COSTUME_TRIGGER_WORDS = ("帽", "摘")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _dedupe(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _result(
    failures: Optional[list[str]] = None,
    warnings: Optional[list[str]] = None,
    measurements: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "failures": _dedupe(failures or []),
        "warnings": _dedupe(warnings or []),
        "measurements": measurements or {},
    }


def _shots(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in contract.get("shots") or [] if isinstance(s, dict)]


def _shot_id(shot: dict[str, Any], index: int) -> str:
    return _clean(shot.get("shot_id")) or f"SHOT-{index + 1}"


def _spec(shot: dict[str, Any]) -> dict[str, Any]:
    spec = shot.get("prompt_spec")
    return spec if isinstance(spec, dict) else {}


def _cast_ids(shot: dict[str, Any]) -> list[str]:
    return [
        _clean(c.get("character_id"))
        for c in _spec(shot).get("cast") or []
        if isinstance(c, dict) and _clean(c.get("character_id"))
    ]


def _entity_states(shot: dict[str, Any]) -> dict[str, str]:
    role = _spec(shot).get("role_semantic_disambiguation") or {}
    states = role.get("entity_states") if isinstance(role, dict) else None
    return {str(k): _clean(v) for k, v in states.items()} if isinstance(states, dict) else {}


def _action_text(shot: dict[str, Any]) -> str:
    action = _spec(shot).get("action") or {}
    return " ".join(p for p in (_clean(shot.get("blocking")), _clean(action.get("primary_action"))) if p)


def _full_text(shot: dict[str, Any]) -> str:
    return " ".join(
        p for p in (
            _action_text(shot),
            _clean(shot.get("entry_state")),
            _clean(shot.get("completion_state")),
            *_entity_states(shot).values(),
        ) if p
    )


# --------------------------------------------------------------------------- B1 life state / group count


def check_life_state(contract: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    last_state: dict[str, str] = {}
    last_count: dict[str, int] = {}
    declared_rows = 0
    undeclared_rows = 0
    for index, shot in enumerate(_shots(contract)):
        sid = _shot_id(shot, index)
        for cast in _spec(shot).get("cast") or []:
            if not isinstance(cast, dict):
                continue
            cid = _clean(cast.get("character_id")) or _clean(cast.get("character")) or "UNKNOWN"
            state = _clean(cast.get("life_state")).lower()
            if not state:
                undeclared_rows += 1
                failures.append(f"LIFE_STATE_UNDECLARED:{sid}:{cid}")
                continue
            if state not in LIFE_STATES:
                failures.append(f"LIFE_STATE_INVALID:{sid}:{cid}:{state}")
                continue
            declared_rows += 1
            if last_state.get(cid) == "dead" and state != "dead":
                failures.append(f"DEAD_THEN_ALIVE:{cid}:{sid}")
            last_state[cid] = state

        counts = shot.get("group_counts")
        if isinstance(counts, dict):
            for gid, entry in counts.items():
                gid = _clean(gid)
                if isinstance(entry, dict):
                    count, note = entry.get("count"), _clean(entry.get("count_change_note"))
                else:
                    count, note = entry, ""
                if not isinstance(count, int) or isinstance(count, bool):
                    failures.append(f"GROUP_COUNT_INVALID:{gid}:{sid}")
                    continue
                if gid in last_count and last_count[gid] != count and not note:
                    failures.append(f"GROUP_COUNT_DRIFT:{gid}:{sid}")
                last_count[gid] = count
    return _result(
        failures,
        measurements={
            "cast_rows_declared": declared_rows,
            "cast_rows_undeclared": undeclared_rows,
            "final_life_state": last_state,
            "final_group_counts": last_count,
        },
    )


# --------------------------------------------------------------------------- B2 creature card


def _is_creature(row: dict[str, Any]) -> tuple[bool, bool]:
    """(is_creature, kind_inferred_from_id)."""
    eid = _clean(row.get("entity_id")).upper()
    kind = _clean(row.get("kind")).upper()
    if kind:
        return kind == CREATURE_KIND, False
    inferred = eid.startswith(CREATURE_ID_HINTS) or any(s in eid for s in CREATURE_ID_SUBSTRINGS)
    return inferred, inferred


def check_creature_card(contract: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    creatures: list[dict[str, Any]] = []
    shots = _shots(contract)
    for row in contract.get("non_character_entities") or []:
        if not isinstance(row, dict):
            continue
        is_creature, inferred = _is_creature(row)
        if not is_creature:
            continue
        eid = _clean(row.get("entity_id"))
        entry: dict[str, Any] = {"entity_id": eid, "kind_inferred": inferred}
        creatures.append(entry)
        if inferred:
            failures.append(f"CREATURE_KIND_UNDECLARED:{eid}")
        card = row.get("creature_card")
        locomotion = _clean(card.get("locomotion")).lower() if isinstance(card, dict) else ""
        if not isinstance(card, dict) or not locomotion:
            failures.append(f"CREATURE_CARD_MISSING:{eid}")
            continue
        if locomotion not in LOCOMOTION_KINDS:
            failures.append(f"CREATURE_CARD_INVALID:{eid}:{locomotion}")
            continue
        for field in ("eye_color", "silhouette_ref"):
            if not _clean(card.get(field)):
                failures.append(f"CREATURE_CARD_FIELD_MISSING:{eid}:{field}")
        entry["locomotion"] = locomotion
        other = [k for k in LOCOMOTION_KINDS if k != locomotion][0]
        appearances: list[str] = []
        for index, shot in enumerate(shots):
            sid = _shot_id(shot, index)
            props = [_clean(p.get("prop_id")) for p in _spec(shot).get("props") or [] if isinstance(p, dict)]
            if eid not in props and eid not in _entity_states(shot):
                continue
            appearances.append(sid)
            text = _action_text(shot)
            if any(w in text for w in LOCOMOTION_WORDS[other]):
                failures.append(f"CREATURE_FORM_DRIFT:{eid}:{sid}")
        entry["appearances"] = appearances
    return _result(failures, measurements={"creatures": creatures})


# --------------------------------------------------------------------------- B4 ambush space


def _entity_name(contract: dict[str, Any], entity_id: str) -> str:
    for row in contract.get("non_character_entities") or []:
        if isinstance(row, dict) and _clean(row.get("entity_id")) == entity_id:
            return _clean(row.get("name")) or entity_id
    return entity_id


def check_ambush_space(contract: dict[str, Any]) -> dict[str, Any]:
    shots = _shots(contract)
    contracts = contract.get("ambush_contracts")
    trigger_shots = [
        _shot_id(s, i) for i, s in enumerate(shots)
        if any(w in _full_text(s) for w in AMBUSH_TRIGGER_WORDS)
    ]
    measurements: dict[str, Any] = {"trigger_shots": trigger_shots, "ambush_contracts": []}
    if not isinstance(contracts, list) or not contracts:
        if trigger_shots:
            return _result(["AMBUSH_CONTRACT_UNDECLARED"], measurements=measurements)
        return _result(measurements=measurements)

    failures: list[str] = []
    order = {_shot_id(s, i): i for i, s in enumerate(shots)}
    for amb in contracts:
        if not isinstance(amb, dict):
            continue
        reveal = _clean(amb.get("reveal_shot_id"))
        approachers = {_clean(c) for c in amb.get("who_approaches") or [] if _clean(c)}
        place_id = _clean(amb.get("hide_place_id"))
        place = _entity_name(contract, place_id)
        measurements["ambush_contracts"].append(
            {"hide_place_id": place_id, "place_name": place, "reveal_shot_id": reveal,
             "who_approaches": sorted(approachers)}
        )
        if reveal not in order:
            failures.append(f"AMBUSH_REVEAL_SHOT_MISSING:{reveal or 'EMPTY'}")
            continue
        if not approachers or not place:
            failures.append(f"AMBUSH_CONTRACT_INCOMPLETE:{reveal}")
            continue
        for index, shot in enumerate(shots[: order[reveal]]):
            sid = _shot_id(shot, index)
            subject = _clean((_spec(shot).get("action") or {}).get("subject_id"))
            present = approachers & (set(_cast_ids(shot)) | {subject})
            if not present:
                continue
            states = _entity_states(shot)
            evidence = shot.get("state_delta_evidence") or {}
            position = evidence.get("POSITION") if isinstance(evidence, dict) else None
            exit_text = _clean(position.get("exit")) if isinstance(position, dict) else ""
            texts = [
                _clean(shot.get("entry_state")),
                _clean(shot.get("completion_state")),
                _action_text(shot),
                *[states.get(cid, "") for cid in present],
            ]
            entered = (place in exit_text) or any(
                place in t and any(v in t for v in ENTER_VERBS) for t in texts
            )
            if entered:
                failures.append(f"AMBUSH_APPROACHER_ENTERS_HIDEOUT_BEFORE_REVEAL:{sid}")
    return _result(failures, measurements=measurements)


# --------------------------------------------------------------------------- B5 costume inheritance


def _int_ext(location_id: str) -> str:
    loc = location_id.upper()
    if "-INT" in loc:
        return "INT"
    if "-EXT" in loc:
        return "EXT"
    return ""


def check_costume_inheritance(contract: dict[str, Any]) -> dict[str, Any]:
    shots = _shots(contract)
    by_scene: dict[str, list[dict[str, Any]]] = {}
    for shot in shots:
        by_scene.setdefault(_clean(shot.get("scene_id")), []).append(shot)
    scenes = [s for s in contract.get("scene_states") or [] if isinstance(s, dict)]
    warnings: list[str] = []
    transitions: list[dict[str, Any]] = []
    for prev, cur in zip(scenes, scenes[1:]):
        before, after = _int_ext(_clean(prev.get("location_id"))), _int_ext(_clean(cur.get("location_id")))
        if not before or not after or before == after:
            continue
        prev_cast = {c for s in by_scene.get(_clean(prev.get("scene_id")), []) for c in _cast_ids(s)}
        cur_shots = by_scene.get(_clean(cur.get("scene_id")), [])
        cur_cast = {c for s in cur_shots for c in _cast_ids(s)}
        mentions = any(any(w in _full_text(s) for w in COSTUME_TRIGGER_WORDS) for s in cur_shots)
        overrides = cur.get("costume_overrides") if isinstance(cur.get("costume_overrides"), dict) else {}
        scene_id = _clean(cur.get("scene_id"))
        transitions.append({"scene_id": scene_id, "from": before, "to": after,
                            "costume_mentioned": mentions})
        if not mentions:
            continue
        for cid in sorted(prev_cast & cur_cast):
            if cid not in overrides:
                warnings.append(f"COSTUME_STATE_UNDECLARED:{scene_id}:{cid}")
    return _result(warnings=warnings, measurements={"int_ext_transitions": transitions})


# --------------------------------------------------------------------------- evaluate


def evaluate(contract: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "life_state": check_life_state(contract),
        "creature_card": check_creature_card(contract),
        "ambush_space": check_ambush_space(contract),
        "costume_inheritance": check_costume_inheritance(contract),
    }
    failures: list[str] = []
    warnings: list[str] = []
    measurements: dict[str, Any] = {
        "episode": _clean(contract.get("episode")),
        "shot_count": len(_shots(contract)),
    }
    if not _shots(contract):
        failures.append("SHOTS_MISSING")
    for name, result in checks.items():
        failures.extend(result["failures"])
        warnings.extend(result["warnings"])
        measurements[name] = result["measurements"]
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    return {
        "schema": SCHEMA,
        "status": status,
        "failures": _dedupe(failures),
        "warnings": _dedupe(warnings),
        "unverified": [
            "perceived_life_state / visible_group_count / creature_locomotion on generated video: "
            "NOT_IMPLEMENTED (post-generation review questions)"
        ],
        "measurements": measurements,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contract", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    report = evaluate(contract)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
