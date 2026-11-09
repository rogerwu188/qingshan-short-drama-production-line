#!/usr/bin/env python3
"""COMBAT_MOTION_V1 — a fight unit is compiled as an action shot list, not as a state change.

Roger 2026-11-08 (E15 看片, order seq=219): 「打斗镜头根本不像是专业的武侠打斗。」 The E15 remedies
were text-level and the model behaved identically three takes running: VU-020 froze blade-on-shaft
for 1.75–2.0 s every time.  The cause is upstream — the renderer handed each fight beat the
dialogue-scene template:

    [2s-4.5s] Start from <state>. Force origin: <state>. <action>. Interaction mode: physical
    contact; the interaction point is reached at 2.55s at <contact>. primary feedback: <state>.
    End at <state>.

That asks the model to *complete a state change*, so it holds the contact and slides.  A fight needs
an action ladder: who strikes, what meets it, where the force lands, what moves where.

This module turns authored combat text into that ladder:

  compile_combat_unit(...)  →  {shots: [{index, start, end, seconds, scale, camera, strike,
                               guard, contact, displacement, result}], text: "[Shot N · a–b s · …]"}

Rules (configs/COMBAT_MOTION_V1.json):
  CM1 one move per shot            a strike, its reception and its displacement are separate shots
  CM2 every shot states a body     each shot names the part met and the direction/distance moved
  CM3 single contact               a shot that makes contact carries no second contact
  CM4 contact is short             a contact shot is at most ``max_contact_seconds`` (0.4 s)
  CM5 the segment ends in motion   the last shot's result is an ongoing move, never a settled pose
  CM6 scale changes across shots   consecutive shots never share the same scale and camera side

The renderer (tools/h3_provider_prompt_renderer.py) calls ``combat_shot_lines`` for a COMBAT beat
when the policy is active and the beat carries an authored action ladder; otherwise it keeps the
legacy state template (old episodes unchanged).

Offline, free.  exit 0 ok, 2 unreadable.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

POLICY_ID = "COMBAT_MOTION_V1"
POLICY_PATH = Path(__file__).resolve().parents[1] / "configs" / f"{POLICY_ID}.json"

DEFAULT_MAX_CONTACT_SECONDS = 0.4
DEFAULT_MIN_SHOT_SECONDS = 0.5
DEFAULT_MAX_SHOT_SECONDS = 1.5

#: wording that means "hold still" — never allowed as a shot result
SETTLE_WORDS = ("保持不变", "停住", "定住", "僵持", "顶住", "咬住", "相持", "撑住",
                "hold", "holds", "held", "settle", "settles", "brace", "braces", "locked", "lock")

#: the body part a strike can land on, and the displacement a result must state
BODY_PARTS = ("刀面", "刀身", "刀背", "刀刃", "矛杆", "矛尖", "护臂", "肩", "手腕", "胸口", "肋", "腿",
              "blade", "shaft", "bracer", "shoulder", "wrist", "chest", "ribs", "leg", "guard")
DIRECTIONS = ("画左", "画右", "向前", "向后", "上挑", "下压", "左", "右", "前", "后",
              "frame left", "frame right", "forward", "back", "up", "down")
DISTANCE = ("半尺", "一尺", "半臂", "一臂", "半步", "一步", "两步", "三步",
            "half a foot", "a foot", "half an arm", "an arm", "half a step", "a step", "two steps", "three steps")

#: wording that states the weapons actually met in this move
CONTACT_VERBS = re.compile(r"(?:砍在|劈在|砍上|撞在|撞上|砸在|砸上|架住|格开|击中|strikes|lands on|clashes)")

CJK = re.compile(r"[\u4e00-\u9fff]")

SCALE_OF_SIZE = {"远景": "WIDE", "全景": "FULL", "中全景": "MEDIUM_WIDE", "中景": "MEDIUM",
                 "中近景": "MEDIUM_CLOSE_UP", "近景": "CLOSE_UP", "特写": "EXTREME_CLOSE_UP"}


def policy_loaded(path: Path | None = None) -> dict[str, Any]:
    try:
        return json.loads((path or POLICY_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def policy_active(contract: dict[str, Any] | None, *, episode: str | None, policy: dict[str, Any]) -> bool:
    if not policy:
        return False
    if str((contract or {}).get("combat_motion_policy") or "").strip() == POLICY_ID:
        return True
    start = str(policy.get("enabled_from_episode") or "").strip()
    if not start or not episode:
        return False
    try:
        return int(re.sub(r"\D", "", episode)) >= int(re.sub(r"\D", "", start))
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# authored ladder → shots
# --------------------------------------------------------------------------- #

def _split_moves(text: str) -> list[str]:
    """Split authored action text into moves at sentence and semicolon boundaries."""
    parts = re.split(r"[。；;]\s*|\n+", str(text or ""))
    return [p.strip(" ，,、") for p in parts if p.strip(" ，,、")]


def _scale_of(shot: dict[str, Any], default: str = "MEDIUM") -> str:
    size = str((((shot.get("prompt_spec") or {}).get("camera_plan") or {}).get("shot_scale"))
               or shot.get("shot_scale") or "")
    return SCALE_OF_SIZE.get(size, size.upper() or default)


def _camera_of(shot: dict[str, Any]) -> str:
    plan = (shot.get("prompt_spec") or {}).get("camera_plan") or {}
    side = str(plan.get("camera_side") or "")
    height = str(plan.get("camera_height") or "")
    return " ".join(x for x in (side, height) if x)


def analyse_shot_text(move: str, *, contact: bool) -> dict[str, Any]:
    """What one authored move states: the body it meets, the direction and the distance moved."""
    low = move.lower()
    return {
        "body": next((p for p in BODY_PARTS if p.lower() in low), None),
        "direction": next((d for d in DIRECTIONS if d.lower() in low), None),
        "distance": next((d for d in DISTANCE if d.lower() in low), None),
        "settles": next((w for w in SETTLE_WORDS if w in low), None),
        "contact": contact,
    }


def compile_combat_unit(beat: dict[str, Any], translated: dict[str, Any] | None = None,
                        *, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """One COMBAT beat → an action shot list.

    ``beat`` is the compiled beat spec (start_seconds / end_seconds / primary_action / contact_point /
    exit_state, optionally ``combat_shots`` authored by the writer).  When the writer authored
    ``combat_shots`` they are used verbatim; otherwise the action text is split into moves.
    """
    rules = (policy or policy_loaded()).get("rules") or {}
    max_contact = float(rules.get("max_contact_seconds") or DEFAULT_MAX_CONTACT_SECONDS)
    min_shot = float(rules.get("min_shot_seconds") or DEFAULT_MIN_SHOT_SECONDS)
    max_shot = float(rules.get("max_shot_seconds") or DEFAULT_MAX_SHOT_SECONDS)
    start = float(beat.get("start_seconds") or 0.0)
    end = float(beat.get("end_seconds") or start + max_shot)
    window = max(end - start, min_shot)
    authored = beat.get("combat_shots") or []
    if authored:
        moves = [{"text": str(row.get("move") or row.get("text") or "").strip(),
                  "seconds": float(row.get("seconds") or 0.0),
                  "scale": str(row.get("shot_scale") or ""),
                  "camera": str(row.get("camera_side") or ""),
                  "contact": bool(row.get("contact"))}
                 for row in authored if isinstance(row, dict)]
    else:
        # H3 accepts no CJK outside <d> tags, so the ladder is split from the ENGLISH action when the
        # caller supplies it; the authored Chinese is only used when no translation exists.
        english = str((translated or {}).get("primary_action") or "").strip()
        authored_text = english if english and not CJK.search(english) else str(beat.get("primary_action") or "")
        texts = _split_moves(authored_text)
        if not texts:
            texts = [str((translated or {}).get("primary_action") or "").strip() or "the strike continues"]
        contact_marker = str(beat.get("contact_point") or "")
        moves = []
        for index, text in enumerate(texts):
            stated = bool(CONTACT_VERBS.search(text)) or (bool(contact_marker) and index == len(texts) // 2)
            moves.append({"text": text, "seconds": 0.0, "scale": "", "camera": "", "contact": stated})
    # Durations always fill the beat window exactly: the ladder is a cut list inside [start, end], never
    # past it.  (E15 VU-020 2026-11-09: clamping every shot up to min_shot pushed beat 3's five shots to
    # 6.9 s inside a 6.5 s window and beat 2's six shots into beat 3.)  Contact shots are capped first; the
    # remaining time is shared by the other shots in proportion to their authored (or equal) weights.
    bodies = [analyse_shot_text(m["text"], contact=m["contact"]) for m in moves]
    weights = [m["seconds"] or 1.0 for m in moves]
    durations = [0.0] * len(moves)
    contact_ix = [i for i, b in enumerate(bodies) if b["contact"]]
    free_ix = [i for i in range(len(moves)) if i not in contact_ix]
    even = window / len(moves)
    for i in contact_ix:
        durations[i] = min(max_contact, even if not free_ix else max_contact)
    rest = window - sum(durations[i] for i in contact_ix)
    free_weight = sum(weights[i] for i in free_ix)
    for i in free_ix:
        durations[i] = rest * weights[i] / free_weight
    if not free_ix and contact_ix:
        durations[contact_ix[-1]] += window - sum(durations)
    shots: list[dict[str, Any]] = []
    cursor = start
    for index, (move, body, seconds) in enumerate(zip(moves, bodies, durations), 1):
        if index == len(moves):
            seconds = end - cursor if end > cursor else seconds  # absorb rounding so the ladder ends on `end`
        shots.append({
            "index": index, "start": round(cursor, 3), "end": round(cursor + seconds, 3), "seconds": round(seconds, 3),
            "scale": move["scale"] or (str(beat.get("shot_scale") or "") if index == 1 else ""),
            "camera": move["camera"] or (str(beat.get("camera_family") or "") if index == 1 else ""),
            "move": move["text"], "body": body["body"], "direction": body["direction"],
            "distance": body["distance"], "contact": body["contact"], "settles": body["settles"],
        })
        cursor += seconds
    # CM1 is about one move per shot; a window too short for every shot to reach min_shot is reported,
    # not silently stretched past the beat.
    short = [s["index"] for s in shots if s["seconds"] + 1e-6 < min(min_shot, max_contact) and not s["contact"]]
    return {"shots": shots, "start": start, "end": end, "window": round(window, 3), "short_shots": short,
            "text": render_shot_lines(shots)}


def render_shot_lines(shots: list[dict[str, Any]]) -> str:
    lines = []
    for shot in shots:
        # One decimal is what an editor cuts on; three decimals cost runes and imply false precision.
        head = f"[Shot {shot['index']} · {round(shot['start'], 1):g}–{round(shot['end'], 1):g} s"
        if shot.get("scale"):
            head += f" · {shot['scale']}"
        if shot.get("camera"):
            head += f", {shot['camera']}"
        lines.append(f"{head}] {shot['move']}")
    return "\n".join(lines)


def validate_ladder(compiled: dict[str, Any], *, policy: dict[str, Any] | None = None) -> list[str]:
    """CM1–CM6 over a compiled ladder; returns failure codes (empty = pass)."""
    rules = (policy or policy_loaded()).get("rules") or {}
    max_contact = float(rules.get("max_contact_seconds") or DEFAULT_MAX_CONTACT_SECONDS)
    failures: list[str] = []
    shots = compiled.get("shots") or []
    if len(shots) < 2:
        failures.append("CM1_COMBAT_LADDER_TOO_SHORT")
    for prev, cur in zip(shots, shots[1:]):
        if prev.get("scale") and cur.get("scale") and prev["scale"] == cur["scale"] and prev.get("camera") == cur.get("camera"):
            failures.append(f"CM6_NO_SCALE_CHANGE:{cur['index']}")
    contact_shots = [s for s in shots if s.get("contact")]
    if len(contact_shots) > 1:
        failures.append(f"CM3_MULTIPLE_CONTACT_SHOTS:{len(contact_shots)}")
    for shot in contact_shots:
        if shot["seconds"] > max_contact:
            failures.append(f"CM4_CONTACT_TOO_LONG:{shot['index']}:{shot['seconds']}")
    # CM2: force must have a target and a destination.  A contact shot names the body it meets; every
    # shot after the contact names the direction the force sends the other body; the ladder as a whole
    # names at least one distance.  A shot that names none of these is a pose, not a move.
    contact_at = next((i for i, sh in enumerate(shots) if sh.get("contact")), None)
    for i, shot in enumerate(shots):
        if shot["index"] == 1 and not shot.get("contact"):
            continue  # the wind-up itself (the blade coming down) has no target yet
        if shot.get("contact") and not shot.get("body"):
            failures.append(f"CM2_CONTACT_SHOT_NO_BODY:{shot['index']}")
        if contact_at is not None and i > contact_at and not shot.get("direction"):
            failures.append(f"CM2_RESULT_SHOT_NO_DIRECTION:{shot['index']}")
    if not any(shot.get("distance") for shot in shots):
        failures.append("CM2_LADDER_STATES_NO_DISTANCE")
    for shot in shots:
        if shot.get("settles"):
            failures.append(f"CM5_SETTLED_RESULT:{shot['index']}:{shot['settles']}")
    return failures


def combat_shot_lines(beat: dict[str, Any], translated: dict[str, Any] | None = None,
                      *, policy: dict[str, Any] | None = None) -> tuple[str | None, dict[str, Any]]:
    """Renderer hook: the shot-list text for a COMBAT beat, plus the evidence facts it states.

    Returns ``(None, {})`` when the policy is inactive or the beat has no authored ladder, so the
    caller keeps the legacy template (delivered episodes stay byte-identical).
    """
    pol = policy or policy_loaded()
    if not pol:
        return None, {}
    if not (beat.get("combat_shots") or beat.get("primary_action")):
        return None, {}
    compiled = compile_combat_unit(beat, translated, policy=pol)
    if not compiled["shots"]:
        return None, {}
    return compiled["text"], {"COMBAT_SHOTS": compiled["shots"]}
