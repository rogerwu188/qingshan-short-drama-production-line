#!/usr/bin/env python3
"""FIGHT_DESIGN_V1 — writing-time (S1) fight design gate (Roger 2026-11-07: 「我希望以后的打斗片段，生产线都能学会
怎么生产，不要再犯同类错误」).

COMBAT_UNIT_DIRECTION_V1 stops a static fight at the paid boundary; by then keyframes are already paid for and
the writer has to restart.  This gate reads the writer's generation contract — the same schema on every line —
and rejects the E15 failure shapes before anything is grouped, compiled or paid:

  FD1 COMBAT_SHOT_CAMERA_LOCKED     a COMBAT shot is authored on a locked camera (E15: 9/9 locked)
  FD2 COMBAT_SHOT_WITH_DIALOGUE     a COMBAT shot carries an in-video line (tactical lines go before/after or V.O.)
  FD3 FIGHT_SCENE_NARRATED          in a scene with COMBAT shots, COMBAT seconds < 50 % of the scene
  FD4 COMBAT_RUN_SHORTER_THAN_UNIT  a silent run of shots that contains COMBAT is < 4 s, so grouping must merge
                                    the exchange into a dialogue unit (where the dialogue camera lock applies)
  FD5 FIGHTERS_FACE_CAMERA          a fight-scene shot composes the fighters with both faces to the lens
  FD6 COMBAT_WEAPON_WITHOUT_CARD    a weapon named in a COMBAT shot has no prop reference card, so its shape is
                                    re-invented every unit (E15: Fuentao's long sabre never registered; the iron
                                    spear declared_without_card -> sabre turned into a straight sword mid-unit)

Active from configs/FIGHT_DESIGN_V1.json enabled_from_episode, or when the contract declares
fight_design_policy=FIGHT_DESIGN_V1.  exit 0 PASS / NOT_ACTIVE, 3 BLOCK, 2 unreadable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

POLICY_ID = "FIGHT_DESIGN_V1"
POLICY_PATH = Path(__file__).resolve().parents[1] / "configs" / f"{POLICY_ID}.json"
LOCKED = {"", "LOCKED", "STATIC"}
MIN_COMBAT_SHARE = 0.5
MIN_COMBAT_RUN_SECONDS = 4.0
FACES_TO_CAMERA = re.compile(r"(都转向镜头|脸都转向镜头|都朝向镜头|脸都朝镜头|都面向镜头|都面朝镜头|both faces? (?:to|toward) (?:the )?(?:camera|lens))",
                             re.IGNORECASE)
#: weapon NOUNS (longest first); single characters (刀/矛/弓) are too ambiguous in prose (挥刀, 把矛) to count
WEAPON = re.compile(
    r"(砍柴刀|斩马刀|鬼头刀|长柄刀|柴刀|长刀|大刀|弯刀|朴刀|钢刀|短刀|佩刀|腰刀|横刀|唐刀|长剑|宝剑|短剑|铁剑|"
    r"铁矛|长矛|短矛|长枪|铁枪|红缨枪|硬弓|长弓|弓箭|战斧|板斧|铁锤|铜锤|长棍|铁棍|长鞭|铁鞭|长戟|方天戟|匕首|飞刀)")


def _episode_number(value: Any) -> int | None:
    match = re.match(r"E(\d+)", str(value or "").strip().upper())
    return int(match.group(1)) if match else None


def active(contract: dict[str, Any]) -> bool:
    if str(contract.get("fight_design_policy") or "").strip().upper() == POLICY_ID:
        return True
    try:
        start = _episode_number(json.loads(POLICY_PATH.read_text(encoding="utf-8")).get("enabled_from_episode"))
    except (OSError, ValueError):
        return False
    episode = _episode_number(contract.get("episode") or contract.get("episode_id"))
    return start is not None and episode is not None and episode >= start


def _spec(shot: dict[str, Any]) -> dict[str, Any]:
    return shot.get("prompt_spec") or {}


def _combat(shot: dict[str, Any]) -> bool:
    kind = str((_spec(shot).get("action") or {}).get("action_kind") or "").strip().upper()
    return kind in {"COMBAT", "ACTION_COMBAT", "FIGHT", "COMBAT_IMPULSE", "COMBAT_EXCHANGE"}


def _dialogue(shot: dict[str, Any]) -> bool:
    value = _spec(shot).get("dialogue")
    if isinstance(value, list):
        return any(str(x.get("text") if isinstance(x, dict) else x).strip() for x in value)
    return bool(str(value or "").strip())


def _seconds(shot: dict[str, Any]) -> float:
    for name in ("target_seconds", "sec", "duration_seconds"):
        try:
            value = float(shot.get(name) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _carded_names(contract: dict[str, Any]) -> list[str]:
    props = contract.get("props") or {}
    cards = props.get("reference_cards") if isinstance(props, dict) else props
    names = []
    for card in cards or []:
        if isinstance(card, dict) and card.get("name"):
            names.append(str(card["name"]))
    return names


def _weapons(shot: dict[str, Any]) -> set[str]:
    action = _spec(shot).get("action") or {}
    texts = [str(action.get("primary_action") or "")]
    choreo = action.get("combat_choreography") or {}
    exchange = choreo.get("exchange") or {}
    texts += [str(exchange.get(k) or "") for k in ("attack", "defender_answer")]
    texts.append(str(choreo.get("attack_defense_chain") or ""))
    texts += [str(p.get("prop") or "") for p in _spec(shot).get("props") or [] if isinstance(p, dict)]
    return {match.group(0) for text in texts for match in WEAPON.finditer(text)}


def evaluate(contract: dict[str, Any]) -> dict[str, Any]:
    if not active(contract):
        return {"gate_id": POLICY_ID, "status": "NOT_ACTIVE", "failures": []}
    shots = [s for s in contract.get("shots") or [] if isinstance(s, dict)]
    failures: list[dict[str, Any]] = []
    scenes: dict[str, dict[str, float]] = {}
    for shot in shots:
        bucket = scenes.setdefault(str(shot.get("scene_id") or ""), {"seconds": 0.0, "combat_seconds": 0.0})
        bucket["seconds"] += _seconds(shot)
        if _combat(shot):
            bucket["combat_seconds"] += _seconds(shot)
    fight_scenes = {s for s, b in scenes.items() if b["combat_seconds"] > 0}
    carded = _carded_names(contract)
    for shot in shots:
        sid = str(shot.get("shot_id") or "")
        scene = str(shot.get("scene_id") or "")
        camera = _spec(shot).get("camera_plan") or {}
        if _combat(shot):
            if str(camera.get("motion_family") or "").upper() in LOCKED:
                failures.append({"code": "COMBAT_SHOT_CAMERA_LOCKED", "shot_id": sid})
            if _dialogue(shot):
                failures.append({"code": "COMBAT_SHOT_WITH_DIALOGUE", "shot_id": sid})
            missing = sorted(w for w in _weapons(shot) if not any(w in name or name in w for name in carded))
            if missing:
                failures.append({"code": "COMBAT_WEAPON_WITHOUT_CARD", "shot_id": sid, "weapons": missing,
                                 "carded": carded})
        if scene in fight_scenes:
            text = " ".join(str(camera.get(k) or "") for k in ("axis_relation", "start_framing", "end_framing",
                                                                 "lens_intent")) + " " + str(shot.get("blocking") or "")
            if FACES_TO_CAMERA.search(text):
                failures.append({"code": "FIGHTERS_FACE_CAMERA", "shot_id": sid})
    for scene in sorted(fight_scenes):
        b = scenes[scene]
        share = b["combat_seconds"] / b["seconds"] if b["seconds"] else 0.0
        if share < MIN_COMBAT_SHARE:
            failures.append({"code": "FIGHT_SCENE_NARRATED", "scene_id": scene, "combat_share": round(share, 3)})
    # silent runs that contain combat must be long enough to be their own (unlocked) video unit
    run: list[dict[str, Any]] = []

    def close(run_rows: list[dict[str, Any]]) -> None:
        if run_rows and any(_combat(s) for s in run_rows):
            seconds = sum(_seconds(s) for s in run_rows)
            if seconds < MIN_COMBAT_RUN_SECONDS:
                failures.append({"code": "COMBAT_RUN_SHORTER_THAN_UNIT",
                                 "shot_ids": [str(s.get("shot_id")) for s in run_rows],
                                 "seconds": round(seconds, 3), "minimum": MIN_COMBAT_RUN_SECONDS})

    previous_scene = None
    for shot in shots:
        scene = shot.get("scene_id")
        if _dialogue(shot) or scene != previous_scene:
            close(run)
            run = []
        if not _dialogue(shot):
            run.append(shot)
        previous_scene = scene
    close(run)
    return {"gate_id": POLICY_ID, "status": "PASS" if not failures else "BLOCK",
            "authority": "Roger 2026-11-07「以后的打斗片段，生产线都能学会怎么生产，不要再犯同类错误」",
            "fight_scenes": {s: {k: round(v, 3) for k, v in scenes[s].items()} for s in sorted(fight_scenes)},
            "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contract", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"UNREADABLE: {exc}", file=sys.stderr)
        return 2
    report = evaluate(contract)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 3 if report["status"] == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
