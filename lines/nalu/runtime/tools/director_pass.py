#!/usr/bin/env python3
"""L4 director pass (BILI_V1 only; CHANGE_SPEC WP3, line owner 2026-11-23, Bilibili benchmark ep2 + ep3).

The writer's screenplay (L3: dialogue, action lines, props, shot order) is the content.  This pass is the director:
it turns each line into TV coverage and may only set *framing* --

- the listener's ``face_visibility`` (over-the-shoulder ``OTS_LISTENER`` by default in a scene with >= 2 people;
  a writer-declared OTS / back / ``SOFT_PROFILE`` / off-screen listener is kept);
- ``camera_plan`` motion (locked by default; ONE slow push-in per scene, on the line the writer marked as the
  scene's hardest one: ``prompt_spec.hardest_line: true``; a ``beat_role: TURN`` line when nothing is marked);
- ``target_seconds`` (+1.5 s on a speaking shot that opens on an authored lead-in reaction);
- the ``prompt_spec.director`` block (what it decided and why) and the contract-level ``director_pass`` stamp.

It may NOT change dialogue text, action text, reaction text, props or shot order.  :func:`content_fingerprint`
hashes exactly those before and after; a mismatch is the INTEGRITY code ``DIRECTOR_CHANGED_CONTENT`` (never
admitted).

Reactions follow the owner's cheap rule (2026-11-23).  After every ``ATTACK / REVEAL / PUNCHLINE / TURN / PAYOFF``
line the person it lands on reacts, in order of preference:

  (a) in the same shot, as the in-frame (OTS / two-shot) listener: ``action.listener_reaction(_en)``;
  (b) in the first 1-2 s of the next shot, which belongs to the reacting character:
      ``action.lead_in_reaction(_en)`` ("for the first 1.5 s, before speaking, X ...");
  (c) a dedicated silent reaction close-up (``beat_role: REACTION``), at most 3 per episode, only after a
      ``REVEAL / TURN / ENDING`` beat (or as the episode's last shots).

:func:`reaction_coverage` measures it; ``script_pacing_check`` turns it into the taste codes
``REACTION_BEAT_UNCOVERED`` / ``DEDICATED_REACTION_OVER`` under BILI_V1.

Silence: one ``beat_role: MUSIC_PASSAGE`` run per episode (3-4 silent shots, <= 8 s together) is allowed (the same
marker WP5 mixes the passage's music on).

WP6 hooks (``craft_ledger.director_hints``, optional import): an object-first entrance that tilts / pushes / pans to
the face is that scene's one move; a ``mirror_of`` scene's first shot reuses the mirrored scene's camera setup; more
dedicated inserts than WP6's cap get the zero-cost insert-alternative advisory.

LEGACY contracts are returned unchanged (byte-identical): :func:`direct` is a no-op unless the profile is BILI_V1.
CLI: ``python3 director_pass.py CONTRACT.json [--write] [--force] [--report OUT.json]``.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from tools import craft_profile as _cp
except ModuleNotFoundError:  # runtime tools dir only
    import craft_profile as _cp

SCHEMA = "nalu.director_pass.v1"
VERSION = "1"
PROFILE = "BILI_V1"

#: beats after which the person the line lands on must react (a / b / c)
TRIGGER_ROLES = frozenset({"ATTACK", "REVEAL", "PUNCHLINE", "TURN", "PAYOFF"})
#: a dedicated silent reaction close-up is only for these beats (or the episode's ending)
DEDICATED_ALLOWED_AFTER = frozenset({"REVEAL", "TURN", "ENDING"})
DEDICATED_REACTION_MAX = 3
REACTION_ROLE = "REACTION"
MUSIC_PASSAGE_ROLE = "MUSIC_PASSAGE"
MUSIC_PASSAGE_SECONDS_MAX = 8.0
MUSIC_PASSAGES_MAX = 1
#: a lead-in reaction adds this much to the speaking shot (CHANGE_SPEC WP3 L4 7: <= +2 s)
LEAD_IN_SECONDS = 1.5
UNIT_MIN_SECONDS = 4.0          # historical HopsAPI H3 floor; live value: unit_min_seconds() (tools/h3_limits.py)
#: authored cuts / reverse angles the director adds per episode (each = one more start keyframe; WP2 compiles every
#: transition CONTINUOUS_ACTION, cost-neutral).  Turns first, then reveals, then payoffs / attacks / punchlines.
AUTHORED_CUT_MAX = 3
CUT_PRIORITY = {"TURN": 0, "REVEAL": 1, "PAYOFF": 2, "ATTACK": 2, "PUNCHLINE": 2}
CUT_MODES = frozenset({"MOTIVATED_CUT", "REACTION_CUT", "MATCH_CUT", "HARD_CUT", "SMASH_CUT"})
#: with a 2 s H3 floor (owner 2026-11-23, not live yet): dedicated reaction / insert units are cut short (ep3 rhythm:
#: ~48 % of shots under 2 s) and, at the same credits, twice as many are affordable
SHORT_UNIT_SECONDS = 2.0
SHORT_UNIT_RANGE = (1.5, 2.5)
SHORT_ROLES = frozenset({REACTION_ROLE, "INSERT"})


def unit_min_seconds() -> int:
    """The shortest H3 unit (tools/h3_limits.py: NALU_H3_MIN_UNIT_SECONDS > configs/H3_LIMITS_V1.json > 4)."""
    try:
        try:
            from tools import h3_limits as _limits  # noqa: PLC0415
        except ModuleNotFoundError:
            sys.path.append(str(Path(__file__).resolve().parents[4] / "tools"))
            import h3_limits as _limits  # type: ignore  # noqa: PLC0415
        return _limits.min_unit_seconds()
    except Exception:  # noqa: BLE001 -- the historical floor
        return int(UNIT_MIN_SECONDS)


def dedicated_reaction_max(min_seconds: int | None = None) -> int:
    """3 per episode at the 4 s floor (owner's cheap rule); the same credits buy proportionally more short units."""
    floor = unit_min_seconds() if min_seconds is None else min_seconds
    return DEDICATED_REACTION_MAX if floor >= 4 else DEDICATED_REACTION_MAX * 4 // max(1, floor)
UNIT_HARD_MAX_SECONDS = 15.0    # tools/speaking_unit_duration.GROUP_HARD_MAX_SECONDS
TWO_PERSON_UNIT_MAX_SECONDS = 12.0
LISTENER_IN_FRAME_TARGET = 0.40
#: the listener framing the pass writes (tools/h3_provider_prompt_renderer.is_ots_visibility)
OTS_LISTENER = "OTS_LISTENER"
SOFT_PROFILE = "SOFT_PROFILE"
PUSH_MARK = "bili_slow_push_in"
PUSH_MOTIVE_ZH = "缓慢推近约10%（动机：本场最难的一句）"
PUSH_MOTIVATION = "动机：本场最难的一句 -- slow push-in, about 10 % closer over the shot"
PUSH_END_SUFFIX = " The slow push-in ends about 10 % closer."

#: one continuous small action may run while a line is spoken (C-03 relaxed under BILI_V1)
SMALL_ACTION = re.compile(
    r"拿着|握着|捏着|端着|攥着|抱着|吃|嚼|啃|喝|抿|嗑|剥|搓手|搓着手|推眼镜|扶眼镜|推了推眼镜|摘下?墨镜|戴上?墨镜|转着|"
    r"把玩|摩挲|揉脖子|揉着脖子|摸后颈|擦泪|抹泪|擦眼泪|掰手指|掰着手指|数手指|扇着|摇着扇|绕着头发|"
    r"\b(?:hold(?:s|ing)?|eat(?:s|ing)?|chew(?:s|ing)?|munch(?:es|ing)?|sip(?:s|ping)?|nibbl(?:e|es|ing)|"
    r"rub(?:s|bing)? (?:his|her|their) hands|adjust(?:s|ing)? (?:his|her|their)? ?(?:sun)?glasses|"
    r"push(?:es|ing)? up (?:his|her|their) glasses|turn(?:s|ing)? (?:the|a|his|her) (?:token|coin|ring|cup)|"
    r"twirl(?:s|ing)?|spin(?:s|ning)? (?:the|a|his|her)|toy(?:s|ing)? with|fiddl(?:e|es|ing) with|"
    r"rub(?:s|bing)? (?:the back of )?(?:his|her|their) neck|wip(?:e|es|ing) (?:away )?(?:his|her|their)? ?tears|"
    r"count(?:s|ing)? on (?:his|her|their) fingers|fan(?:s|ning)? (?:himself|herself))\b",
    re.IGNORECASE)
#: a large action gets its own shot (C-03 kept for these)
LARGE_ACTION = re.compile(
    r"走进|走向|走到|进门|闯|冲|扑|跑|奔|抓住|揪住|推开|推倒|甩开|撞|打|踢|扇了?一?耳光|拔剑|跪下|站起身|转身离开|"
    r"\b(?:enter(?:s|ing)?|walk(?:s|ing)?|strid(?:e|es|ing)|run(?:s|ning)?|rush(?:es|ing)?|lung(?:e|es|ing)|"
    r"grab(?:s|bing)?|shov(?:e|es|ing)|slap(?:s|ping)?|punch(?:es|ing)?|kick(?:s|ing)?|tackl(?:e|es|ing)|"
    r"draw(?:s|ing)? (?:a|his|her|the) (?:sword|blade|gun)|kneel(?:s|ing)?|storm(?:s|ing)? (?:in|out|off))\b",
    re.IGNORECASE)
#: a listener declared with one of these is a second sharp front face: the director turns it into an OTS figure;
#: any other declared value (OTS / back / profile / bust / off-screen ...) is the writer's choice and is kept
_FRONT_FACE = frozenset({"FRONT_FACE_VISIBLE", "FRONT_FACE", "FACE_VISIBLE", "VISIBLE", "FULL_FACE",
                         "VISIBLE_PER_FRAME_CONTENT", "VISIBLE_AND_IDENTITY_LOCKED"})


# --------------------------------------------------------------------------- small readers
def _clean(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _spec(shot: dict[str, Any]) -> dict[str, Any]:
    spec = shot.get("prompt_spec")
    return spec if isinstance(spec, dict) else {}


def _action(shot: dict[str, Any]) -> dict[str, Any]:
    action = _spec(shot).get("action")
    return action if isinstance(action, dict) else {}


def _role(shot: dict[str, Any]) -> dict[str, Any]:
    role = _spec(shot).get("role_semantic_disambiguation")
    return role if isinstance(role, dict) else {}


def beat_role(shot: dict[str, Any]) -> str:
    return _clean(_spec(shot).get("beat_role") or shot.get("beat_role")).upper()


def dialogue_text(shot: dict[str, Any]) -> str:
    value = _spec(shot).get("dialogue")
    if value in (None, "", []):
        value = shot.get("dialogue")
    if isinstance(value, list):
        return " ".join(_clean(row.get("text") if isinstance(row, dict) else row) for row in value).strip()
    return _clean(value)


def speaking(shot: dict[str, Any]) -> bool:
    text = dialogue_text(shot)
    if not text:
        return False
    _name, sep, line = text.partition("：")
    return bool((line if sep else text).strip())


def speaker_id(shot: dict[str, Any]) -> str:
    role = _role(shot)
    return _clean(role.get("dialogue_speaker_id") or role.get("lip_owner_id"))


def listener_id(shot: dict[str, Any]) -> str:
    return _clean(_role(shot).get("dialogue_listener_id"))


def _text_of(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_text_of(v) for v in value.values()).strip()
    if isinstance(value, list):
        return " ".join(_text_of(v) for v in value).strip()
    return _clean(value)


def listener_reaction(shot: dict[str, Any]) -> str:
    action = _action(shot)
    return _text_of(action.get("listener_reaction_en") or action.get("listener_reaction"))


def lead_in_reaction(shot: dict[str, Any]) -> str:
    action = _action(shot)
    return _text_of(action.get("lead_in_reaction_en") or action.get("lead_in_reaction"))


def _offscreen(row: dict[str, Any], presence: dict[str, Any]) -> bool:
    cid = _clean(row.get("character_id") or row.get("character"))
    face = _clean(row.get("face_visibility")).upper()
    return face.startswith("OFFSCREEN") or "VOICE" in face or _clean(presence.get(cid)).upper().startswith("OFFSCREEN")


def visible_cast(shot: dict[str, Any]) -> list[str]:
    """Characters physically in frame (an OTS / back / soft-profile listener counts; an off-screen voice does not)."""
    presence = _role(shot).get("entity_presence") or {}
    out: list[str] = []
    for row in _spec(shot).get("cast") or []:
        if not isinstance(row, dict):
            continue
        cid = _clean(row.get("character_id") or row.get("character"))
        if cid and not _offscreen(row, presence if isinstance(presence, dict) else {}) and cid not in out:
            out.append(cid)
    return out


def _cast_row(shot: dict[str, Any], cid: str) -> dict[str, Any] | None:
    for row in _spec(shot).get("cast") or []:
        if isinstance(row, dict) and _clean(row.get("character_id") or row.get("character")) == cid:
            return row
    return None


def action_class(shot: dict[str, Any]) -> str:
    """SMALL_CONTINUOUS (may run while speaking) | LARGE (own shot) | NONE."""
    action = _action(shot)
    text = " ".join(_clean(action.get(k)) for k in ("primary_action", "business_en", "body_action")
                    if not isinstance(action.get(k), (dict, list)))
    if LARGE_ACTION.search(text):
        return "LARGE"
    if SMALL_ACTION.search(text):
        return "SMALL_CONTINUOUS"
    return "NONE"


def _hardest(shot: dict[str, Any]) -> bool:
    return bool(_spec(shot).get("hardest_line") or shot.get("hardest_line"))


def _object_first(shot: dict[str, Any]) -> bool:
    return bool(_spec(shot).get("object_first") or shot.get("object_first"))


def _camera_plan(shot: dict[str, Any]) -> dict[str, Any]:
    plan = _spec(shot).get("camera_plan")
    return plan if isinstance(plan, dict) else {}


def _locked(plan: dict[str, Any]) -> bool:
    return _clean(plan.get("motion_family") or "LOCKED").upper() in {"LOCKED", "STATIC"}


def is_push_in(plan: dict[str, Any] | None) -> bool:
    """A director-placed BILI_V1 slow push-in (renderer, S7 push-in compensation and the camera gates read it)."""
    return bool((plan or {}).get(PUSH_MARK))


def _scenes(shots: list[dict[str, Any]]) -> list[tuple[str, list[int]]]:
    order: list[str] = []
    rows: dict[str, list[int]] = {}
    for i, shot in enumerate(shots):
        sid = _clean(shot.get("scene_id")) or "SCENE"
        if sid not in rows:
            order.append(sid)
            rows[sid] = []
        rows[sid].append(i)
    return [(sid, rows[sid]) for sid in order]


def _name_of(contract: dict[str, Any], cid: str, shot: dict[str, Any]) -> str:
    role = _role(shot)
    if _clean(role.get("dialogue_listener_id")) == cid and _clean(role.get("dialogue_listener")):
        return _clean(role.get("dialogue_listener"))
    for row in contract.get("character_entities") or []:
        if isinstance(row, dict) and _clean(row.get("character_id") or row.get("entity_id")) == cid:
            return _clean(row.get("canonical_name") or row.get("name") or cid)
    return cid


# --------------------------------------------------------------------------- content guard
def _props(value: Any) -> Any:
    return value if isinstance(value, (list, dict)) else []


def content_fingerprint(contract: dict[str, Any]) -> str:
    """sha256 of what the director may never change: shot order, dialogue, action text, reaction text, props."""
    rows = []
    for shot in (contract or {}).get("shots") or []:
        if not isinstance(shot, dict):
            continue
        action = _action(shot)
        rows.append({
            "shot_id": _clean(shot.get("shot_id")),
            "dialogue": _spec(shot).get("dialogue", shot.get("dialogue")),
            "action": {k: action.get(k) for k in ("primary_action", "business_en", "body_action", "listener_reaction",
                                                  "listener_reaction_en", "lead_in_reaction", "lead_in_reaction_en")},
            "props": _props(_spec(shot).get("props")),
            "shot_props": _props(shot.get("props")),
        })
    payload = {"shots": rows, "props": _props((contract or {}).get("props"))}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def content_failures(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """INTEGRITY: ``DIRECTOR_CHANGED_CONTENT`` when L3 content differs (never admitted)."""
    return [] if content_fingerprint(before) == content_fingerprint(after) else ["DIRECTOR_CHANGED_CONTENT"]


# --------------------------------------------------------------------------- measurements (any profile)
def _reactor_acts(shot: dict[str, Any], reactor: str) -> bool:
    """An authored (screenplay) action line whose subject is the reacting character, who is in frame."""
    action = _action(shot)
    sources = action.get("field_sources") if isinstance(action.get("field_sources"), dict) else {}
    authored = _clean(sources.get("primary_action") or action.get("source")).lower() == "screenplay"
    if not authored or reactor not in visible_cast(shot):
        return False
    if _clean(action.get("subject_id") or action.get("initiator_entity_id")) == reactor:
        return True
    row = _cast_row(shot, reactor) or {}
    name = _clean(row.get("character"))
    return bool(name) and name != reactor and name in _clean(action.get("primary_action"))


def reaction_coverage(contract: dict[str, Any]) -> dict[str, Any]:
    """The owner's cheap reaction rule, measured.  ``uncovered``: trigger shots with no reaction (a/b/c);
    ``dedicated``: silent ``beat_role: REACTION`` shots; ``misplaced``: dedicated ones not after a
    REVEAL / TURN / ENDING beat and not part of the episode's last shots."""
    shots = [s for s in (contract or {}).get("shots") or [] if isinstance(s, dict)]
    floor = unit_min_seconds()
    short = floor <= 2  # 2 s units: a dedicated reaction may follow any trigger beat
    covered: dict[str, str] = {}
    uncovered: list[str] = []
    dedicated: list[str] = []
    misplaced: list[str] = []
    tail_from = len(shots)
    while tail_from > 0 and not speaking(shots[tail_from - 1]):
        tail_from -= 1
    for i, shot in enumerate(shots):
        sid = _clean(shot.get("shot_id")) or f"SHOT-{i + 1}"
        if beat_role(shot) == REACTION_ROLE and not speaking(shot):
            dedicated.append(sid)
            run_start = i
            while run_start > 0 and beat_role(shots[run_start - 1]) == REACTION_ROLE and not speaking(shots[run_start - 1]):
                run_start -= 1
            prev = beat_role(shots[run_start - 1]) if run_start else ""
            allowed = DEDICATED_ALLOWED_AFTER | (TRIGGER_ROLES if short else frozenset())
            if prev not in allowed and i < tail_from:
                misplaced.append(sid)
        if beat_role(shot) not in TRIGGER_ROLES:
            continue
        reactor = listener_id(shot)
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        if listener_reaction(shot) and len(visible_cast(shot)) >= 2:
            covered[sid] = "A_IN_FRAME"
        elif reactor and any(s is not None and _reactor_acts(s, reactor) for s in (shot, nxt)):
            covered[sid] = "A_IN_FRAME"    # the screenplay's own action line for the reactor (e.g. 他低低笑了一声)
        elif nxt is not None and listener_reaction(nxt) and len(visible_cast(nxt)) >= 2 and not speaking(nxt):
            covered[sid] = "A_IN_FRAME"
        elif (nxt is not None and speaking(nxt) and lead_in_reaction(nxt)
              and (not reactor or not speaker_id(nxt) or speaker_id(nxt) == reactor)):
            covered[sid] = "B_LEAD_IN"
        elif nxt is not None and speaking(nxt) and reactor and speaker_id(nxt) == reactor:
            covered[sid] = "B_NEXT_LINE"   # the reactor's own reply opens on his face (cheap rule b)
        elif nxt is not None and beat_role(nxt) == REACTION_ROLE and not speaking(nxt):
            covered[sid] = "C_DEDICATED"
        else:
            uncovered.append(sid)
    return {"triggers": len(covered) + len(uncovered), "covered": covered, "uncovered": uncovered,
            "dedicated": dedicated, "dedicated_count": len(dedicated), "dedicated_max": dedicated_reaction_max(floor),
            "misplaced_dedicated": misplaced}


def music_passages(contract: dict[str, Any]) -> dict[str, Any]:
    """Runs of ``beat_role: MUSIC_PASSAGE`` shots: at most one per episode, silent, <= 8 s."""
    shots = [s for s in (contract or {}).get("shots") or [] if isinstance(s, dict)]
    runs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for shot in shots:
        if beat_role(shot) == MUSIC_PASSAGE_ROLE:
            if current is None:
                current = {"shots": [], "seconds": 0.0, "spoken": []}
                runs.append(current)
            current["shots"].append(_clean(shot.get("shot_id")))
            current["seconds"] = round(current["seconds"] + _num(shot.get("target_seconds")), 3)
            if speaking(shot):
                current["spoken"].append(_clean(shot.get("shot_id")))
        else:
            current = None
    codes: list[str] = []
    if len(runs) > MUSIC_PASSAGES_MAX:
        codes.append(f"MUSIC_PASSAGES_OVER:{len(runs)}>{MUSIC_PASSAGES_MAX}")
    for run in runs:
        if run["seconds"] > MUSIC_PASSAGE_SECONDS_MAX + 1e-9:
            codes.append(f"MUSIC_PASSAGE_TOO_LONG:{run['shots'][0]}:{run['seconds']:g}>{MUSIC_PASSAGE_SECONDS_MAX:g}")
        for sid in run["spoken"]:
            codes.append(f"MUSIC_PASSAGE_HAS_DIALOGUE:{sid}")
    return {"runs": runs, "codes": codes}


def coverage_metrics(contract: dict[str, Any]) -> dict[str, Any]:
    shots = [s for s in (contract or {}).get("shots") or [] if isinstance(s, dict)]
    dialogue_s = sum(_num(s.get("target_seconds")) for s in shots if speaking(s))
    in_frame_s = sum(_num(s.get("target_seconds")) for s in shots if speaking(s) and len(visible_cast(s)) >= 2)
    pushes: dict[str, int] = {}
    for shot in shots:
        if is_push_in(_camera_plan(shot)):
            sid = _clean(shot.get("scene_id")) or "SCENE"
            pushes[sid] = pushes.get(sid, 0) + 1
    return {"dialogue_seconds": round(dialogue_s, 3),
            "listener_in_frame_seconds": round(in_frame_s, 3),
            "listener_in_frame_share": round(in_frame_s / dialogue_s, 3) if dialogue_s else 0.0,
            "listener_in_frame_target": LISTENER_IN_FRAME_TARGET,
            "push_ins_per_scene": pushes}


# --------------------------------------------------------------------------- the pass
def _apply_listener(contract: dict[str, Any], shot: dict[str, Any], scene_people: set[str],
                    applied: list[str]) -> str:
    """Speaker to camera, listener in frame from behind (OTS) -- the default dialogue coverage."""
    if not speaking(shot) or len(scene_people) < 2:
        return "SINGLE_PERSON_SCENE" if speaking(shot) else ""
    who, lid = speaker_id(shot), listener_id(shot)
    if not lid or lid == who or lid not in scene_people:
        return "NO_LISTENER_DECLARED"
    sid = _clean(shot.get("shot_id"))
    row = _cast_row(shot, lid)
    if row is not None:
        face = _clean(row.get("face_visibility")).upper()
        prior = _spec(shot).get("director") if isinstance(_spec(shot).get("director"), dict) else {}
        if face == OTS_LISTENER and prior.get("listener_framing") == OTS_LISTENER:
            return OTS_LISTENER              # this pass already framed it (idempotent)
        if face and face not in _FRONT_FACE:
            return f"WRITER_{face}"          # the writer chose the listener's framing (OTS, profile, bust): keep it
        row["face_visibility"] = OTS_LISTENER
        applied.append(f"LISTENER_OTS:{sid}:{lid}")
        return OTS_LISTENER
    others = [c for c in visible_cast(shot) if c not in (who, lid)]
    if others or len(visible_cast(shot)) >= 2:
        return "FRAME_FULL"                  # never a third subject (grouping MAX_VISIBLE_SUBJECTS = 2)
    spec = shot.setdefault("prompt_spec", {})
    spec.setdefault("cast", []).append({"character": _name_of(contract, lid, shot), "character_id": lid,
                                        "face_visibility": OTS_LISTENER, "director_added": True})
    role = spec.get("role_semantic_disambiguation")
    if isinstance(role, dict) and isinstance(role.get("entity_presence"), dict):
        role["entity_presence"].setdefault(lid, "VISIBLE_AND_IDENTITY_LOCKED")
    if isinstance(shot.get("visible_subject_ids"), list) and lid not in shot["visible_subject_ids"]:
        shot["visible_subject_ids"].append(lid)
    applied.append(f"LISTENER_OTS_ADDED:{sid}:{lid}")
    return OTS_LISTENER


def _apply_push(shot: dict[str, Any], applied: list[str]) -> bool:
    plan = _camera_plan(shot)
    if not plan or not _locked(plan):
        return False
    start = _clean(plan.get("start_framing")) or "The speaker framed for the line."
    end = _clean(plan.get("end_framing")) or start
    original = {k: plan.get(k) for k in ("motion_family", "motion_direction", "end_framing", "motivation")}
    plan.update({"motion_family": "DOLLY", "motion_direction": "PUSH_IN",
                 "end_framing": end if PUSH_END_SUFFIX in end else end + PUSH_END_SUFFIX,
                 "motivation": PUSH_MOTIVATION, PUSH_MARK: True})
    shot["camera"] = PUSH_MOTIVE_ZH
    director = shot["prompt_spec"].setdefault("director", {})
    director["push_in"] = {"original": original, "rule": "one slow push-in per scene, on the writer's hardest line"}
    applied.append(f"PUSH_IN:{_clean(shot.get('shot_id'))}")
    return True


#: camera setup fields a mirrored scene's first shot takes over (tools/speaking_unit_duration.SETUP_FIELDS minus the
#: motion, which stays the director's: locked, or the scene's one push-in)
MIRROR_FIELDS = ("shot_scale", "camera_height", "camera_side", "start_framing")


def ledger_hints(contract: dict[str, Any]) -> dict[str, Any] | None:
    """WP6 L4 hooks (craft_ledger.director_hints: object-first entrances, mirrored-scene setups, the zero-cost insert
    alternative), or None when that module is not deployed / fails -- the pass then reads the writer's own
    ``prompt_spec.object_first`` flags and skips mirrors."""
    try:
        import craft_ledger as _cl  # noqa: PLC0415 -- same directory (WP6, PR #329)
        hints = _cl.director_hints(contract)
    except Exception:  # noqa: BLE001 -- optional hook
        return None
    return hints if isinstance(hints, dict) else None


def _apply_mirror(shot: dict[str, Any], hint: dict[str, Any], applied: list[str]) -> bool:
    plan = _camera_plan(shot)
    fields = {k: hint[k] for k in MIRROR_FIELDS if hint.get(k) not in (None, "")}
    if not plan or not _locked(plan) or not fields or all(plan.get(k) == v for k, v in fields.items()):
        return False
    original = {k: plan.get(k) for k in fields}
    plan.update(fields)
    if "start_framing" in fields:
        plan["end_framing"] = fields["start_framing"]  # a locked plan keeps identical start / end framing
    shot["prompt_spec"].setdefault("director", {})["mirror_of"] = {"scene": hint.get("mirror_of"), "original": original}
    applied.append(f"MIRROR_SETUP:{_clean(shot.get('shot_id'))}:{hint.get('mirror_of')}")
    return True


def _transition_mode(shot: dict[str, Any]) -> str:
    return _clean(shot.get("incoming_transition_mode")).upper()


def _set_transition(shot: dict[str, Any], mode: str, reason: str) -> None:
    shot["incoming_transition_mode"] = mode
    for holder in (shot, _spec(shot)):
        block = holder.get("internal_transition_authoring")
        if isinstance(block, dict):
            block.update(transition_mode=mode, reason=reason)


def _apply_cuts(shots: list[dict[str, Any]], applied: list[str], advisories: list[str]) -> None:
    """Up to AUTHORED_CUT_MAX authored cuts / reverse angles per episode (minus the writer's own), on the speaking
    shots where the angle change is worth its keyframe: the turn first, then reveals, then payoffs / attacks.  Only a
    continuous shot that changes speaker inside a scene (a reverse angle) is cut; a scene's first shot already is."""
    existing = [i for i in range(1, len(shots)) if _transition_mode(shots[i]) in CUT_MODES
                and _clean(shots[i].get("scene_id")) == _clean(shots[i - 1].get("scene_id"))]
    budget = AUTHORED_CUT_MAX - len(existing)
    candidates = []
    for i in range(1, len(shots)):
        shot, prev = shots[i], shots[i - 1]
        role = beat_role(shot)
        if (role not in CUT_PRIORITY or not speaking(shot) or _transition_mode(shot) in CUT_MODES
                or _clean(shot.get("scene_id")) != _clean(prev.get("scene_id"))
                or (speaking(prev) and speaker_id(prev) == speaker_id(shot))):
            continue
        candidates.append((CUT_PRIORITY[role], i))
    if len(candidates) > max(0, budget):
        advisories.append(f"AUTHORED_CUTS_CAPPED:{len(candidates)}>{max(0, budget)}")
    for _rank, i in sorted(candidates)[:max(0, budget)]:
        shot = shots[i]
        mode = "MOTIVATED_CUT" if beat_role(shot) == "TURN" else "REACTION_CUT"
        _set_transition(shot, mode, f"director: reverse angle on the {beat_role(shot).lower()} line")
        shot.setdefault("prompt_spec", {}).setdefault("director", {})["authored_cut"] = {
            "mode": mode, "rule": f"<= {AUTHORED_CUT_MAX} per episode; each costs one start keyframe"}
        applied.append(f"AUTHORED_CUT:{_clean(shot.get('shot_id'))}:{mode}")


def _apply_short_units(shots: list[dict[str, Any]], applied: list[str]) -> None:
    """2 s H3 floor: a dedicated silent reaction / insert plays 1.5-2.5 s (ep3 rhythm) and is requested at 2 s."""
    for shot in shots:
        if beat_role(shot) not in SHORT_ROLES or speaking(shot):
            continue
        old = _num(shot.get("target_seconds"))
        new = old if SHORT_UNIT_RANGE[0] <= old <= SHORT_UNIT_RANGE[1] else SHORT_UNIT_SECONDS
        shot.setdefault("prompt_spec", {}).setdefault("director", {})["short_unit"] = {
            "seconds": new, "rule": "H3 floor <= 2 s: dedicated reaction / insert units run 1.5-2.5 s"}
        if new != old:
            shot["target_seconds"] = new
            applied.append(f"SHORT_UNIT:{_clean(shot.get('shot_id'))}:{old:g}->{new:g}")


def direct(contract: dict[str, Any], *, force: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """(directed contract, report).  LEGACY (and ``force`` False) -> the input object itself, untouched."""
    if not isinstance(contract, dict):
        return contract, {"schema": SCHEMA, "status": "NO_CONTRACT"}
    if not force and not _cp.is_bili_v1(contract):
        return contract, {"schema": SCHEMA, "status": "NOT_APPLICABLE", "profile": _cp.profile_of(contract)}
    before = content_fingerprint(contract)
    out = copy.deepcopy(contract)
    shots = [s for s in out.get("shots") or [] if isinstance(s, dict)]
    applied: list[str] = []
    advisories: list[str] = []
    hints = ledger_hints(out)
    hinted_move: set[str] = set()
    if hints is not None:
        by_shot = {_clean(s.get("shot_id")): s for s in shots}
        for row in hints.get("object_first") or []:
            target = by_shot.get(_clean(row.get("shot_id")))
            if target is None:
                continue
            target.setdefault("prompt_spec", {}).setdefault("director", {})["object_first"] = {
                k: row.get(k) for k in ("subject", "of", "then", "counts_as_scene_move")}
            if row.get("counts_as_scene_move"):
                hinted_move.add(_clean(target.get("scene_id")) or "SCENE")
    mirrors = (hints or {}).get("mirror_setups") or {}
    for scene_id, idx in _scenes(shots):
        people: set[str] = set()  # who is physically in this scene: seen in frame in at least one of its shots
        for i in idx:
            people |= set(visible_cast(shots[i]))
        # one move per scene: an object-first entrance or a writer-authored move already is it
        if isinstance(mirrors.get(scene_id), dict):
            _apply_mirror(shots[idx[0]], mirrors[scene_id], applied)
        object_move = (scene_id in hinted_move) if hints is not None else any(_object_first(shots[i]) for i in idx)
        moved = object_move or any(not _locked(_camera_plan(shots[i])) and _camera_plan(shots[i]) for i in idx)
        marked = [i for i in idx if _hardest(shots[i]) and speaking(shots[i])]
        if len(marked) > 1:
            advisories.append(f"PUSH_IN_EXTRA_MARK:{scene_id}:{len(marked)}")
        target = marked[:1] or [i for i in idx if beat_role(shots[i]) == "TURN" and speaking(shots[i])][:1]
        already = any(is_push_in(_camera_plan(shots[i])) for i in idx)
        if not already:
            # a push-in the writer / screenplay compiler already authored on a line is the scene's one push: mark it
            # so S7 lock-off / push-in compensation never stabilise it away
            authored_push = [i for i in idx if speaking(shots[i]) and _camera_plan(shots[i]).get("motion_family")
                             == "DOLLY" and _camera_plan(shots[i]).get("motion_direction") == "PUSH_IN"]
            if authored_push:
                _camera_plan(shots[authored_push[0]])[PUSH_MARK] = True
                applied.append(f"PUSH_IN_ADOPTED:{_clean(shots[authored_push[0]].get('shot_id'))}")
                already = True
        for i in idx:
            shot = shots[i]
            spec = shot.setdefault("prompt_spec", {})
            decided: dict[str, Any] = {}
            framing = _apply_listener(out, shot, people, applied)
            if framing:
                decided["listener_framing"] = framing
            if speaking(shot):
                klass = action_class(shot)
                decided["speaking_action"] = klass
                if klass == "LARGE":
                    advisories.append(f"LARGE_ACTION_WHILE_SPEAKING:{_clean(shot.get('shot_id'))}")
                if lead_in_reaction(shot):
                    prior = spec.get("director") if isinstance(spec.get("director"), dict) else {}
                    if not prior.get("lead_in_seconds_added"):
                        old = _num(shot.get("target_seconds"))
                        cap = TWO_PERSON_UNIT_MAX_SECONDS if len(visible_cast(shot)) >= 2 else UNIT_HARD_MAX_SECONDS
                        new = round(min(cap, max(float(unit_min_seconds()), old + LEAD_IN_SECONDS)), 3)
                        if new > old:
                            shot["target_seconds"] = new
                            decided["lead_in_seconds_added"] = round(new - old, 3)
                            applied.append(f"LEAD_IN_SECONDS:{_clean(shot.get('shot_id'))}:+{new - old:g}")
                    else:
                        decided["lead_in_seconds_added"] = prior["lead_in_seconds_added"]
            if decided:
                spec["director"] = {**(spec.get("director") if isinstance(spec.get("director"), dict) else {}),
                                    **decided}
        if target and not moved and not already:
            _apply_push(shots[target[0]], applied)
        elif len(idx) >= 3 and not marked and not moved and not already:
            advisories.append(f"PUSH_IN_UNMARKED:{scene_id}")
    _apply_cuts(shots, applied, advisories)
    if unit_min_seconds() <= 2:
        _apply_short_units(shots, applied)
    reactions = reaction_coverage(out)
    music = music_passages(out)
    advisories += [f"DEDICATED_REACTION_MISPLACED:{sid}" for sid in reactions["misplaced_dedicated"]]
    advisories += music["codes"]
    if hints is not None:
        inserts = [_clean(s.get("shot_id")) for s in shots if beat_role(s) == "INSERT"]
        cap = int(hints["insert_max"]) if isinstance(hints.get("insert_max"), int) else 3
        if len(inserts) > cap:
            advisories.append(f"INSERT_ALTERNATIVE:{len(inserts)}>{cap}:"
                              f"{hints.get('insert_alternative_en')}")
    metrics = coverage_metrics(out)
    if metrics["dialogue_seconds"] and metrics["listener_in_frame_share"] < LISTENER_IN_FRAME_TARGET:
        advisories.append(f"LISTENER_IN_FRAME_LOW:{metrics['listener_in_frame_share']:.2f}<{LISTENER_IN_FRAME_TARGET:.2f}")
    after = content_fingerprint(out)
    integrity = [] if before == after else ["DIRECTOR_CHANGED_CONTENT"]
    report = {"schema": SCHEMA, "version": VERSION, "profile": PROFILE,
              "status": "FAIL" if integrity else "PASS", "integrity_failures": integrity,
              "content_sha256": after, "content_sha256_before": before,
              "applied": applied, "advisories": advisories,
              "reactions": reactions, "music_passages": music["runs"], "metrics": metrics}
    if integrity:
        return contract, report
    if _cp.from_contract(out) is None:
        out["craft_profile"] = PROFILE  # contract-only readers (gates, S7 metrics) then see the series' profile
    out["director_pass"] = {k: report[k] for k in ("schema", "version", "profile", "content_sha256", "applied",
                                                   "advisories", "metrics")}
    return out, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("contract", type=Path)
    ap.add_argument("--write", action="store_true", help="write the directed contract back (keeps .pre_director)")
    ap.add_argument("--force", action="store_true", help="direct even when the contract is not BILI_V1 (lab)")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(argv)
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    directed, report = direct(contract, force=args.force)
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.write and directed is not contract and report.get("status") == "PASS":
        backup = args.contract.with_name(args.contract.stem + ".pre_director.json")
        if not backup.exists():
            backup.write_bytes(args.contract.read_bytes())
        args.contract.write_text(json.dumps(directed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("status", "applied", "advisories", "metrics")}, ensure_ascii=False))
    return 1 if report.get("status") == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
