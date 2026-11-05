#!/usr/bin/env python3
"""Combat exchange gate: a fight is several exchanges, not one strike.

Roger 2026-11-05: 「打斗至少要有几个回合才有感觉，没有你来我往的打斗场面」— a fight needs
several rounds with attack and answer going both ways. The engine already had every
physical fact it needed (force origin, contact point, feedback, exit state) but nothing
required the *other side* to act, and COMBAT_EXCHANGE capped a unit at two contacts, so
the cheapest passing shape was one side swinging once.

This gate reads the compiled execution plan and enforces configs/COMBAT_EXCHANGE_V1.json:

  * every exchange beat carries all four phases: the attacker's action, the defender's
    *authored* answer, visible force on the body, and a new position to start from;
  * within a fight, initiative changes hands at least once, and no two consecutive
    exchanges repeat the same attack answered the same way;
  * a fight needs at least `minimum_exchanges_per_fight` exchanges.

Two things it deliberately does not do. It does not require one 4-8 s take to alternate
initiative — the policy's own turns_note puts that requirement on the whole fight, and a
take holding a single exchange cannot alternate anything. And it does not treat every
combat beat as a round: a beat the writer declares `exchange_role: IMPULSE` is one authored
blow with one outcome (ch15's spear through the mastiff's skull), which owes no answer and
is not counted as a round.

It never invents moves, and it never triggers a reroll: it runs before submission, on the
authored plan, exactly like the other direction gates. An episode outside the policy's
scope is untouched.
"""
from __future__ import annotations

import json
import re
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

IMPULSE = "IMPULSE"
EXCHANGE = "EXCHANGE"
SINGLE = "SINGLE_EXCHANGE"
SEQUENCE = "SEQUENCE"
NOT_A_ROUND = {IMPULSE, SEQUENCE}


def load_policy(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or POLICY_PATH).read_text(encoding="utf-8"))


def episode_number(episode: Any) -> int | None:
    """``E15`` or a unit id like ``E15-VU-007``. The compiler's plan carries the unit id, and an
    episode that cannot be resolved makes the whole gate NOT_APPLICABLE."""
    match = re.match(r"^\s*E(\d+)", str(episode or "").upper())
    return int(match.group(1)) if match else None


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


def _exchange_role(beat: dict[str, Any]) -> str:
    """EXCHANGE by default: a combat beat is a round unless the writer says otherwise.

    IMPULSE is one authored blow with one outcome (ch15's spear through the mastiff): no answer,
    not a round. SEQUENCE is authored fight design that is not itself a round — closing distance
    under fire, taking cover, the recoil after an exchange — so it carries the combat choreography
    without owing an answer. SINGLE_EXCHANGE is exactly one attack and one answer with no bout
    following (ch15's thrown spear parried by a long sabre): a round, but not a fight, so the
    fight-wide round count does not apply to it.
    """
    role = str(beat.get("exchange_role") or "").strip().upper()
    if role in {IMPULSE, EXCHANGE, SINGLE, SEQUENCE}:
        return role
    return EXCHANGE


def _fight_id(beat: dict[str, Any]) -> str:
    return str(beat.get("fight_id") or "").strip()


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


def _judge_beats(beats: list[dict[str, Any]], unit_id: str) -> tuple[list[str], list[dict[str, Any]], int]:
    """Phase + repetition checks for the exchange beats of one unit. Impulses are not judged."""
    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    previous_pair: tuple[str, str] | None = None
    exchanges = 0
    for index, beat in enumerate(beats, 1):
        source_id = f"{unit_id}:BEAT_{index}"
        role = _exchange_role(beat)
        if role in NOT_A_ROUND:
            rows.append({"source_id": source_id, "exchange_role": role,
                         "initiator": _initiator(beat), "responder": _responder(beat)})
            continue
        exchanges += 1
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
        rows.append({"source_id": source_id, "exchange_role": EXCHANGE,
                     "initiator": _initiator(beat), "responder": _responder(beat),
                     "phases": phases, "attack_answer": list(pair) if pair else None})
    return failures, rows, exchanges


def evaluate(plan: dict[str, Any], *, policy: dict[str, Any] | None = None,
             scene_exchange_counts: dict[str, int] | None = None) -> dict[str, Any]:
    """Judge one compiled unit. The fight-wide account is `evaluate_fight`."""
    policy = policy or load_policy()
    unit_id = str(plan.get("unit_id") or "UNKNOWN")
    episode = plan.get("episode") or plan.get("unit_id")
    if not policy_active(episode, plan.get("combat_exchange_policy"), policy):
        return {"schema": GATE_ID, "status": "NOT_APPLICABLE", "unit_id": unit_id,
                "failures": [], "exchanges": 0, "impulses": 0}
    beats = _combat_beats(plan)
    if not beats:
        return {"schema": GATE_ID, "status": "NOT_APPLICABLE", "unit_id": unit_id,
                "failures": [], "exchanges": 0, "impulses": 0}

    failures, rows, exchanges = _judge_beats(beats, unit_id)
    if not exchanges:
        return {"schema": GATE_ID, "status": "NOT_APPLICABLE", "unit_id": unit_id,
                "reason": "IMPULSE_ONLY_UNIT", "failures": [], "exchanges": 0,
                "impulses": len(beats), "rows": rows}

    initiators = [row["initiator"] for row in rows if row.get("initiator")]
    # A unit holding two or more exchanges must alternate between them. A unit holding one
    # cannot, and the policy's turns_note puts that requirement on the whole fight.
    if exchanges >= int(policy.get("provider_budget", {}).get("max_exchanges_per_unit") or 2) \
            and len(set(initiators)) < 2:
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
        "exchanges": exchanges,
        "impulses": len(beats) - exchanges,
        "initiators": sorted(set(initiators)),
        "initiative_alternates": len(set(initiators)) >= 2,
        "rows": rows,
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
        "policy_id": policy.get("policy_id"),
        "policy_sha256": None,
    }


def evaluate_fight(plans: list[dict[str, Any]], *, policy: dict[str, Any] | None = None,
                   fight_key: str | None = None) -> dict[str, Any]:
    """Judge a whole fight, spread over the units that carry it.

    Per-unit judging cannot see the thing Roger asked for: 「打斗至少要有几个回合」是整场的账，
    不是单镜的账。Two units of one exchange each pass alone and are still a two-round fight;
    one unit of one exchange each is still nothing.

    The total is what enforces the round count and fight-wide initiative. Repeated pairs are
    compared across the whole fight in unit order, so the same attack answered the same way
    three units running still fails.
    """
    policy = policy or load_policy()
    plans = [plan for plan in plans if _combat_beats(plan)]
    # A bout declares fight_id and is counted across every unit carrying it: ch15's 傅恩涛 bout
    # spans the engage, the break and the re-engage in different scenes. Without fight_id the
    # scene is the fallback scope, as before.
    declared = sorted({fid for plan in plans for beat in _combat_beats(plan)
                       for fid in [_fight_id(beat)] if fid})
    if fight_key:
        key = fight_key
    elif len(declared) == 1:
        key = declared[0]
    elif len(declared) > 1:
        # Each declared bout is its own fight and owes its own round count. Merging them would
        # let one three-round bout carry a second one that has nothing, which is the accounting
        # Roger's rule is meant to prevent. Callers with several bouts in one pass ask per bout.
        raise ValueError("MULTIPLE_FIGHTS_IN_ONE_PASS:" + ",".join(declared))
    else:
        key = str((plans[0] or {}).get("scene_id") or "") if plans else ""
    if not plans:
        return {"schema": GATE_ID, "status": "NOT_APPLICABLE", "fight": key or None,
                "failures": [], "exchanges": 0, "impulses": 0}
    failures: list[str] = []
    exchanges = impulses = sequences = 0
    pairs: list[tuple[str, str]] = []
    initiators: list[str] = []
    unit_reports: list[dict[str, Any]] = []
    for plan in plans:
        unit_id = str(plan.get("unit_id") or "UNKNOWN")
        unit_failures, rows, unit_exchanges = _judge_beats(_combat_beats(plan), unit_id)
        failures.extend(unit_failures)
        exchanges += unit_exchanges
        impulses += sum(1 for row in rows if row.get("exchange_role") == IMPULSE)
        sequences += sum(1 for row in rows if row.get("exchange_role") == SEQUENCE)
        for row in rows:
            if row.get("initiator"):
                initiators.append(row["initiator"])
            if row.get("attack_answer"):
                pairs.append(tuple(row["attack_answer"]))
        unit_reports.append(evaluate(plan, policy=policy))
    minimum = int(policy["unit_shape"]["minimum_exchanges_per_fight"])
    singles = sum(1 for plan in plans for beat in _combat_beats(plan)
                  if _exchange_role(beat) == SINGLE)
    # A declared single exchange is one attack and one answer by design; the round count is a
    # statement about fights, not about it. Every other exchange beat is a fight and must reach
    # the minimum.
    fight_exchanges = exchanges - singles
    if fight_exchanges and fight_exchanges < minimum:
        failures.append(f"{TOO_FEW}:{key or 'FIGHT'}:{fight_exchanges}<{minimum}")
    elif fight_exchanges and len(set(initiators)) < 2:
        # No single unit held both directions, but the fight as a whole must still.
        failures.append(f"{INITIATIVE_STATIC}:{key or 'FIGHT'}:{','.join(sorted(set(initiators))) or 'NONE'}")
    repeats = [f"{left[0]}+{left[1]}" for left, right in zip(pairs, pairs[1:]) if left == right]
    for repeat in sorted(set(repeats)):
        failures.append(f"{REPEATED_PAIR}:{key or 'FIGHT'}:{repeat}")
    return {
        "schema": GATE_ID,
        "fight": key or None,
        "episode": str((plans[0] or {}).get("episode") or "") or None,
        "units": [report["unit_id"] for report in unit_reports],
        "exchanges": exchanges,
        "single_exchanges": singles,
        "impulses": impulses,
        "sequences": sequences,
        "initiators": sorted(set(initiators)),
        "initiative_alternates": len(set(initiators)) >= 2,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "policy_id": policy.get("policy_id"),
        "unit_reports": unit_reports,
    }
