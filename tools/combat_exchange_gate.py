#!/usr/bin/env python3
"""Combat exchange gate: a fight is several exchanges, not one strike.

Roger 2026-11-05: 「打斗至少要有几个回合才有感觉，没有你来我往的打斗场面」— a fight needs
several rounds with attack and answer going both ways. The engine already had every
physical fact it needed (force origin, contact point, feedback, exit state) but nothing
required the *other side* to act, and COMBAT_EXCHANGE capped a unit at two contacts, so
the cheapest passing shape was one side swinging once.

This gate reads the compiled execution plan and enforces configs/COMBAT_EXCHANGE_V1.json:

  * every combat beat is one complete exchange: both sides act, force is evident, and
    the beat ends in a new position;
  * initiative changes hands at least once across the unit;
  * no two consecutive exchanges repeat the same attack against the same answer;
  * a fight that is spread over several units has at least `minimum_exchanges_per_fight`
    exchanges in the scene in total, and each unit holds at least one complete exchange.

It never invents moves, and it never triggers a reroll: it runs before submission, on the
authored plan, exactly like the other direction gates. An episode outside the policy's
scope is untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
POLICY_PATH = ROOT / "configs" / "COMBAT_EXCHANGE_V1.json"
GATE_ID = "COMBAT-EXCHANGE-V1"

#: Why a beat fails to be an exchange. Each is a distinct repair the writer can make.
DEFENDER_MISSING = "EXCHANGE_DEFENDER_ANSWER_MISSING"
INITIATOR_MISSING = "EXCHANGE_INITIATOR_MISSING"
FORCE_MISSING = "EXCHANGE_FORCE_EVIDENCE_MISSING"
POSITION_MISSING = "EXCHANGE_NEW_POSITION_MISSING"
INITIATIVE_STATIC = "EXCHANGE_INITIATIVE_NEVER_CHANGES"
REPEATED_PAIR = "EXCHANGE_REPEATS_PREVIOUS_ATTACK_ANSWER"
TOO_FEW = "EXCHANGE_TOO_FEW_IN_FIGHT"


def load_policy(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or POLICY_PATH).read_text(encoding="utf-8"))


def episode_number(episode: Any) -> int | None:
    text = str(episode or "").strip().upper()
    if text.startswith("E") and text[1:].isdigit():
        return int(text[1:])
    return None


def policy_active(episode: Any, declared: Any, policy: dict[str, Any]) -> bool:
    """Same shape as STATE_DELTA_SEMANTICS_V1: an explicit declaration, an episode list,
    or an episode floor; anything else keeps the old behaviour."""
    if str(declared or "").strip().upper() == str(policy.get("policy_id") or ""):
        return True
    enabled = {str(v).upper() for v in policy.get("enabled_episodes") or []}
    if "ALL" in enabled or str(episode or "").strip().upper() in enabled:
        return True
    floor = policy.get("enabled_from_episode")
    number = episode_number(episode)
    return bool(floor and number is not None and number >= int(floor))


def _combat_beats(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [beat for beat in plan.get("beats") or []
            if str(beat.get("source_action_kind") or "").upper() == "COMBAT"
            or plan.get("unit_class") in {"COMBAT_IMPULSE", "COMBAT_EXCHANGE"}]


def _initiator(beat: dict[str, Any]) -> str:
    return str(beat.get("action_subject") or beat.get("action_subject_id") or "").strip()


def _responder(beat: dict[str, Any]) -> str:
    return str(beat.get("action_patient") or beat.get("action_patient_id") or "").strip()


def _exchange_phases(beat: dict[str, Any]) -> dict[str, bool]:
    """Which of the four phases this beat actually carries.

    DEFENDER_ANSWER is the phase the old plan shape never had: a beat whose only named
    actor is the attacker and whose text never mentions the other side's response is a
    swing at a training dummy, not an exchange.
    """
    action = str(beat.get("primary_action") or "")
    responder = _responder(beat)
    # The answer must be the authored field, not a verb found somewhere in the prose: a beat
    # whose exit_state happens to say "格开" proves the defence happened, not that the writer
    # designed one. Required for every exchange beat under this policy.
    return {
        "ATTACKER_ACTION": bool(_initiator(beat) and (action or beat.get("force_origin"))),
        "DEFENDER_ANSWER": bool(responder and str(beat.get("defender_answer") or "").strip()),
        "FORCE_EVIDENCE": bool(str(beat.get("primary_feedback") or beat.get("force_feedback") or "").strip()),
        "NEW_POSITION": bool(str(beat.get("exit_state") or "").strip()
                             and str(beat.get("exit_state") or "").strip() != str(beat.get("entry_state") or "").strip()),
    }


def _attack_answer_pair(beat: dict[str, Any]) -> tuple[str, str] | None:
    attack = str(beat.get("attack_kind") or "").strip().upper()
    answer = str(beat.get("defender_answer_kind") or "").strip().upper()
    return (attack, answer) if attack or answer else None


def evaluate(plan: dict[str, Any], *, policy: dict[str, Any] | None = None,
             scene_exchange_counts: dict[str, int] | None = None) -> dict[str, Any]:
    """Gate one compiled plan. `scene_exchange_counts` lets a scene-level caller add up
    the exchanges of every unit in the fight; a single-plan call judges the unit alone."""
    policy = policy or load_policy()
    unit_id = str(plan.get("unit_id") or "UNKNOWN")
    if not policy_active(plan.get("episode"), plan.get("combat_exchange_policy"), policy):
        return {"schema": GATE_ID, "status": "NOT_APPLICABLE", "unit_id": unit_id,
                "failures": [], "exchanges": 0}
    beats = _combat_beats(plan)
    if not beats:
        return {"schema": GATE_ID, "status": "NOT_APPLICABLE", "unit_id": unit_id,
                "failures": [], "exchanges": 0}

    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    initiators: list[str] = []
    previous_pair: tuple[str, str] | None = None
    for index, beat in enumerate(beats, 1):
        source_id = f"{unit_id}:EXCHANGE_{index}"
        phases = _exchange_phases(beat)
        if not phases["ATTACKER_ACTION"]:
            failures.append(f"{INITIATOR_MISSING}:{source_id}")
        if not phases["DEFENDER_ANSWER"]:
            failures.append(f"{DEFENDER_MISSING}:{source_id}")
        if not phases["FORCE_EVIDENCE"]:
            failures.append(f"{FORCE_MISSING}:{source_id}")
        if not phases["NEW_POSITION"]:
            failures.append(f"{POSITION_MISSING}:{source_id}")
        pair = _attack_answer_pair(beat)
        if pair and previous_pair and pair == previous_pair:
            failures.append(f"{REPEATED_PAIR}:{source_id}:{pair[0]}+{pair[1]}")
        if pair:
            previous_pair = pair
        initiator = _initiator(beat)
        if initiator:
            initiators.append(initiator)
        rows.append({"source_id": source_id, "initiator": initiator,
                     "responder": _responder(beat), "phases": phases,
                     "attack_answer": list(pair) if pair else None})

    if len(set(initiators)) < 2:
        # One side acting in every exchange is a demonstration, not a fight.
        failures.append(f"{INITIATIVE_STATIC}:{unit_id}:{','.join(sorted(set(initiators))) or 'NONE'}")

    scene_id = str(plan.get("scene_id") or "").strip()
    if scene_exchange_counts is not None and scene_id:
        total = int(scene_exchange_counts.get(scene_id) or 0)
        minimum = int(policy["unit_shape"]["minimum_exchanges_per_fight"])
        if total and total < minimum:
            failures.append(f"{TOO_FEW}:{scene_id}:{total}<{minimum}")

    return {
        "schema": GATE_ID,
        "unit_id": unit_id,
        "scene_id": scene_id or None,
        "exchanges": len(beats),
        "initiators": sorted(set(initiators)),
        "initiative_alternates": len(set(initiators)) >= 2,
        "rows": rows,
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
        "policy_id": policy.get("policy_id"),
        "policy_sha256": None,
    }
