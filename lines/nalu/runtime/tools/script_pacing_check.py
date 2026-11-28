#!/usr/bin/env python3
"""SHORT_DRAMA_PACING_V1 -- free, deterministic script pacing check + bounded writer revision loop.

Line owner 2026-11-22: 「剧情推进太慢。Codex 需要对原著进行改写和删减；现在一集基本就是人物在念台词，一点都不刺激。」
Final reviews kept flagging weak opening hooks, static talking shots, endings without suspense and pacing 2-3/5,
and a typical dispatch adapted ONE chapter into a ~115-120 s episode (every source beat landed, nearly all of it as
dialogue).  The craft standard v1 (lines/nalu/standards/NALU_CRAFT_STANDARD_v1.md S-01..S-10) already says how a
vertical short drama should move; nothing measured the script against it before money was spent.

This module measures the authored generation contract (``qingshan.generation_contract.v3``; shot timeline =
cumulative ``target_seconds``) -- no model, no network, no paid call:

  beats_per_minute         plot turns (``pacing.beat_sheet`` rows + shots with ``prompt_spec.beat_role: PAYOFF``)
  first_conflict_at        min(``pacing.hook.at_seconds``, first turn)              target <= 3 s
  max_turn_gap_seconds     largest gap between 0, the turns and the cliffhanger    target <= 30 s
  dialogue_only_ratio      seconds of TALKING-HEAD shots / episode seconds                             <= 0.60
  visual_action_ratio      seconds of shots that show something other than a speaking face (action, insert,
                           establishing, transition, a moving silent shot, a line spoken while grabbing / shoving /
                           handing over ...) / episode seconds                                          >= 0.30
  visual_beat_count        silent visual beats (action / insert / establishing / transition / movement)
                                                                                  >= max(3, ceil(D / 30))
  visual variety           MOTIVATED scene changes + in-place variety (movement / action / insert / establishing
                           shots, reaction action, new arrivals, blocking changes)          >= max(4, ceil(D / 24))
  scene changes            each change of location must be motivated: a time change, or a shown transition /
                           arrival / travel beat, or a new set of participants (a new event).  A continuing
                           conversation (overlapping speakers, no time skip, no transition) stays in ONE place and
                           ONE scene_id (CONVERSATION_SPLIT_ACROSS_LOCATIONS); two consecutive scene_ids in the same
                           place without a time skip are one scene (SCENE_SPLIT_SAME_LOCATION).  JA-01 E08 on device
                           1485 (2026-11-22): the "scenes per 2 minutes" target of the first version made the writer
                           relocate one three-person conversation council hall -> market -> courtyard, and every
                           speaker's shots had a different background.  Unmotivated changes never count.
  longest_line             sentences and spoken units of the longest line (<= 2 sentences, language cap)
  monologue runs           one speaker's back-to-back lines > 12 s without an interjection or action
  scenes_without_action    scenes where no shot shows a physical action (talk-only scenes)
  scene_plan               ``pacing.scene_plan`` {scene_id, objective, conflict, physical_action} per scene (the
                           top-level ``pacing_scene_plan`` / ``pacing_<key>`` spelling is accepted too)

The visual numbers are MEASURED from the storyboard (each shot's dialogue, blocking / primary action text, camera
motion family, shot scale, cast and props), never from the writer's own ``state_delta_dimensions`` labels (JA-01 E07
on device 1485, 2026-11-22: every speaking shot was labelled MOMENTUM/CONTACT, dialogue_only_ratio measured 0.00 and
the owner saw "almost everything is characters talking, the scene barely changes, no other action shots").
  ending                   ``pacing.cliffhanger`` {shot_id, open_question} on the last beat of the episode
  adaptation               ``adaptation_plan`` {source_chapters, plot_events[], cut[]}: the episode's source
                           budget is plot events, not chapters (>= the required turn count)

Activation: SHORT_DRAMA_PACING_V1 is the DEFAULT policy of every contract (2026-11-22, E07: the contract carried no
``pacing_policy`` key, the check stayed ADVISORY and SCRIPT_PACING_REVISE never fired).  A contract opts out only
explicitly (``"pacing_policy": "OFF"`` / ``"NONE"`` / ``"LEGACY"``).  An episode already past a paid stage (S4+ in
its pipeline state) whose contract does not declare the policy is grandfathered (ADVISORY): a re-run of S1 never
sends a paid episode back to the writer.  ``NALU_SCRIPT_PACING=off`` turns the revision request off everywhere
(metrics are still recorded).

Revision loop (``decide``): a failing check asks the writer (Codex) to revise the script; each distinct failing
contract sha is one round.  Rounds 1..MAX_REVISIONS return REVISE (S1 reports ``SCRIPT_PACING_REVISE:*`` and the
writer revises its own layers and reruns S1, free); after MAX_REVISIONS failed revisions the script is ADMITTED with
the remaining gaps recorded -- the loop always terminates, never needs a human and never stops the line.

Source coverage (``record_coverage`` / ``coverage``): the chapters each episode adapted are kept in
``$NALU_RUNTIME_ROOT/series/SOURCE_COVERAGE.json`` so the next dispatch continues where the series really is.

Stdlib only (codex_production and the final review load it too).  Language-agnostic (zh / en / ja / ko via
lang_profile) and genre-agnostic (the turn types are structural, not genre words).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import lang_profile as _lang  # noqa: E402

SCHEMA = "nalu.script_pacing_check.v1"
POLICY = "SHORT_DRAMA_PACING_V1"
ENV_SWITCH = "NALU_SCRIPT_PACING"
MAX_REVISIONS = 2
STALL_EVALUATIONS = 3
ROUNDS_SCHEMA = "nalu.script_pacing_rounds.v1"
COVERAGE_SCHEMA = "nalu.source_coverage.v1"

#: structural turn types (genre-agnostic): what flips power, information or danger in front of the viewer
TURN_TYPES = ("HUMILIATION_PAYBACK", "IDENTITY_REVEAL", "POWER_SHIFT", "SECRET_REVEALED", "THREAT_ESCALATION",
              "CONFRONTATION", "ROMANTIC_SPIKE", "REVERSAL", "DISCOVERY")
#: state changes a viewer SEES (POSTURE alone -- sitting up, turning a head -- is not an action beat)
PHYSICAL_DIMENSIONS = frozenset({"MOMENTUM", "CONTACT", "POSSESSION", "POSITION", "INTEGRITY"})
#: a SPEAKING shot carries action only when something is struck, grabbed, handed over, broken or rushed -- a step
#: closer (POSITION) or a turn of the head (POSTURE) while talking is still a talking head
SPEAKING_ACTION_DIMENSIONS = frozenset({"MOMENTUM", "CONTACT", "POSSESSION", "INTEGRITY"})

TARGETS = {
    "first_conflict_max_seconds": 3.0,
    "turn_every_seconds": 25.0,          # required turns = max(MIN_TURNS, floor(D / 25)) (craft S-02)
    "min_turns": 4,
    "max_turn_gap_seconds": 30.0,
    "dialogue_only_ratio_max": 0.60,
    "max_sentences_per_line": 2,
    "monologue_run_max_seconds": 12.0,
    "cliffhanger_window_seconds": 8.0,   # the cliffhanger shot starts inside the last 8 s (or is the last shot)
    "visual_action_ratio_min": 0.30,     # >= 30 % of screen time shows action / non-talking visual storytelling
    "visual_beat_every_seconds": 30.0,   # silent visual beats >= max(MIN, ceil(D / 30))
    "min_visual_beats": 3,
    # visual variety (replaces "scenes per 2 minutes", JA-01 E08): motivated scene changes + in-place variety events
    "visual_variety_every_seconds": 24.0,
    "min_visual_variety": 4,
}
#: a person entering the scene (an arrival is in-place variety)
_ENTER_WORDS = re.compile(r"\b(?:enter(?:s|ed)?|arriv(?:es|ed|ing)|walks? in|steps? in|comes? in|bursts? in)\b"
                          r"|走进|进来|进门|赶到|赶来|闯进|闯入|入って|現れ|들어오|나타나", re.IGNORECASE)
#: shot kinds that add visual variety inside one location (reaction action, movement, inserts, establishing views)
VARIETY_KINDS = frozenset({"ACTION", "MOVEMENT", "INSERT", "ESTABLISHING", "TRANSITION", "TALK_WITH_ACTION"})
#: a shown change of place / time: the new scene opens on (or the old one ends with) one of these silent shots
TRANSITION_KINDS = frozenset({"TRANSITION", "ESTABLISHING", "MOVEMENT", "ACTION"})
TRANSITION_ROLES = frozenset({"TRANSITION", "ARRIVAL", "TRAVEL", "TIME_SKIP", "ESTABLISHING", "EXIT", "ENTRANCE"})

# --------------------------------------------------------------------------- storyboard (visual) classification
#: a line spoken WHILE one of these happens is not a talking head (grab / shove / strike / hand over / break / run
#: ...); a step, a turn of the head, a raised arm or a lean is still a talking head.  zh / ja share the Han verbs.
STRONG_ACTION_WORDS = (
    # zh
    "抓", "夺", "抢", "推搡", "推倒", "推开", "猛推", "一把推", "撞", "扇", "掌掴", "打了", "打向", "击", "踢", "踹", "砸",
    "摔", "扔", "甩开", "甩手", "拽", "拉住", "扯", "撕", "掐", "揪", "按住", "扑", "冲向", "冲进", "冲出", "冲上",
    "奔", "跑", "逃", "追", "跪", "抱住", "拥抱", "吻", "拔出", "拔刀", "拔剑", "刺", "砍", "挥拳", "挥刀", "挥剑",
    "递", "接过", "塞给", "塞进", "掏出", "夺过", "举起", "倒下", "跌倒", "摔倒", "翻倒", "掀", "破门", "摔门", "撞门",
    "关上门", "拦住", "挡住", "泼", "泼向", "砸碎", "打碎", "撕碎", "扔下", "丢下", "拖走", "拖着", "架住", "勒住",
    "掐住", "捂住", "捏碎", "扼", "摁", "拍桌", "掀桌", "踩", "跳", "翻身", "爬",
    # ja (kana / kanji forms not covered above)
    "掴", "つかむ", "つかみ", "押し倒", "突き飛ば", "殴", "叩", "蹴", "投げ", "駆け", "走り", "逃げ", "抱きし", "抱き寄",
    "倒れ", "奪", "渡す", "手渡", "破り", "引っ張", "振り払", "斬", "切りつけ", "飛びかか",
    # ko
    "붙잡", "움켜", "밀치", "밀어", "때리", "뺨을", "걷어차", "던지", "달려", "뛰어", "도망", "끌어안", "무릎을 꿇",
    "넘어지", "빼앗", "건네", "찢", "부수", "내리치", "휘두르",
)
_STRONG_EN = re.compile(
    r"\b(grab|grabs|grabbed|seize|seizes|seized|snatch|snatches|snatched|shove|shoves|shoved|push(?:es|ed)? (?:him|her|them|"
    r"it|away|past|open)|punch(?:es|ed)?|slap(?:s|ped)?|strike|strikes|struck|hit|hits|kick(?:s|ed)?|throw(?:s|n)?|threw|"
    r"hurl(?:s|ed)?|smash(?:es|ed)?|break(?:s)?|broke|tear(?:s)?|tore|rip(?:s|ped)?|run(?:s)?|ran|rush(?:es|ed)?|"
    r"chase(?:s|d)?|flee(?:s)?|fled|kneel(?:s)?|knelt|hug(?:s|ged)?|embrace(?:s|d)?|kiss(?:es|ed)?|draws? (?:a|the|his|"
    r"her) (?:sword|knife|gun|blade)|hand(?:s|ed)? (?:over|him|her|them)|yank(?:s|ed)?|drag(?:s|ged)?|slam(?:s|med)?|"
    r"collapse(?:s|d)?|stab(?:s|bed)?|lunge(?:s|d)?|burst(?:s)? (?:in|into|through)|tackle(?:s|d)?|"
    r"pin(?:s|ned)? (?:him|her|them)|fall(?:s)?|fell|jump(?:s|ed)?|climb(?:s|ed)?)\b", re.IGNORECASE)
#: craft_profile BILI_V1 only (WP3, line owner 2026-11-23): the small, specific business of a screenplay's action
#: lines is visual action too (E25 妖皇宫: 磕令牌, 亮出令牌, 按下他的手, 拍手背).  LEGACY keeps the list above.
BILI_ACTION_WORDS = (
    # zh
    "磕", "亮出", "亮到", "按下", "按住", "拍", "敲", "戳", "弹", "捏", "掰", "攥", "握紧", "搓", "揉", "擦", "抹",
    "翻开", "合上", "撕开", "点燃", "倒酒", "倒茶", "端起", "举到", "拿起", "放下", "搁下", "丢给", "抛", "接住",
    "起身", "站起", "坐下", "转身", "走下", "走向", "走到", "凑近", "俯身", "后退", "退后", "转着", "抽出", "收起",
    # ja
    "叩", "押さえ", "置く", "置い", "持ち上げ", "差し出", "立ち上が", "座り", "振り向", "掲げ", "握りしめ", "撫で",
    # ko
    "두드리", "내려놓", "집어", "들어올리", "내밀", "일어서", "일어나", "앉", "돌아서", "쥐", "쓰다듬", "누르",
)
_BILI_ACTION_EN = re.compile(
    r"\b(tap(?:s|ped)?|knock(?:s|ed)?|rap(?:s|ped)?|press(?:es|ed)? (?:down|it|his|her)|pat(?:s|ted)?|flick(?:s|ed)?|"
    r"rub(?:s|bed)?|wipe(?:s|d)?|set(?:s)? (?:it |the \w+ )?down|put(?:s)? (?:it |the \w+ )?down|pick(?:s|ed)? up|"
    r"raise(?:s|d)?|lift(?:s|ed)?|hold(?:s)? (?:up|out)|turn(?:s|ed)? (?:the|a|his|her)|stand(?:s)? up|stood up|"
    r"sit(?:s)? down|sat down|lean(?:s|ed)? (?:in|over|forward)|step(?:s|ped)? (?:back|forward|down)|pour(?:s|ed)?|"
    r"light(?:s)? (?:a|the)|flip(?:s|ped)?|fold(?:s|ed)?|unfold(?:s|ed)?)\b", re.IGNORECASE)
_TOUCH_MODES = frozenset({"CONTACT", "HANDOVER", "HAND_OVER", "TOUCH", "GRAB", "PUSH", "PULL", "STRIKE"})
#: camera words inside an action text are not an action ("镜头推近" is not a shove)
_CAMERA_WORDS = re.compile(r"镜头[^，。；,;]*|推近|推镜|拉远|拉镜|推进|拉开距离|push[- ]in|pull[- ]out|dolly", re.IGNORECASE)
#: a moving camera family gives a SILENT shot visual motion (PUSH_IN / LOCKED do not -- static_design_gate R7)
MOVING_CAMERA = frozenset({"ARC", "TRACK", "CRANE", "HANDHELD", "ORBIT", "PAN", "TILT", "DOLLY", "FOLLOW", "WHIP_PAN",
                           "STEADICAM"})
WIDE_SCALES = frozenset({"WIDE", "EXTREME_WIDE", "ESTABLISHING", "FULL", "LONG", "EXTREME_LONG", "MASTER"})
INSERT_SCALES = frozenset({"INSERT", "EXTREME_CLOSE", "EXTREME_CLOSE_UP", "ECU", "DETAIL", "MACRO"})
#: shot kinds counted as action / non-talking visual storytelling (screen time share and beats)
VISUAL_KINDS = frozenset({"ACTION", "MOVEMENT", "INSERT", "ESTABLISHING", "TRANSITION", "TALK_WITH_ACTION"})
SILENT_VISUAL_KINDS = frozenset({"ACTION", "MOVEMENT", "INSERT", "ESTABLISHING", "TRANSITION"})
#: kinds that put a physical action on screen (a scene without one is talk-only)
PHYSICAL_KINDS = frozenset({"ACTION", "TALK_WITH_ACTION"})


def _body_verbs() -> tuple[str, ...]:
    try:
        import nalu_prompt_rules as _npr  # noqa: PLC0415 -- same directory; the static design gate's lexicon
        return tuple(_npr.BODY_VERBS)
    except Exception:  # noqa: BLE001 -- the lexicon is optional
        return ()


_BODY_VERBS: tuple[str, ...] | None = None


def action_text(shot: dict[str, Any]) -> str:
    """The storyboard's description of what physically happens in the shot (blocking / primary action / frame
    content), camera wording removed."""
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    act = spec.get("action") if isinstance(spec.get("action"), dict) else {}
    parts = [shot.get("blocking"), act.get("primary_action"), act.get("secondary_action"),
             shot.get("action") if isinstance(shot.get("action"), str) else None]
    if not any(_clean(x) for x in parts):
        parts.append(shot.get("frame_content"))
    return _CAMERA_WORDS.sub(" ", " ".join(_clean(x) for x in parts if _clean(x)))


def strong_action(text: str) -> bool:
    return bool(text) and (any(w in text for w in STRONG_ACTION_WORDS) or bool(_STRONG_EN.search(text)))


def body_motion(text: str) -> bool:
    global _BODY_VERBS
    if _BODY_VERBS is None:
        _BODY_VERBS = _body_verbs()
    return bool(text) and any(v in text for v in _BODY_VERBS)


def _camera(shot: dict[str, Any]) -> tuple[str, str]:
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    plan = spec.get("camera_plan") if isinstance(spec.get("camera_plan"), dict) else \
        shot.get("camera_plan") if isinstance(shot.get("camera_plan"), dict) else {}
    family = _clean(plan.get("motion_family")).upper()
    scale = _clean(plan.get("shot_scale") or shot.get("shot_size")).upper()
    return family, scale


def bili_visual_speaking(shot: dict[str, Any], text: str) -> bool:
    """BILI_V1: a spoken line is not a talking head when the shot carries an authored action line (screenplay source,
    or a verb of the wider BILI lexicon), a prop in use, a touch between two people, or an in-frame listener's
    reaction (owner 2026-11-23: reactions inside two-person frames)."""
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    act = spec.get("action") if isinstance(spec.get("action"), dict) else {}
    sources = act.get("field_sources") if isinstance(act.get("field_sources"), dict) else {}
    authored = _clean(sources.get("primary_action") or act.get("source")).lower() == "screenplay"
    if text and (authored or any(w in text for w in BILI_ACTION_WORDS) or _BILI_ACTION_EN.search(text)):
        return True
    if [x for x in spec.get("props") or [] if x]:
        return True
    target, subject = _clean(act.get("target_entity_id")), _clean(act.get("subject_id") or act.get("initiator_entity_id"))
    if _clean(act.get("interaction_mode")).upper() in _TOUCH_MODES and target and target != subject:
        return True
    visible = [c for c in spec.get("cast") or [] if isinstance(c, dict)
               and not _clean(c.get("face_visibility")).upper().startswith("OFFSCREEN")]
    return bool(act.get("listener_reaction_en") or act.get("listener_reaction")) and len(visible) >= 2


def shot_kind(shot: dict[str, Any], speaking: bool, bili: bool = False) -> str:
    """What the viewer SEES in one storyboard shot -- from its structure, never from its state labels:

    TALKING_HEAD       a line is spoken and nothing but the speaking (gesturing / stepping) characters is shown
    TALK_WITH_ACTION   a line is spoken while something is grabbed, struck, handed over, broken, run from ...
    ACTION             no line; a body action happens (strong verb, or the static gate's body-level motion verbs)
    MOVEMENT           no line; the camera itself travels (ARC / TRACK / CRANE / HANDHELD ...)
    INSERT             no line; a close detail of a prop / object (insert scale, or props without cast)
    ESTABLISHING       no line; a wide view of the place, or a shot without characters
    TRANSITION         a declared transition shot (beat_role / shot_function TRANSITION)
    STATIC_REACTION    no line, locked camera, a face reacting without a body action"""
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    text = action_text(shot)
    family, scale = _camera(shot)
    if speaking:
        if bili and not strong_action(text):
            return "TALK_WITH_ACTION" if bili_visual_speaking(shot, text) else "TALKING_HEAD"
        return "TALK_WITH_ACTION" if strong_action(text) else "TALKING_HEAD"
    role = _clean(spec.get("beat_role") or shot.get("shot_function") or spec.get("shot_function")).upper()
    if role == "TRANSITION":
        return "TRANSITION"
    cast = [c for c in spec.get("cast") or [] if isinstance(c, dict)]
    props = [x for x in spec.get("props") or [] if x]
    if not cast:
        return "INSERT" if props and scale not in WIDE_SCALES else "ESTABLISHING"
    if scale in INSERT_SCALES and props:
        return "INSERT"
    if strong_action(text) or body_motion(text):
        return "ACTION"
    if family in MOVING_CAMERA:
        return "MOVEMENT"
    if scale in WIDE_SCALES:
        return "ESTABLISHING"
    return "STATIC_REACTION"


def _location(shot: dict[str, Any], scene_row: dict[str, Any] | None = None) -> tuple[str, str]:
    """(location, time) of one shot: the shot's own declaration, else its scene's ``scene_states`` row (the
    generation contract keeps the location on the scene, ``shot_scene_overrides`` aside)."""
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    space = spec.get("space") if isinstance(spec.get("space"), dict) else {}
    state = spec.get("scene_state") if isinstance(spec.get("scene_state"), dict) else {}
    scene_row = scene_row or {}
    return (_clean(space.get("location") or shot.get("location_id") or shot.get("location")
                   or scene_row.get("location_id") or scene_row.get("location")),
            _clean(state.get("time") or shot.get("time_of_day") or scene_row.get("time_id") or scene_row.get("time")))

_SENTENCE_END = re.compile(r"[。！？!?…]+|\.(?:\s+|$)")
_OPEN_END = re.compile(r"[？?…—―-]\s*[」』\"'”’]?\s*$")


# --------------------------------------------------------------------------- helpers
def _clean(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def enabled(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return _clean(env.get(ENV_SWITCH)).lower() not in ("off", "0", "false", "no")


#: explicit opt-out values of ``pacing_policy`` (anything else, or no key at all, is SHORT_DRAMA_PACING_V1)
OPT_OUT_VALUES = frozenset({"OFF", "NONE", "LEGACY", "OPT_OUT", "DISABLED", "FALSE", "0"})


def policy_basis(contract: dict[str, Any]) -> str:
    """DECLARED (the contract names the policy), OPT_OUT (it explicitly switched it off) or DEFAULT (no key)."""
    raw = (contract or {}).get("pacing_policy")
    if raw is False:
        return "OPT_OUT"
    value = _clean(raw).upper()
    if not value:
        return "DEFAULT"
    if value in OPT_OUT_VALUES:
        return "OPT_OUT"
    return "DECLARED" if value == POLICY else "DEFAULT"


def policy_active(contract: dict[str, Any], *, in_flight: bool = False) -> bool:
    """The policy applies to the contract: declared, or by default -- except an explicit opt-out, and except a
    contract that relies on the default while its episode is already past a paid stage (``in_flight``)."""
    basis = policy_basis(contract)
    if basis == "OPT_OUT":
        return False
    return basis == "DECLARED" or not in_flight


def pacing_block(contract: dict[str, Any]) -> dict[str, Any]:
    """``pacing`` with the top-level ``pacing_<key>`` spellings folded in (E07: Codex wrote ``pacing_scene_plan`` at
    the contract top level next to ``pacing.hook`` / ``pacing.beat_sheet``; the check read only ``pacing.scene_plan``
    and reported SCENE_PLAN_MISSING for every scene).  A key inside ``pacing`` wins; list keys are merged."""
    contract = contract if isinstance(contract, dict) else {}
    pacing = dict(contract.get("pacing")) if isinstance(contract.get("pacing"), dict) else {}
    for key in ("hook", "beat_sheet", "scene_plan", "cliffhanger"):
        alias = contract.get(f"pacing_{key}")
        if alias in (None, "", [], {}):
            continue
        if isinstance(alias, list) and isinstance(pacing.get(key), list):
            seen = {json.dumps(x, ensure_ascii=False, sort_keys=True) for x in pacing[key]}
            pacing[key] = list(pacing[key]) + [x for x in alias
                                               if json.dumps(x, ensure_ascii=False, sort_keys=True) not in seen]
        elif pacing.get(key) in (None, "", [], {}):
            pacing[key] = alias
    return pacing


def contract_language(contract: dict[str, Any], language: str | None = None) -> str:
    return (_lang.language_code(language) or _lang.language_code((contract or {}).get("dialogue_language"))
            or _lang.DEFAULT_LANGUAGE)


def _rows(dialogue: Any) -> list[str]:
    if isinstance(dialogue, (list, tuple)):
        rows = [str(x.get("text") if isinstance(x, dict) else x) for x in dialogue]
    else:
        rows = str(dialogue or "").splitlines()
    return [r.strip() for r in rows if str(r).strip()]


def split_line(row: str, language: str) -> tuple[str, str]:
    """``Speaker：words`` -> (speaker, words); a label is at most 24 characters (romanised names included)."""
    for sep in ("：", ":"):
        at = row.find(sep)
        if 0 <= at < 24:
            return row[:at].strip(), row[at + 1:].strip()
    return "", row.strip()


def sentence_count(words: str) -> int:
    parts = [p for p in _SENTENCE_END.split(words) if re.search(r"\w", p)]
    return max(1, len(parts)) if words.strip() else 0


def line_unit_cap(language: str) -> int:
    """Two craft-standard lines (S-08) of the language: zh 28 chars / en 20 words / ja 44 chars / ko 36 syllables."""
    return 2 * int(_lang.profile(language).line_units[1])


# --------------------------------------------------------------------------- timeline
def timeline(contract: dict[str, Any], language: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    bili = _bili_v1(contract or {})  # BILI_V1: authored business counts as visual action (WP3)
    cursor = 0.0
    scene_rows = {_clean(r.get("scene_id")): r for r in (contract or {}).get("scene_states") or []
                  if isinstance(r, dict) and _clean(r.get("scene_id"))}
    overrides = (contract or {}).get("shot_scene_overrides") if isinstance(
        (contract or {}).get("shot_scene_overrides"), dict) else {}
    for index, shot in enumerate((contract or {}).get("shots") or []):
        if not isinstance(shot, dict):
            continue
        seconds = max(_num(shot.get("target_seconds")) or 0.0, 0.0)
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        role = spec.get("role_semantic_disambiguation") if isinstance(spec.get("role_semantic_disambiguation"),
                                                                       dict) else {}
        lines = []
        for row in _rows(spec.get("dialogue") if spec.get("dialogue") not in (None, "", []) else shot.get("dialogue")):
            speaker, words = split_line(row, language)
            units = _lang.speech_units(words, language)
            if units:
                lines.append({"speaker": speaker, "units": units, "sentences": sentence_count(words),
                              "open_end": bool(_OPEN_END.search(words))})
        dims = {_clean(d).upper() for d in shot.get("state_delta_dimensions") or []}
        speaker = _clean(role.get("dialogue_speaker_id")) or (lines[0]["speaker"] if lines else "")
        kind = shot_kind(shot, bool(lines), bili) if bili else shot_kind(shot, bool(lines))
        scene_row = dict(scene_rows.get(_clean(shot.get("scene_id"))) or {})
        override = overrides.get(_clean(shot.get("shot_id"))) if isinstance(
            overrides.get(_clean(shot.get("shot_id"))), dict) else {}
        scene_row.update({k: v for k, v in override.items() if k in ("location_id", "time_id") and v})
        location, time_of_day = _location(shot, scene_row)
        out.append({"index": index, "shot_id": _clean(shot.get("shot_id")) or f"SHOT-{index + 1}",
                    "scene_id": _clean(shot.get("scene_id")) or "SCENE", "start": round(cursor, 3),
                    "end": round(cursor + seconds, 3), "seconds": seconds, "lines": lines,
                    "speaker": speaker if lines else "", "kind": kind,
                    "location": location, "time_of_day": time_of_day,
                    "cross_cut": bool(override.get("location_id")),
                    "cast": sorted({_clean(c.get("character_id") or c.get("character")) for c in spec.get("cast") or []
                                    if isinstance(c, dict) and _clean(c.get("character_id") or c.get("character"))
                                    and _clean(c.get("face_visibility")).upper() != "OFFSCREEN_VOICE_ONLY"}),
                    "enters": bool(_ENTER_WORDS.search(action_text(shot))),
                    "subspace": _clean((spec.get("space") or {}).get("subspace") if isinstance(spec.get("space"), dict)
                                       else "") or _clean(shot.get("subspace_id") or shot.get("zone_id")),
                    # measured from the storyboard (shot_kind), not from the writer's state labels
                    "physical": kind in PHYSICAL_KINDS,
                    "speaking_action": kind == "TALK_WITH_ACTION",
                    # the writer's own labels, kept only to show how far they drift from the storyboard
                    "declared_physical": bool(dims & PHYSICAL_DIMENSIONS),
                    "declared_speaking_action": bool(dims & SPEAKING_ACTION_DIMENSIONS),
                    "beat_role": _clean(spec.get("beat_role")).upper()})
        cursor += seconds
    return out


def _at(ref: Any, rows: list[dict[str, Any]]) -> float | None:
    """Seconds of a beat reference: ``shot_id`` (start of that shot) or ``at_seconds``."""
    if isinstance(ref, dict):
        sid = _clean(ref.get("shot_id") or ref.get("line_or_shot_id"))
        if sid:
            hit = next((r for r in rows if r["shot_id"] == sid), None)
            if hit is not None:
                return hit["start"]
        return _num(ref.get("at_seconds"))
    return None


# --------------------------------------------------------------------------- remote calls (deep review 1205 E15)
#: a shot that stages a phone / video call: the device at the ear, the call answered / ended, the voice on the line
_REMOTE_CALL = re.compile(
    r"phone (?:to|at) (?:his|her|their|my|the) ear|(?:on|over) the (?:phone|line)|answers? the (?:phone|call)"
    r"|hangs? up|ends? the call|video[- ]call|facetime|phone call|the call\b|calls? (?:him|her|them) back"
    r"|电话|通话|视频通话|挂断|電話|通話|전화|통화", re.I)


def remote_call_one_place(contract: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    """Scenes that stage a phone / video call (2+ shots say so) with two or more speakers, every speaking shot in ONE
    location and no ``shot_scene_overrides`` cross-cut: the far caller is rendered sitting in the same room (1205 E15:
    father and daughter both "seated at the meeting table" of the refuge room, the phone visible in 2 of 17 shots).
    A call is one conversation in two places: the far side's shots carry their own location as a cross-cut."""
    by_index = {i: s for i, s in enumerate((contract or {}).get("shots") or []) if isinstance(s, dict)}
    out: list[str] = []
    scenes: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        scenes.setdefault(r["scene_id"], []).append(r)
    for scene_id, rs in scenes.items():
        calls = 0
        for r in rs:
            shot = by_index.get(r["index"]) or {}
            text = " ".join([action_text(shot), _clean(shot.get("frame_content")), _clean(shot.get("entry_state"))])
            calls += bool(_REMOTE_CALL.search(text))
        speaking = [r for r in rs if r["lines"]]
        places = {r["location"] for r in speaking if r["location"]}
        if (calls >= 2 and len(_speakers(speaking)) >= 2 and len(places) == 1
                and not any(r["cross_cut"] for r in rs)):
            out.append(scene_id)
    return out


# --------------------------------------------------------------------------- scene changes (JA-01 E08)
def _speakers(rows: list[dict[str, Any]]) -> set[str]:
    return {_clean(ln.get("speaker")) for r in rows for ln in r["lines"] if _clean(ln.get("speaker"))} | {
        _clean(r.get("speaker")) for r in rows if _clean(r.get("speaker"))}


def _shown_transition(prev_rows: list[dict[str, Any]], rows: list[dict[str, Any]]) -> bool:
    """The change of place is SHOWN: the new scene opens on a silent transition / establishing / arrival / movement
    shot (or a declared transition / arrival role), or the old scene ends on a silent exit / movement shot."""
    head = rows[:2]
    if any(r["beat_role"] in TRANSITION_ROLES for r in head):
        return True
    if rows and not rows[0]["lines"] and rows[0]["kind"] in TRANSITION_KINDS:
        return True
    tail = prev_rows[-1] if prev_rows else None
    return bool(tail and not tail["lines"] and (tail["kind"] in ("TRANSITION", "MOVEMENT", "ACTION")
                                                or tail["beat_role"] in TRANSITION_ROLES))


#: how many speaking shots on each side of a scene boundary decide "the same conversation goes on"
BOUNDARY_SPEAKING_SHOTS = 4
#: ``pacing.scene_plan[].change_reason`` values that declare a time jump told by a line or a caption (craft S-04)
TIME_SKIP_REASONS = frozenset({"TIME_SKIP", "TIME_JUMP", "LATER"})


def continuing_conversation(prev_rows: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[str]:
    """The speakers who carry one conversation across the boundary: the last speaking shots of the old scene and the
    first of the new one share two or more speakers (or the very same single speaker on both sides).  One shared
    person is not a continuing conversation (craft S-04: she is thrown out, hard cut, she already sits at the rival's
    desk -- a new event with a new partner)."""
    tail = [r for r in prev_rows if r["lines"]][-BOUNDARY_SPEAKING_SHOTS:]
    head = [r for r in rows if r["lines"]][:BOUNDARY_SPEAKING_SHOTS]
    a, b = _speakers(tail), _speakers(head)
    shared = sorted(a & b)
    if len(shared) >= 2 or (shared and a == b):
        return shared
    return []


def scene_changes(rows: list[dict[str, Any]], scene_plan: dict[str, dict[str, Any]] | None = None
                  ) -> list[dict[str, Any]]:
    """Every boundary between consecutive scene_ids, classified:

    MOTIVATED_TIME_CHANGE      the scene's time changes (scene_states time), or the writer declares a time jump
                               told by a line / caption (``pacing.scene_plan[].change_reason: TIME_SKIP``, craft S-04)
    MOTIVATED_SHOWN            a new place opened by a shown transition / arrival / establishing beat
    MOTIVATED_NEW_EVENT        a new place and no conversation carried over the cut (:func:`continuing_conversation`)
    CONVERSATION_SPLIT         a new place, the same people still talking, no time skip, nothing shown -- one
                               continuing conversation relocated (E08: council hall -> market -> courtyard)
    SAME_PLACE_SPLIT           the same place and time under a new scene_id: one scene split in two (E08 S01/S02)
    Cross-cut shots (``shot_scene_overrides``) belong to their scene; a scene's place is its first shot's."""
    scenes: list[tuple[str, list[dict[str, Any]]]] = []
    for r in rows:
        if scenes and scenes[-1][0] == r["scene_id"]:
            scenes[-1][1].append(r)
        else:
            scenes.append((r["scene_id"], [r]))
    out: list[dict[str, Any]] = []
    for (prev_id, prev_rows), (scene_id, cur_rows) in zip(scenes, scenes[1:]):
        if prev_id == scene_id:
            continue
        place = lambda rs: next((x["location"] for x in rs if x["location"] and not x["cross_cut"]), "")  # noqa: E731
        when = lambda rs: next((x["time_of_day"] for x in rs if x["time_of_day"]), "")  # noqa: E731
        a_loc, b_loc, a_time, b_time = place(prev_rows), place(cur_rows), when(prev_rows), when(cur_rows)
        overlap = continuing_conversation(prev_rows, cur_rows)
        shown = _shown_transition(prev_rows, cur_rows)
        plan_row = (scene_plan or {}).get(scene_id) or {}
        declared_skip = (_clean(plan_row.get("change_reason")).upper() in TIME_SKIP_REASONS
                         or plan_row.get("time_skip") is True)
        time_change = bool(a_time and b_time and a_time != b_time) or declared_skip
        if time_change:
            kind = "MOTIVATED_TIME_CHANGE"
        elif not a_loc or not b_loc:
            kind = "UNKNOWN_LOCATION"
        elif a_loc == b_loc:
            kind = "SAME_PLACE_SPLIT"
        elif shown:
            kind = "MOTIVATED_SHOWN"
        elif not overlap:
            kind = "MOTIVATED_NEW_EVENT"
        else:
            kind = "CONVERSATION_SPLIT"
        out.append({"from_scene": prev_id, "to_scene": scene_id, "from_location": a_loc, "to_location": b_loc,
                    "at": cur_rows[0]["start"], "kind": kind, "motivated": kind.startswith("MOTIVATED"),
                    "shared_speakers": overlap[:6], "shown_transition": shown, "time_change": time_change})
    return out


def in_place_variety(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Visual variety that needs no new location: movement / action / insert / establishing / transition shots and
    lines spoken with action (reaction action), new arrivals (someone enters an ongoing scene) and blocking changes
    (the shot moves to another subspace of the same place)."""
    shots = sum(1 for r in rows if r["kind"] in VARIETY_KINDS)
    arrivals = blocking = 0
    seen: dict[str, set[str]] = {}
    last_subspace: dict[str, str] = {}
    for r in rows:
        cast = set(r.get("cast") or [])
        if r["scene_id"] in seen:
            # someone visibly ENTERS an ongoing scene (a reverse shot of a person who was there all along is not one)
            if cast - seen[r["scene_id"]] and (r["beat_role"] in ("ARRIVAL", "ENTRANCE") or r.get("enters")):
                arrivals += len(cast - seen[r["scene_id"]])
            seen[r["scene_id"]] |= cast
        else:
            seen[r["scene_id"]] = set(cast)
        sub = r.get("subspace") or ""
        if sub and last_subspace.get(r["scene_id"]) not in (None, sub):
            blocking += 1
        if sub:
            last_subspace[r["scene_id"]] = sub
    return {"variety_shots": shots, "arrivals": arrivals, "blocking_changes": blocking}


# --------------------------------------------------------------------------- placeholder acting (JA-01 E08)
#: per-shot performance text the writer authors; a template copied onto every line is not direction
PERFORMANCE_TEXT_FIELDS = (("shot", "entry_state"), ("shot", "completion_state"), ("action", "primary_action"),
                           ("action", "start_state"), ("action", "completion_state"), ("action", "contact_point"),
                           ("action", "force_feedback"),
                           # E24 (device 1101, 2026-11-23): the framing / ambience / transition text of every shot was
                           # one series template ("<Name> alone, centered with a full face visible ... in the declared
                           # location", "Bamboo wind and field insects", "Continue or reveal the declared beat").
                           # Like entry/exit states these legitimately repeat inside one take, so here they are only
                           # checked for generic placeholders; the cross-scene copy is boilerplate_failures' job.
                           ("camera_plan", "start_framing"), ("camera_plan", "end_framing"),
                           ("camera_plan", "motivation"), ("sound", "ambience"), ("transition", "reason"),
                           ("transition", "transition_execution"))
#: fields whose text is the action itself (a repeat is a template); every other field is checked for generic text only
_ACTION_TEXT_KEYS = frozenset({"primary_action", "contact_point", "force_feedback"})


def _field_source(shot: dict[str, Any], spec: dict[str, Any], where: str) -> dict[str, Any]:
    if where == "shot":
        return shot
    if where == "transition":
        value = spec.get("internal_transition_authoring") or spec.get("transition") or \
            shot.get("internal_transition_authoring")
    else:
        value = spec.get(where)
    return value if isinstance(value, dict) else {}


def _performance_variety():
    try:
        import performance_variety as _pv  # noqa: PLC0415 -- repo tools/ (on the engine path)
        return _pv
    except Exception:  # noqa: BLE001
        pass
    try:
        root_tools = str(_HERE.parents[3] / "tools")
        if root_tools not in sys.path:
            sys.path.append(root_tools)
        import performance_variety as _pv  # noqa: PLC0415
        return _pv
    except Exception:  # noqa: BLE001 -- the check is optional when the module is absent
        return None


def _screenplay_checks():
    try:
        import screenplay_checks as _sc  # noqa: PLC0415 -- same directory
        return _sc
    except Exception:  # noqa: BLE001
        return None


def _screenplay_v1(contract: dict[str, Any]) -> bool:
    """BILI_V1 + writer_format SCREENPLAY_V1 declared by the contract (CHANGE_SPEC WP2); LEGACY is always False."""
    sc = _screenplay_checks()
    return bool(sc and sc.active(contract) and sc.screenplay(contract))


def screenplay_checks_row(contract: dict[str, Any]) -> dict[str, Any]:
    """WP2 anti-template v2 (screenplay_checks.evaluate) for a BILI_V1 contract; {} otherwise.  Never raises."""
    sc = _screenplay_checks()
    try:
        if sc is None or not sc.active(contract):
            return {}
        files = sc.generator_scripts(_clean((contract or {}).get("episode"))) if sc.screenplay(contract) else []
        return sc.evaluate(contract, generator_files=files)
    except Exception:  # noqa: BLE001 -- a measurement never breaks S1
        return {}


def placeholder_acting(contract: dict[str, Any]) -> list[str]:
    """Speaking-shot performance text that is a template (the same sentence, names masked, on 3+ lines) or a generic
    gesture placeholder.  JA-01 E08: every line was "<Name> delivers the line with a clear anime gesture and visible
    posture change", entry "standing facing the immediate conflict", exit "gesture settles while the conflict remains
    visible" -- H3 rendered one raised index finger for all of them."""
    if _screenplay_v1(contract):
        return []  # SCREENPLAY_V1 (WP2): superseded by screenplay_checks ACTION_TEXT_TEMPLATE (similarity, not phrases)
    pv = _performance_variety()
    if pv is None:
        return []
    names: set[str] = set()
    for row in (contract or {}).get("character_entities") or []:
        if isinstance(row, dict):
            names |= {_clean(row.get(k)) for k in ("canonical_name", "english_name", "character_id", "name")}
    texts: list[str] = []
    states: list[str] = []   # entry / exit states legitimately chain (shot n's exit = shot n+1's entry): generic only
    lang = contract_language(contract)
    for shot in (contract or {}).get("shots") or []:
        if not isinstance(shot, dict):
            continue
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        dialogue = spec.get("dialogue") if spec.get("dialogue") not in (None, "", []) else shot.get("dialogue")
        rows = _rows(dialogue)
        if not rows:
            continue
        names |= {split_line(r, lang)[0] for r in rows}
        for where, key in PERFORMANCE_TEXT_FIELDS:
            value = _clean(_field_source(shot, spec, where).get(key))
            if value:
                (texts if key in _ACTION_TEXT_KEYS else states).append(value)
    found = pv.placeholder_beat_texts(texts, names - {""})
    found += [t for t in pv.placeholder_beat_texts(states, names - {""}, minimum=10 ** 6) if t not in found]
    return found[:6]


# --------------------------------------------------------------------------- measure
def measure(contract: dict[str, Any], language: str | None = None) -> dict[str, Any]:
    """Every pacing number of the authored script.  Pure, never raises on odd input (missing parts -> None)."""
    contract = contract if isinstance(contract, dict) else {}
    lang = contract_language(contract, language)
    rows = timeline(contract, lang)
    duration = round(sum(r["seconds"] for r in rows), 3)
    pacing = pacing_block(contract)

    turns: list[dict[str, Any]] = []
    unknown_types: list[str] = []
    for entry in pacing.get("beat_sheet") or []:
        if not isinstance(entry, dict):
            continue
        at = _at(entry, rows)
        kind = _clean(entry.get("type")).upper()
        if at is None:
            continue
        if kind not in TURN_TYPES:
            unknown_types.append(kind or "EMPTY")
            continue
        turns.append({"at": round(at, 3), "type": kind, "shot_id": _clean(entry.get("shot_id")) or None,
                      "source": "beat_sheet"})
    declared_shots = {t["shot_id"] for t in turns if t["shot_id"]}
    for r in rows:
        if r["beat_role"] == "PAYOFF" and r["shot_id"] not in declared_shots:
            turns.append({"at": r["start"], "type": "PAYOFF", "shot_id": r["shot_id"], "source": "beat_role"})
    turns.sort(key=lambda t: t["at"])

    hook = pacing.get("hook") if isinstance(pacing.get("hook"), dict) else {}
    hook_at = _num(hook.get("at_seconds"))
    first_turn = turns[0]["at"] if turns else None
    first_conflict = min([v for v in (hook_at, first_turn) if v is not None], default=None)

    cliff = pacing.get("cliffhanger") if isinstance(pacing.get("cliffhanger"), dict) else {}
    cliff_at = _at(cliff, rows) if cliff else None
    last = rows[-1] if rows else None
    cliff_shot = next((r for r in rows if r["shot_id"] == _clean(cliff.get("shot_id"))), None) if cliff else None
    window = TARGETS["cliffhanger_window_seconds"]
    in_window = bool(cliff_shot is not None and (cliff_shot is last or cliff_shot["start"] >= duration - window))
    question = _clean(cliff.get("open_question"))
    last_line = next((ln for r in reversed(rows) for ln in reversed(r["lines"])), None)
    ending = {"declared": bool(cliff), "shot_id": cliff_shot["shot_id"] if cliff_shot else None,
              "at": cliff_at, "in_final_window": in_window, "open_question": bool(question),
              "last_line_open": bool(last_line and last_line["open_end"])}
    ending["unresolved"] = bool((in_window and question) or (not cliff and ending["last_line_open"]))
    ending["basis"] = "declared" if cliff else ("last_line" if ending["last_line_open"] else "none")

    points = [0.0] + [t["at"] for t in turns] + [cliff_at if (cliff_at is not None and in_window) else duration]
    points = sorted(p for p in points if p is not None)
    gaps = [round(b - a, 3) for a, b in zip(points, points[1:])]
    max_gap = max(gaps, default=duration)
    gap_at = None
    if gaps:
        i = gaps.index(max_gap)
        gap_at = [round(points[i], 3), round(points[i + 1], 3)]

    speaking = [r for r in rows if r["lines"]]
    talk_only = [r for r in speaking if not r["speaking_action"]]
    dialogue_only_seconds = round(sum(r["seconds"] for r in talk_only), 3)
    declared_talk_only = round(sum(r["seconds"] for r in speaking if not r["declared_speaking_action"]), 3)
    kinds: dict[str, dict[str, float]] = {}
    for r in rows:
        k = kinds.setdefault(r["kind"], {"shots": 0, "seconds": 0.0})
        k["shots"] += 1
        k["seconds"] = round(k["seconds"] + r["seconds"], 3)
    visual_seconds = round(sum(r["seconds"] for r in rows if r["kind"] in VISUAL_KINDS), 3)
    visual_beats = [{"shot_id": r["shot_id"], "kind": r["kind"], "at": r["start"]} for r in rows
                    if r["kind"] in SILENT_VISUAL_KINDS]
    required_visual_beats = max(TARGETS["min_visual_beats"],
                                math.ceil(duration / TARGETS["visual_beat_every_seconds"])) if duration else \
        TARGETS["min_visual_beats"]
    locations = sorted({r["location"] for r in rows if r["location"]})
    times_of_day = sorted({r["time_of_day"] for r in rows if r["time_of_day"]})
    speech_seconds = round(sum(min(r["seconds"], sum(ln["units"] for ln in r["lines"]) /
                                   _lang.profile(lang).rate) for r in speaking), 3)

    cap = line_unit_cap(lang)
    longest = None
    long_lines: list[dict[str, Any]] = []
    for r in rows:
        for ln in r["lines"]:
            if longest is None or ln["units"] > longest["units"]:
                longest = {"shot_id": r["shot_id"], "units": ln["units"], "sentences": ln["sentences"]}
            if ln["sentences"] > TARGETS["max_sentences_per_line"] or ln["units"] > cap:
                long_lines.append({"shot_id": r["shot_id"], "units": ln["units"], "sentences": ln["sentences"]})

    runs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for r in rows:
        if r["lines"] and r["speaker"] and not r["speaking_action"] and cur and cur["speaker"] == r["speaker"]:
            cur["seconds"] = round(cur["seconds"] + r["seconds"], 3)
            cur["shots"].append(r["shot_id"])
            continue
        if cur:
            runs.append(cur)
        cur = ({"speaker": r["speaker"], "start": r["start"], "seconds": r["seconds"],
                "shots": [r["shot_id"]]} if r["lines"] and r["speaker"] and not r["speaking_action"] else None)
    if cur:
        runs.append(cur)
    monologues = [{"start": x["start"], "seconds": x["seconds"], "shots": x["shots"]} for x in runs
                  if x["seconds"] > TARGETS["monologue_run_max_seconds"]]

    scenes: dict[str, dict[str, Any]] = {}
    for r in rows:
        s = scenes.setdefault(r["scene_id"], {"scene_id": r["scene_id"], "start": r["start"], "seconds": 0.0,
                                              "physical": False, "shots": 0})
        s["seconds"] = round(s["seconds"] + r["seconds"], 3)
        s["physical"] = s["physical"] or r["physical"]
        s["shots"] += 1
    plan_rows = {(_clean(p.get("scene_id"))): p for p in pacing.get("scene_plan") or [] if isinstance(p, dict)}
    plan_missing = []
    for sid in scenes:
        p = plan_rows.get(sid) or {}
        lacking = [k for k in ("objective", "conflict", "physical_action") if not _clean(p.get(k))]
        if lacking:
            plan_missing.append({"scene_id": sid, "missing": lacking})

    adaptation = contract.get("adaptation_plan") if isinstance(contract.get("adaptation_plan"), dict) else {}
    chapters = sorted({int(c) for c in adaptation.get("source_chapters") or []
                       if _num(c) is not None and float(c) >= 0})
    events = [e for e in adaptation.get("plot_events") or [] if (isinstance(e, dict) and _clean(
        e.get("event") or e.get("summary"))) or (isinstance(e, str) and e.strip())]

    required = max(TARGETS["min_turns"], int(duration // TARGETS["turn_every_seconds"])) if duration else \
        TARGETS["min_turns"]
    changes = scene_changes(rows, {_clean(p.get("scene_id")): p for p in pacing.get("scene_plan") or []
                                   if isinstance(p, dict)})
    motivated = [c for c in changes if c["motivated"]]
    variety = in_place_variety(rows)
    variety_count = len(motivated) + sum(variety.values())
    required_variety = max(TARGETS["min_visual_variety"],
                           math.ceil(duration / TARGETS["visual_variety_every_seconds"])) if duration else \
        TARGETS["min_visual_variety"]
    return {
        "language": lang, "duration_seconds": duration, "shot_count": len(rows), "scene_count": len(scenes),
        "turns": turns, "turn_count": len(turns), "required_turns": required,
        "beats_per_minute": round(len(turns) * 60.0 / duration, 2) if duration else 0.0,
        "unknown_turn_types": unknown_types,
        "hook_at_seconds": hook_at, "first_conflict_at": first_conflict,
        "max_turn_gap_seconds": round(max_gap, 3), "max_turn_gap_window": gap_at,
        "dialogue_only_seconds": dialogue_only_seconds,
        "dialogue_only_ratio": round(dialogue_only_seconds / duration, 3) if duration else 0.0,
        "dialogue_only_ratio_declared": round(declared_talk_only / duration, 3) if duration else 0.0,
        "talking_head_ratio": round(dialogue_only_seconds / duration, 3) if duration else 0.0,
        "visual_action_seconds": visual_seconds,
        "visual_action_ratio": round(visual_seconds / duration, 3) if duration else 0.0,
        "visual_beat_count": len(visual_beats), "required_visual_beats": required_visual_beats,
        "visual_beats": visual_beats[:16], "shot_kinds": kinds,
        "location_count": len(locations) if locations else None, "locations": locations[:8],
        "time_change": len(times_of_day) > 1,
        "scenes_per_2min": round(len(scenes) * 120.0 / duration, 2) if duration else 0.0,
        "scene_changes": changes[:24], "motivated_scene_changes": len(motivated),
        "motivated_scene_changes_per_2min": round(len(motivated) * 120.0 / duration, 2) if duration else 0.0,
        "conversation_splits": [f"{c['from_scene']}>{c['to_scene']}" for c in changes
                                if c["kind"] == "CONVERSATION_SPLIT"],
        "same_place_splits": [f"{c['from_scene']}>{c['to_scene']}" for c in changes if c["kind"] == "SAME_PLACE_SPLIT"],
        # only present when a call is staged in one place: legacy reports stay byte-identical
        **({"remote_call_one_place": calls_one_place} if (calls_one_place := remote_call_one_place(contract, rows))
           else {}),
        "in_place_variety": variety, "visual_variety_count": variety_count,
        "placeholder_acting": placeholder_acting(contract),
        "required_visual_variety": required_variety,
        "speech_share_ref": round(speech_seconds / duration, 3) if duration else 0.0,
        "longest_line": longest, "line_unit_cap": cap, "long_lines": long_lines[:12],
        "long_line_count": len(long_lines), "monologue_runs": monologues[:8],
        "scenes_without_action": [s["scene_id"] for s in scenes.values() if not s["physical"]],
        "scene_plan_missing": plan_missing,
        "ending": ending,
        "adaptation": {"declared": bool(adaptation), "source_chapters": chapters,
                       "source_chapter_count": len(chapters), "plot_event_count": len(events),
                       "cut_count": len([c for c in adaptation.get("cut") or [] if c])},
    }


# --------------------------------------------------------------------------- S1 integrity (E24, never admitted)
#: switch for the integrity part of this check (boilerplate, a location contradicted by the action); the taste loop
#: keeps its own switch.  Integrity failures are never ADMITTED_AFTER_REVISIONS: they go back to the writer until the
#: S1 integrity round cap (nalu_pipeline.S1_INTEGRITY_MAX_ROUNDS) blocks the episode with a named code.
INTEGRITY_SWITCH = "NALU_SCRIPT_INTEGRITY"
INTEGRITY_CODES = frozenset({"BOILERPLATE_TEXT", "BOILERPLATE_PHRASE", "SCENE_SPLIT_LOCATION_CONTRADICTS_ACTION",
                             "SCENE_NOT_CONTIGUOUS"})
#: transition modes that legitimately return to an earlier scene (cross-cutting / flashback)
INTERCUT_MODES = frozenset({"INTERCUT", "CROSS_CUT", "CROSSCUT", "FLASHBACK", "PARALLEL_CUT"})
BOILERPLATE_SHARE = 0.5          # the same text on more than half of the shots ...
BOILERPLATE_MIN_SCENES = 3       # ... spread over at least three scenes is a series template, not a scene's own text
BOILERPLATE_MIN_CHARS = 12
#: per-shot fields the writer must write per scene -- (where, key).  BLOCKING: the ambience (what is heard THERE).
#: ADVISORY (warnings only): framing, axis, camera motivation, transition reason -- accepted lab scripts (holmes,
#: huayuan, urban 2026-10/11) legitimately keep one episode-level axis rule or one locked-single framing template, so
#: a repeat there is not by itself proof that the scene was never written.
BOILERPLATE_SHOT_FIELDS = (("sound", "ambience"),
                           # deep review 1485 E09 (JA anime line, 2026-11-23): one action / state template on all 38
                           # shots of five scenes -- "<Name> grabs the desk or clenches a fist while delivering the
                           # line", entry "the immediate conflict is already active", exit "the speaker finishes the
                           # gesture as the threat escalates", body "one distinct gesture driven by the conflict".
                           # H3 rendered one stock gesture (raised index finger) for all of them; the per-line
                           # PERFORMANCE_PLACEHOLDER taste check was admitted after two rounds.  What a shot DOES is
                           # never a legitimate series template, so its copy across scenes is integrity.
                           # (entry_state stays advisory: accepted lab scripts open every shot on one neutral pose,
                           # "<Name> is visible with both arms lowered before the action begins")
                           ("action", "primary_action"), ("shot", "blocking"), ("shot", "completion_state"),
                           ("performance", "body_action"),
                           ("performance", "business_en"))
BOILERPLATE_ADVISORY_SHOT_FIELDS = (("camera_plan", "start_framing"), ("camera_plan", "end_framing"),
                                    ("camera_plan", "motivation"), ("shot", "axis"), ("shot", "camera"),
                                    ("transition", "reason"), ("shot", "entry_state"))
#: per-scene rows (scene_states ambient text): advisory; pacing.scene_plan objective / conflict / action: blocking
BOILERPLATE_SCENE_FIELDS = (("ambient_life", "motion_trend"), ("ambient_life", "first_frame_state"),
                            ("ambient_life", "reaction_progression"))
#: template sentences seen on fleet scripts (device 1101 E18 / E24); any of them on two or more shots is boilerplate
KNOWN_BOILERPLATE_PHRASES = (
    "the declared subject", "a declared subject", "in the declared location", "the declared beat is complete",
    "continue the declared action", "continue or reveal the declared beat", "continue or cut as authored",
    "the declared starting position", "the declared posture", "hut-to-field axis", "bamboo wind and field insects",
    "keep the conflict readable", "hold the readable conflict", "the listener reacts visibly",
    "no unregistered prop handoff", "locked readable framing", "推进调查并制造可见冲突", "嫌疑人或证据阻碍调查",
    "抓、夺、定身、捆绑或人群逼近",
    # 1485 E09 (JA anime): the per-shot action / state template
    "grabs the desk or clenches a fist", "the immediate conflict is already active",
    "the speaker finishes the gesture", "one distinct gesture driven by the conflict",
    "makes one clear anime gesture", "delivers the line with a clear anime gesture")
_NAME_RUN = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*")


def integrity_enabled(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(INTEGRITY_SWITCH) or "").strip().lower() not in ("off", "0", "false", "no")


def _names(contract: dict[str, Any]) -> list[str]:
    out: set[str] = set()
    for row in (contract or {}).get("character_entities") or []:
        if isinstance(row, dict):
            out |= {_clean(row.get(k)) for k in ("canonical_name", "english_name", "name_en", "character_id")}
            out |= {_clean(a) for a in row.get("aliases") or []}
    return sorted((n for n in out if len(n) >= 2), key=len, reverse=True)


def _norm_template(text: Any, names: list[str]) -> str:
    value = _clean(text)
    for name in names:
        value = value.replace(name, "<N>")
    value = _NAME_RUN.sub("<N>", value)
    return re.sub(r"[\s\W_]+", " ", value.lower(), flags=re.UNICODE).strip()


def boilerplate_failures(contract: dict[str, Any], *, advisory: bool = False) -> list[str]:
    """Series boilerplate in the fields the writer must write per scene (E24: one framing / ambience / axis / scene
    plan sentence on every shot of five scenes that the story set in a teahouse, a shop, a fishing boat and a street).
    A field's text (names masked) repeated on > BOILERPLATE_SHARE of the shots AND over >= BOILERPLATE_MIN_SCENES
    scenes, a scene_plan / scene_states text shared by most scenes, or a known template phrase on 2+ shots."""
    contract = contract if isinstance(contract, dict) else {}
    shots = [s for s in contract.get("shots") or [] if isinstance(s, dict)]
    if len(shots) < 4:
        return []
    names = _names(contract)
    failures: list[str] = []
    for where, key in (BOILERPLATE_ADVISORY_SHOT_FIELDS if advisory else BOILERPLATE_SHOT_FIELDS):
        rows: dict[str, list[str]] = {}
        for shot in shots:
            spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
            src = _field_source(shot, spec, where)
            if where == "camera_plan" and not src and isinstance(shot.get("camera_plan"), dict):
                src = shot["camera_plan"]
            text = _norm_template(src.get(key), names)
            if len(text) >= BOILERPLATE_MIN_CHARS:
                rows.setdefault(text, []).append(_clean(shot.get("scene_id")))
        for text, scenes in rows.items():
            if len(scenes) > BOILERPLATE_SHARE * len(shots) and len(set(scenes)) >= BOILERPLATE_MIN_SCENES:
                failures.append(f"BOILERPLATE_TEXT:{key}:{len(scenes)}/{len(shots)}")
    scene_rows = [r for r in contract.get("scene_states") or [] if isinstance(r, dict)]
    plan = pacing_block(contract).get("scene_plan") or []
    plan_rows = [r for r in plan if isinstance(r, dict)]
    if advisory:
        groups = [(f"scene_states.{a}.{k}", [(r.get(a) or {}).get(k) if isinstance(r.get(a), dict) else None
                                             for r in scene_rows]) for a, k in BOILERPLATE_SCENE_FIELDS]
    else:
        groups = [(f"scene_plan.{k}", [r.get(k) for r in plan_rows])
                  for k in ("objective", "conflict", "physical_action")]
    for label, values in groups:
        texts = [_norm_template(v, names) for v in values]
        texts = [t for t in texts if len(t) >= 6]
        if len(values) < BOILERPLATE_MIN_SCENES or not texts:
            continue
        text, n = max(((t, texts.count(t)) for t in set(texts)), key=lambda x: x[1])
        if n >= BOILERPLATE_MIN_SCENES and n > BOILERPLATE_SHARE * len(values):
            failures.append(f"BOILERPLATE_TEXT:{label}:{n}/{len(values)}")
    if advisory or _screenplay_v1(contract):
        # SCREENPLAY_V1 (WP2): the phrase blacklist is superseded by screenplay_checks (distinctness / similarity)
        return failures[:12]
    hits: dict[str, int] = {}
    for shot in shots:
        blob = json.dumps(shot, ensure_ascii=False).lower()
        for phrase in KNOWN_BOILERPLATE_PHRASES:
            if phrase.lower() in blob:
                hits[phrase] = hits.get(phrase, 0) + 1
    blob = json.dumps({"scene_states": scene_rows, "scene_plan": plan_rows}, ensure_ascii=False).lower()
    for phrase in KNOWN_BOILERPLATE_PHRASES:
        if phrase.lower() in blob:
            hits[phrase] = hits.get(phrase, 0) + blob.count(phrase.lower())
    for phrase, n in sorted(hits.items(), key=lambda x: -x[1]):
        if n >= 2:
            failures.append(f"BOILERPLATE_PHRASE:{phrase}:{n}")
    return failures[:12]


#: place classes an action sentence can put a scene in; a scene whose location does not mention the class while its
#: action is "on a fishing boat" / "into the street" is not where its location field says (E24: every scene was
#: LOC-ANCHENG-TEAHOUSE)
PLACE_CLASSES = {
    "BOAT": (("boat", "ship", "raft", "barge", "deck", "ferry", "sampan", "canoe"), ("船", "舟", "筏", "甲板", "渡口"),
             ("chuan", "zhou", "boat", "ship", "ferry", "dock")),
    "STREET": (("street", "alley", "market", "marketplace", "road", "lane", "square", "plaza", "avenue"),
               ("街", "巷", "集市", "市集", "闹市", "广场", "路口", "大道"),
               ("jie", "xiang", "shiji", "street", "market", "road", "lane", "square", "town", "city", "ext")),
    "SHOP": (("shop", "store", "stall", "pharmacy", "pawnshop", "boutique"), ("店铺", "铺子", "商铺", "胭脂铺", "药铺",
                                                                             "当铺", "摊位", "摊前"),
             ("pu", "dian", "shop", "store", "stall", "pharmacy")),
    "RIVER": (("river", "riverbank", "lake", "lakeshore", "shore", "dock", "pier", "wharf", "harbor", "harbour"),
              ("河边", "河岸", "江边", "湖边", "岸边", "码头"), ("he", "jiang", "hu", "matou", "river", "lake", "shore", "dock")),
    "FOREST": (("forest", "woods", "grove", "jungle"), ("树林", "森林", "林间", "竹林"), ("lin", "forest", "wood", "grove")),
    "MOUNTAIN": (("mountain", "cliff", "peak", "summit", "ridge"), ("山顶", "山崖", "悬崖", "山巅", "山道"),
                 ("shan", "mountain", "cliff", "peak", "ridge")),
}
_EN_PLACE_PREP = r"\b(?:on|onto|aboard|into|in|inside|at|across|through|along|down|up|toward|towards|out to|out into)" \
                 r"\s+(?:the|a|an)\s+(?:[a-z-]+\s+){0,2}?"
_ZH_PLACE_PREP = r"(?:在|到|进|进入|上了|登上|走进|来到|冲进|奔向|回到|于)[^，。；,.;临沿隔]{0,4}?"


def _place_mentions(text: str) -> list[tuple[str, str]]:
    """Places an action sentence stands in: a lower-case place noun after a locative preposition ("on a fishing
    boat", "into the street"; a capitalised name -- "Baker Street" -- is not one), or 在/到/进…<place> in Chinese
    (临街 / 沿街 are modifiers, not places)."""
    out: list[tuple[str, str]] = []
    for place, (en, zh, _ids) in PLACE_CLASSES.items():
        for word in en:
            if re.search(r"(?i:" + _EN_PLACE_PREP + r")" + re.escape(word) + r"s?\b", text):
                out.append((place, word))
        for word in zh:
            if re.search(_ZH_PLACE_PREP + r"(?<![临沿隔])" + re.escape(word), text):
                out.append((place, word))
    return out


def _place_in_location(place: str, location_text: str) -> bool:
    en, zh, ids = PLACE_CLASSES[place]
    low = location_text.lower()
    tokens = re.split(r"[^a-z0-9]+", low)
    return (place.lower() in low or any(w in low for w in en) or any(w in location_text for w in zh)
            or any(t.startswith(w) or t.endswith(w) for t in tokens if t for w in ids))


def location_contradictions(contract: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """scene_id -> place words its action text puts it in that its declared location does not hold."""
    shots = [s for s in (contract or {}).get("shots") or [] if isinstance(s, dict)]
    by_id = {_clean(s.get("shot_id")): s for s in shots}
    scene_rows = {_clean(r.get("scene_id")): r for r in (contract or {}).get("scene_states") or [] if isinstance(r, dict)}
    out: dict[str, list[str]] = {}
    for r in rows:
        shot = by_id.get(r["shot_id"]) or {}
        srow = scene_rows.get(r["scene_id"]) or {}
        location_text = " ".join(_clean(x) for x in (r["location"], srow.get("location_id"), srow.get("location"),
                                                    srow.get("location_name"), srow.get("name"),
                                                    srow.get("description"), shot.get("location_id")))
        location_text = location_text.replace("-", " ").replace("_", " ")
        text = " ".join(_clean(x) for x in (action_text(shot), shot.get("completion_state"), shot.get("entry_state")))
        for place, word in _place_mentions(text):
            if not _place_in_location(place, location_text):
                found = out.setdefault(r["scene_id"], [])
                if word not in found:
                    found.append(word)
    return out


def scene_order_failures(contract: dict[str, Any]) -> list[str]:
    """The shots array is the playback order: a scene_id that comes back after another scene has started is a shot
    filed at the wrong place (deep review 1485 E09, 2026-11-23: the six silent scene-closing shots of S01-S05 were
    appended after the last scene and played as a 9 s montage at the end of the episode).  A shot that declares
    ``intercut: true`` or an INTERCUT / CROSS_CUT / FLASHBACK transition may return."""
    out: list[str] = []
    order: list[str] = []
    for shot in (contract or {}).get("shots") or []:
        if not isinstance(shot, dict):
            continue
        scene = _clean(shot.get("scene_id"))
        if not scene:
            continue
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        mode = str((_field_source(shot, spec, "transition") or {}).get("transition_mode")
                   or shot.get("incoming_transition_mode") or "").upper()
        if order and scene != order[-1] and scene in order and not shot.get("intercut") \
                and mode not in INTERCUT_MODES:
            out.append(f"SCENE_NOT_CONTIGUOUS:{scene}:{_clean(shot.get('shot_id'))}")
        if not order or order[-1] != scene:
            order.append(scene)
    return out[:8]


_SHOT_SUFFIX = re.compile(r"^(.*?)(\d+)\s*$")


def _shot_rank(shot_id: str) -> tuple[str, int] | None:
    m = _SHOT_SUFFIX.match(shot_id)
    return (m.group(1), int(m.group(2))) if m else None


def repair_scene_order(contract: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Deterministic fix for SCENE_NOT_CONTIGUOUS (owner 2026-11-23: the last ~10-25 s of ZH E25 / JA E10 were a
    montage of 1.5 s silent shots with odd camera, no subtitles and stray voices).  Root cause: the writer adds each
    scene's silent visual beats / closing shots (JA E09/E10 ``E10-S01-06``; ZH E25 ``E25-S01-V01`` ...) *after the
    last scene* of the ``shots`` array; units follow the shots array, so S7 played them as an out-of-order tail.
    Every run of shots of a scene that comes back after another scene started (no intercut / flashback declared) is
    moved, as a run, back into its own scene's first run: at the place ``structure[].shot_ids`` gives its first shot,
    else after the last shot of the same id family with a lower number (``-05`` after ``-04``), else at the end of
    the scene.  Returns (new contract, moved shot ids) -- (None, []) when nothing moves.  Shots stay byte-identical;
    only their order changes."""
    shots = (contract or {}).get("shots")
    if not isinstance(shots, list) or not scene_order_failures(contract):
        return None, []
    struct_pos: dict[str, int] = {}
    for beat in (contract or {}).get("structure") or []:
        for sid in (beat.get("shot_ids") if isinstance(beat, dict) else None) or []:
            struct_pos.setdefault(_clean(sid), len(struct_pos))
    runs: list[tuple[str, list[Any]]] = []
    for idx, shot in enumerate(shots):
        scene = _clean(shot.get("scene_id")) if isinstance(shot, dict) else ""
        if isinstance(shot, dict) and scene:
            spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
            mode = str((_field_source(shot, spec, "transition") or {}).get("transition_mode")
                       or shot.get("incoming_transition_mode") or "").upper()
            if shot.get("intercut") or mode in INTERCUT_MODES:
                scene = f"__intercut_{idx}"  # a declared intercut keeps its place
        key = scene or f"__noscene_{idx}"
        if runs and runs[-1][0] == key:
            runs[-1][1].append(shot)
        else:
            runs.append((key, [shot]))
    home: dict[str, list[Any]] = {}
    out_runs: list[list[Any]] = []
    moved: list[str] = []
    for key, run in runs:
        if key not in home or key.startswith("__"):
            home[key] = list(run)
            out_runs.append(home[key])
            continue
        target = home[key]
        first = _clean(run[0].get("shot_id")) if isinstance(run[0], dict) else ""
        at = len(target)
        ids = [_clean(s.get("shot_id")) if isinstance(s, dict) else "" for s in target]
        if first in struct_pos and all(i in struct_pos for i in ids):
            at = next((j for j, i in enumerate(ids) if struct_pos[i] > struct_pos[first]), len(target))
        elif _shot_rank(first):
            fam, num = _shot_rank(first)
            same = [j for j, i in enumerate(ids) if _shot_rank(i) and _shot_rank(i)[0] == fam]
            if same:
                lower = [j for j in same if _shot_rank(ids[j])[1] < num]
                at = (lower[-1] + 1) if lower else same[0]
        target[at:at] = run
        moved.extend(_clean(s.get("shot_id")) if isinstance(s, dict) else "" for s in run)
    out = [s for run in out_runs for s in run]
    if not moved or out == shots:
        return None, []
    return {**contract, "shots": out}, moved


def integrity_failures(contract: dict[str, Any], language: str | None = None,
                       metrics: dict[str, Any] | None = None) -> list[str]:
    """The non-admittable part of the check: boilerplate and a same-place split whose action names another place."""
    contract = contract if isinstance(contract, dict) else {}
    m = metrics if metrics is not None else measure(contract, language)
    rows = timeline(contract, m.get("language") or contract_language(contract, language))
    failures = scene_order_failures(contract) + boilerplate_failures(contract)
    contradicted = location_contradictions(contract, rows)
    for pair in m.get("same_place_splits") or []:
        a, _, b = pair.partition(">")
        words = (contradicted.get(a) or []) + (contradicted.get(b) or [])
        if words:
            failures.append(f"SCENE_SPLIT_LOCATION_CONTRADICTS_ACTION:{pair}:{'/'.join(words[:3])}")
    return failures


#: craft_profile BILI_V1 (line owner 2026-11-23, cheap reaction rule; CHANGE_SPEC WP3, supersedes PR #325's 1-in-5
#: silent reaction share): every ATTACK / REVEAL / PUNCHLINE / TURN / PAYOFF line is followed by the listener's reaction
#: -- in frame (a), as the next shot's lead-in (b), or a dedicated silent CU (c, <= 3 per episode).  Taste codes;
#: LEGACY never sees them (REACTION_BEAT_UNCOVERED / DEDICATED_REACTION_OVER, measured by
#: director_pass.reaction_coverage in evaluate()).
def _director():
    import director_pass as _dp  # noqa: PLC0415 -- same directory (BILI_V1 only)
    return _dp


# --------------------------------------------------------------------------- evaluate
#: failure code -> one-line fix the writer can act on (no story text; language-agnostic)
FIXES = {
    "REACTION_BEAT_UNCOVERED": "after every attack / reveal / punchline / turn line, show the person it lands on react: "
                               "(a) in the same shot, as the over-the-shoulder / two-shot listener "
                               "(action.listener_reaction + listener_reaction_en, hands and props allowed), or (b) as "
                               "the first 1-2 s of their own next line (action.lead_in_reaction + lead_in_reaction_en); "
                               "a dedicated silent reaction close-up only after a key reveal, turn or the ending",
    "DEDICATED_REACTION_OVER": "at most 3 dedicated silent reaction close-ups per episode, only after a REVEAL / TURN / "
                               "ENDING beat; move the others into the shot (listener in frame) or the next line's "
                               "lead-in",
    "FIRST_CONFLICT_LATE": "open mid-conflict: the first shot is already the insult / reveal / danger (<= 3 s)",
    "TOO_FEW_TURNS": "pull more plot events into the episode (cut filler, merge scenes, take the next chapters)",
    "TURN_GAP_TOO_LONG": "add an escalation / reversal / reveal inside the longest gap (one turn per 20-30 s)",
    "DIALOGUE_ONLY_TOO_HIGH": "turn exposition lines into visible action and reaction shots (measured from the "
                              "storyboard: a line spoken with only a gesture or a step is a talking head)",
    "VISUAL_ACTION_TOO_LOW": "give >= 30 % of the screen time to action / insert / establishing / transition shots "
                             "or lines spoken while something physical happens (grab, shove, hand over, break, run)",
    "VISUAL_BEATS_TOO_FEW": "add silent visual beats: an action shot, a prop insert, an establishing view of the new "
                            "place, a transition (one every ~30 s)",
    "VISUAL_VARIETY_LOW": "give the eye something new every ~20-25 s -- inside the same place is fine: a character "
                          "moves or crosses the room, someone arrives, a prop insert, a reaction with action, a "
                          "blocking change; change place only for a story reason (time skip, travel / arrival shown, "
                          "a new event) -- never relocate a conversation to fake a scene change",
    "CONVERSATION_SPLIT_ACROSS_LOCATIONS": "one continuing conversation (same people, same thread, no time skip) stays "
                                           "in ONE location and ONE scene_id: merge the scenes back into the first "
                                           "place; only if the story really moves on, open the new place on a silent "
                                           "establishing / arrival shot, or make it a real time jump (scene time "
                                           "changes, or scene_plan change_reason TIME_SKIP told by a line)",
    "REMOTE_CALL_ONE_PLACE": "a phone / video call is one conversation in TWO places: keep one scene_id, but give "
                             "every shot of the far caller its own place via shot_scene_overrides[shot_id].location_id "
                             "(a cross-cut, not a split); in every on-camera call shot the phone is visible in hand / "
                             "at the ear in entry_state and frame_content (declare it in props.reference_cards); the "
                             "speaker looks toward the person on the line; people the script puts in the room with a "
                             "caller are in that caller's frame",
    "PERFORMANCE_PLACEHOLDER": "write each speaking shot's entry / action / exit from THAT line: one concrete movement "
                               "(a head tilt, a look away, a step, crossing the arms, touching a prop, a posture shift) "
                               "and the listener's reaction; never one template sentence on every line, never 'a clear "
                               "gesture' / 'visible posture change', no pointing or raised index finger unless the story "
                               "needs it",
    "SCENE_SPLIT_SAME_LOCATION": "two consecutive scene_ids in the same place without a time skip are one scene: "
                                 "merge them (one scene_id, one scene_states row)",
    "LINE_TOO_LONG": "at most 2 short sentences per line; split or cut the rest",
    "BACK_TO_BACK_MONOLOGUE": "break the run with an interjection, a physical action or a reaction",
    "SCENE_TALK_ONLY": "give the scene a physical action that changes something (grab, shove, hand over, leave)",
    "SCENE_PLAN_MISSING": "write pacing.scene_plan: objective, conflict and physical action per scene",
    "ENDING_NOT_OPEN": "end on the cliffhanger itself (pacing.cliffhanger with an open question, last shot)",
    "ADAPTATION_PLAN_MISSING": "write adaptation_plan: source_chapters, plot_events, cut",
    "ADAPTATION_TOO_THIN": "budget the episode by plot events: cover at least the required turns from the source",
    "BOILERPLATE_TEXT": "write each scene's own start/end framing, ambience, axis, transition and scene plan from "
                        "THAT scene's place and action (who is where, what is heard there), and each shot's own "
                        "action / blocking / exit / gesture from THAT line (what this person physically does here, "
                        "with which prop or partner) -- never one series template copied onto every shot "
                        "(integrity: not admitted after revisions)",
    "BOILERPLATE_PHRASE": "replace the template sentences ('the declared subject / location / beat', a copied "
                          "ambience or axis) with the shot's concrete content",
    "SCENE_NOT_CONTIGUOUS": "the shots array is the playback order: put every shot inside its own scene (a scene's "
                            "closing / silent beat goes after that scene's last line, before the next scene starts); "
                            "only a declared intercut (intercut: true or an INTERCUT / FLASHBACK transition) may "
                            "return to an earlier scene (integrity)",
    "SCENE_SPLIT_LOCATION_CONTRADICTS_ACTION": "the action happens somewhere else than the scene's location_id "
                                               "(a boat, a shop, a street): give that scene its own location, "
                                               "ambience and axis, or move the action back (integrity)",
}


def _bili_v1(contract: dict[str, Any], craft_profile: str | None = None) -> bool:
    """BILI_V1 craft profile (CHANGE_SPEC WP1): the caller's resolved profile, else the contract's own declaration."""
    try:
        try:
            from tools import craft_profile as _cp  # noqa: PLC0415
        except ModuleNotFoundError:  # runtime tools dir only
            import craft_profile as _cp  # noqa: PLC0415
        return _cp.is_bili_v1(craft_profile if craft_profile else contract)
    except Exception:  # noqa: BLE001 -- an unreadable profile is LEGACY
        return False


def evaluate(contract: dict[str, Any], language: str | None = None,
             environ: dict[str, str] | None = None, *, in_flight: bool = False,
             source_texts: list[str] | None = None, craft_profile: str | None = None,
             revision_round: int = 0) -> dict[str, Any]:
    """{status PASS|FAIL, active, failures [codes], warnings, fixes, metrics}.  ``active`` = the policy applies
    (declared, or by default -- :func:`policy_active`) and the switch is on; an inactive report is ADVISORY whatever
    its numbers.  ``in_flight``: the episode is past a paid stage (a default-policy contract is then grandfathered).
    ``source_texts``: the adapted source chapters -- their action sentences are suggested as beats to dramatise when
    the script is short of visual action.  ``craft_profile`` (BILI_V1, CHANGE_SPEC WP1): events are capped instead of
    floored and the adaptation checks of ``bili_adaptation_check`` run; ``revision_round`` = failing scripts the
    writer already revised (BILI_V1 slogans are advisory on round 0).  LEGACY ignores both."""
    m = measure(contract, language)
    bili = _bili_v1(contract, craft_profile)
    t = TARGETS
    failures: list[str] = []
    warnings: list[str] = [f"TURN_TYPE_UNKNOWN:{k}" for k in m["unknown_turn_types"][:4]]
    fc = m["first_conflict_at"]
    if fc is None or fc > t["first_conflict_max_seconds"]:
        failures.append(f"FIRST_CONFLICT_LATE:{'none' if fc is None else f'{fc:.1f}s'}")
    if m["turn_count"] < m["required_turns"]:
        failures.append(f"TOO_FEW_TURNS:{m['turn_count']}<{m['required_turns']}")
    if m["max_turn_gap_seconds"] > t["max_turn_gap_seconds"]:
        w = m["max_turn_gap_window"] or [0, m["duration_seconds"]]
        failures.append(f"TURN_GAP_TOO_LONG:{m['max_turn_gap_seconds']:.1f}s@{w[0]:.0f}-{w[1]:.0f}")
    if m["dialogue_only_ratio"] > t["dialogue_only_ratio_max"]:
        failures.append(f"DIALOGUE_ONLY_TOO_HIGH:{m['dialogue_only_ratio']:.2f}")
    if m["duration_seconds"] and m["visual_action_ratio"] < t["visual_action_ratio_min"]:
        failures.append(f"VISUAL_ACTION_TOO_LOW:{m['visual_action_ratio']:.2f}<{t['visual_action_ratio_min']:.2f}")
    if m["duration_seconds"] and m["visual_beat_count"] < m["required_visual_beats"]:
        failures.append(f"VISUAL_BEATS_TOO_FEW:{m['visual_beat_count']}<{m['required_visual_beats']}")
    if m["duration_seconds"] and m["visual_variety_count"] < m["required_visual_variety"]:
        # motivated scene changes and in-place variety count; a relocated conversation does not (JA-01 E08)
        failures.append(f"VISUAL_VARIETY_LOW:{m['visual_variety_count']}<{m['required_visual_variety']}"
                        f"(motivated_scene_changes={m['motivated_scene_changes']})")
    for pair in m["conversation_splits"][:4]:
        failures.append(f"CONVERSATION_SPLIT_ACROSS_LOCATIONS:{pair}")
    for sid in (m.get("remote_call_one_place") or [])[:4]:
        failures.append(f"REMOTE_CALL_ONE_PLACE:{sid}")  # taste: revised by the writer, admitted after the rounds
    integrity = integrity_failures(contract, language, m)
    screenplay_row = screenplay_checks_row(contract)  # BILI_V1 (WP2 anti-template v2); {} under LEGACY
    if screenplay_row:
        integrity = integrity + screenplay_row["integrity"]
        failures += screenplay_row["taste"]
        warnings += screenplay_row["advisory"]
        for code, text in screenplay_row["fixes"].items():
            FIXES.setdefault(code, text)
        m["screenplay_checks"] = screenplay_row["metrics"]
    contradicted_pairs = {f.split(":")[1] for f in integrity if f.startswith("SCENE_SPLIT_LOCATION_CONTRADICTS_ACTION:")}
    for pair in [p for p in m["same_place_splits"] if p not in contradicted_pairs][:4]:
        # a split whose action names another place is an integrity failure instead (never admitted)
        failures.append(f"SCENE_SPLIT_SAME_LOCATION:{pair}")
    if m["placeholder_acting"]:
        failures.append(f"PERFORMANCE_PLACEHOLDER:{len(m['placeholder_acting'])}")
    if m["dialogue_only_ratio_declared"] + 0.25 < m["dialogue_only_ratio"]:
        # the writer's state labels claim far more action than the storyboard shows (E07: 0.00 declared)
        warnings.append(f"DECLARED_ACTION_NOT_IN_STORYBOARD:{m['dialogue_only_ratio_declared']:.2f}"
                        f"<{m['dialogue_only_ratio']:.2f}")
    if m["long_line_count"]:
        failures.append(f"LINE_TOO_LONG:{m['long_line_count']}")
    if m["monologue_runs"]:
        failures.append(f"BACK_TO_BACK_MONOLOGUE:{len(m['monologue_runs'])}")
    for sid in m["scenes_without_action"][:6]:
        failures.append(f"SCENE_TALK_ONLY:{sid}")
    if bili:
        # BILI_V1 only: the owner's cheap reaction rule (taste: REVISE, admitted after MAX_REVISIONS)
        cov = _director().reaction_coverage(contract)
        m["reaction_coverage"] = cov
        failures.extend(f"REACTION_BEAT_UNCOVERED:{sid}" for sid in cov["uncovered"][:6])
        if cov["dedicated_count"] > cov["dedicated_max"]:
            failures.append(f"DEDICATED_REACTION_OVER:{cov['dedicated_count']}>{cov['dedicated_max']}")
        warnings.extend(f"DEDICATED_REACTION_MISPLACED:{sid}" for sid in cov["misplaced_dedicated"][:4])
    if m["scene_plan_missing"]:
        failures.append(f"SCENE_PLAN_MISSING:{len(m['scene_plan_missing'])}")
    if not m["ending"]["unresolved"]:
        failures.append(f"ENDING_NOT_OPEN:{m['ending']['basis']}")
    ad = m["adaptation"]
    if not ad["declared"]:
        failures.append("ADAPTATION_PLAN_MISSING")
    elif not bili and ad["plot_event_count"] < m["required_turns"]:
        failures.append(f"ADAPTATION_TOO_THIN:{ad['plot_event_count']}<{m['required_turns']}")
    if not bili and ad["declared"] and ad["source_chapter_count"] <= 1 and \
            ad["plot_event_count"] < m["required_turns"] + 2:
        warnings.append("SINGLE_CHAPTER_EPISODE")
    bili_row: dict[str, Any] = {}
    if bili:
        # BILI_V1 (WP1): 1 main + <= 1 secondary plot event, source details, report lines, slogans, reveal fidelity
        import bili_adaptation_check as _bili  # noqa: PLC0415 -- same directory
        bili_row = _bili.check(contract, m["language"], list(dict.fromkeys(r["scene_id"] for r in timeline(
            contract, m["language"]))), source_texts, revision_round=revision_round)
        failures += bili_row["failures"]
        warnings += bili_row["warnings"]
        m["bili_v1"] = bili_row["metrics"]
    basis = policy_basis(contract)
    # no shots = no script to revise (an unreadable / missing contract is other gates' business)
    active = policy_active(contract, in_flight=in_flight) and enabled(environ) and bool(m["shot_count"])
    codes = sorted({c.split(":", 1)[0] for c in failures})
    suggestions = []
    if source_texts and {"VISUAL_ACTION_TOO_LOW", "VISUAL_BEATS_TOO_FEW", "SCENE_TALK_ONLY", "DIALOGUE_ONLY_TOO_HIGH",
                         "VISUAL_VARIETY_LOW"} & set(codes):
        suggestions = source_action_beats(source_texts, m["language"])
    integrity_on = integrity_enabled(environ) and not in_flight and bool(m["shot_count"])
    if bili_row:
        integrity = integrity + bili_row["integrity"]
        source_fix = ({"SOURCE_DETAIL_MISSING", "SOURCE_DETAIL_NOT_IN_SOURCE"} & set(codes)) and source_texts
        if source_fix and not suggestions:
            suggestions = source_action_beats(source_texts, m["language"])
    fix_table = {**FIXES, **_bili.FIXES} if bili_row else FIXES
    fixes = {c: fix_table[c] for c in codes + sorted({f.split(":", 1)[0] for f in integrity}) if c in fix_table}
    if suggestions:
        fixes["SOURCE_ACTION_BEATS"] = ("dramatise these physical moments of the source chapters as action / insert "
                                        "shots instead of telling them in dialogue: " + " | ".join(suggestions))
    return {"schema": SCHEMA, "policy": POLICY, "active": active, "policy_basis": basis,
            **({"craft_profile": "BILI_V1"} if bili else {}),
            **({"grandfathered": "IN_FLIGHT_PAST_PAID_STAGE"} if in_flight and basis == "DEFAULT" else {}),
            "authority": "WRITER_REVISION_LOOP" if active else "ADVISORY_NOT_A_GATE",
            "status": "PASS" if not failures else "FAIL", "failures": failures, "warnings": warnings,
            "integrity_active": integrity_on, "integrity_failures": integrity,
            "boilerplate_warnings": boilerplate_failures(contract, advisory=True),
            "integrity_status": "FAIL" if (integrity and integrity_on) else "PASS",
            "fixes": fixes, "source_action_beats": suggestions, "targets": dict(TARGETS), "metrics": m}


# --------------------------------------------------------------------------- source action beats
_SOURCE_SENTENCE = re.compile(r"[^。！？!?…\n]+[。！？!?…]*")


def source_action_beats(texts: list[str], language: str | None = None, limit: int = 6) -> list[str]:
    """Up to ``limit`` short source sentences that describe a physical action (the strong-action lexicon), in
    source order, deduplicated -- concrete beats the writer can show instead of narrate.  Dialogue sentences (quoted)
    are skipped.  Pure; never raises."""
    out: list[str] = []
    seen: set[str] = set()
    try:
        for text in texts or []:
            for raw in _SOURCE_SENTENCE.findall(str(text or "")):
                sentence = re.sub(r"\s+", " ", raw).strip(" 　#*>-")
                if len(sentence) < 6 or sentence[:1] in "「『“\"'" or "：「" in sentence:
                    continue
                if not strong_action(sentence):
                    continue
                short = sentence if len(sentence) <= 70 else sentence[:69] + "…"
                if short in seen:
                    continue
                seen.add(short)
                out.append(short)
                if len(out) >= limit:
                    return out
    except Exception:  # noqa: BLE001 -- a suggestion must never break the check
        return out
    return out


def source_texts_for(contract: dict[str, Any], runtime_root: Path | None,
                     craft_profile: str | None = None) -> list[str]:
    """The adapted source chapters' text: the contract's ``source_text`` file, plus ``adaptation_plan.source_chapters``
    under ``<runtime>/sources/<work>/<canonical_reading_script>/chNNNN.md`` (SOURCE_INDEX.json).  [] when none.
    BILI_V1 (WP1): also the ``source_binding`` files, the bound work first (``bili_adaptation_check.source_texts``)."""
    if craft_profile and _bili_v1(contract, craft_profile):
        import bili_adaptation_check as _bili  # noqa: PLC0415 -- same directory
        return _bili.source_texts(contract, runtime_root)
    out: list[str] = []
    try:
        declared = _clean((contract or {}).get("source_text"))
        if declared and Path(declared).is_file():
            out.append(Path(declared).read_text(encoding="utf-8", errors="replace"))
        chapters = measure(contract)["adaptation"]["source_chapters"]
        if not chapters or runtime_root is None:
            return out
        for index in sorted(Path(runtime_root, "sources").glob("*/SOURCE_INDEX.json")):
            meta = _read(index)
            folder = index.parent / _clean(meta.get("canonical_reading_script") or "as_delivered")
            files = [folder / f"ch{c:04d}.md" for c in chapters]
            if any(f.is_file() for f in files):
                out.extend(f.read_text(encoding="utf-8", errors="replace") for f in files if f.is_file())
                break
    except Exception:  # noqa: BLE001
        return out
    return out


# --------------------------------------------------------------------------- revision loop
def contract_sha(contract: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(contract, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def decide(report: dict[str, Any], sha: str, rounds_path: Path, *, max_revisions: int = MAX_REVISIONS,
           record: bool = True) -> dict[str, Any]:
    """One S1 decision of the revision loop.

    PASS                     the check passed
    ADVISORY                 the contract did not opt in (or the switch is off): metrics only
    REVISE                   failing, revision round n of ``max_revisions``: the writer revises and reruns S1
    ADMITTED_AFTER_REVISIONS failing after ``max_revisions`` revisions: the script goes on with the gaps recorded

    Each distinct failing contract sha is one round; re-running S1 on the same bytes never uses up a round, but
    the same failing bytes evaluated more than STALL_EVALUATIONS times are admitted (the writer is not revising).
    ``record=False`` (S1 blocked by another gate) reports without counting a round."""
    state = _read(rounds_path) if rounds_path else {}
    rows = [r for r in state.get("rounds") or [] if isinstance(r, dict)]
    failing = [r["contract_sha256"] for r in rows if r.get("status") == "FAIL" and r.get("contract_sha256")]
    same = next((r for r in rows if r.get("contract_sha256") == sha), None)
    evaluations = int((same or {}).get("evaluations") or (1 if same else 0)) + 1
    reason = None
    if not report.get("active"):
        decision = "ADVISORY"
    elif report.get("status") == "PASS":
        decision = "PASS"
    else:
        n = len(dict.fromkeys(failing + [sha]))
        decision = "REVISE" if n <= max_revisions else "ADMITTED_AFTER_REVISIONS"
        reason = "REVISIONS_EXHAUSTED" if decision != "REVISE" else None
        if decision == "REVISE" and evaluations > STALL_EVALUATIONS:
            # the same failing bytes re-run again and again: the writer is not revising -- never stall the line
            decision, reason = "ADMITTED_AFTER_REVISIONS", "SAME_SCRIPT_RERUN"
    if record and rounds_path and report.get("active"):
        if same is None:
            rows.append({"contract_sha256": sha, "status": report.get("status"),
                         "failures": list(report.get("failures") or [])[:12], "evaluations": 1,
                         "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        else:
            same["evaluations"] = evaluations
        _write(rounds_path, {"schema": ROUNDS_SCHEMA, "max_revisions": max_revisions, "rounds": rows})
    failing_now = len(dict.fromkeys(failing + ([sha] if report.get("status") == "FAIL" else [])))
    return {"decision": decision, "revision_round": min(failing_now, max_revisions + 1),
            "max_revisions": max_revisions, "blocks": decision == "REVISE",
            **({"reason": reason} if reason else {})}


def prior_failing_rounds(rounds_path: Path | None, sha: str) -> int:
    """Distinct failing scripts in the round ledger other than ``sha`` (0 = this is the first evaluation)."""
    rows = [r for r in (_read(rounds_path) if rounds_path else {}).get("rounds") or [] if isinstance(r, dict)]
    return len({r.get("contract_sha256") for r in rows
                if r.get("status") == "FAIL" and r.get("contract_sha256") and r.get("contract_sha256") != sha})


def integrity_blocker_codes(report: dict[str, Any]) -> list[str]:
    """S1 blockers for the integrity part (boilerplate, contradicted location).  Never admitted after revisions."""
    if not report.get("integrity_active"):
        return []
    return [f"SCRIPT_INTEGRITY_FAIL:{code}" for code in (report.get("integrity_failures") or [])[:8]]


def blocker_codes(report: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    if not decision.get("blocks"):
        return []
    head = f"SCRIPT_PACING_REVISE:round={decision['revision_round']}/{decision['max_revisions']}"
    return [head] + [f"SCRIPT_PACING_REVISE:{code}" for code in (report.get("failures") or [])[:8]]


def summary(report: dict[str, Any], decision: dict[str, Any] | None = None) -> dict[str, Any]:
    """The compact episode-record row (pipeline state S1 details, final review context)."""
    m = report.get("metrics") or {}
    return {"policy": report.get("policy"), "active": report.get("active"), "status": report.get("status"),
            **({"decision": decision.get("decision"), "revision_round": decision.get("revision_round")}
               if decision else {}),
            "failures": list(report.get("failures") or [])[:12],
            "integrity_status": report.get("integrity_status"),
            "integrity_failures": list(report.get("integrity_failures") or [])[:12],
            "metrics": {k: m.get(k) for k in (
                "duration_seconds", "turn_count", "required_turns", "beats_per_minute", "first_conflict_at",
                "max_turn_gap_seconds", "max_turn_gap_window", "dialogue_only_ratio", "speech_share_ref",
                "longest_line", "long_line_count", "scenes_without_action", "scene_count",
                "dialogue_only_ratio_declared", "visual_action_ratio", "visual_beat_count", "required_visual_beats",
                "location_count", "scenes_per_2min", "time_change", "motivated_scene_changes",
                "conversation_splits", "same_place_splits", "visual_variety_count", "required_visual_variety")},
            "policy_basis": report.get("policy_basis"),
            **({"grandfathered": report["grandfathered"]} if report.get("grandfathered") else {}),
            "source_action_beats": list(report.get("source_action_beats") or [])[:6],
            "ending_unresolved": (m.get("ending") or {}).get("unresolved"),
            "turns": [{"at": t.get("at"), "type": t.get("type")} for t in m.get("turns") or []][:12],
            "adaptation": m.get("adaptation"),
            **({"craft_profile": report["craft_profile"], "bili_v1": {
                k: (m.get("bili_v1") or {}).get(k) for k in ("events", "report_lines", "revision_round")}}
               if report.get("craft_profile") else {})}


# --------------------------------------------------------------------------- source coverage
def coverage_path(runtime_root: Path) -> Path:
    return Path(runtime_root) / "series" / "SOURCE_COVERAGE.json"


def record_coverage(runtime_root: Path, episode: str, contract: dict[str, Any]) -> dict[str, Any]:
    """Remember which source chapters / how many plot events ``episode`` adapted (from ``adaptation_plan``).
    Re-recording an episode replaces its row.  Never raises; {} when the contract declares no plan."""
    try:
        plan = contract.get("adaptation_plan") if isinstance(contract.get("adaptation_plan"), dict) else {}
        if not plan:
            return {}
        m = measure(contract)["adaptation"]
        path = coverage_path(runtime_root)
        data = _read(path) or {"schema": COVERAGE_SCHEMA, "episodes": {}}
        data.setdefault("episodes", {})[episode] = {
            "source_chapters": m["source_chapters"], "plot_event_count": m["plot_event_count"],
            "cut_count": m["cut_count"], "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        data["schema"] = COVERAGE_SCHEMA
        _write(path, data)
        return coverage(runtime_root)
    except Exception:  # noqa: BLE001 -- bookkeeping must never fail a stage
        return {}


def coverage(runtime_root: Path) -> dict[str, Any]:
    """{episodes, last_chapter, next_chapter, chapters_covered, gaps}: where the series is in the book."""
    data = _read(coverage_path(runtime_root))
    episodes = data.get("episodes") or {}
    covered = sorted({int(c) for row in episodes.values() if isinstance(row, dict)
                      for c in row.get("source_chapters") or [] if _num(c) is not None})
    last = covered[-1] if covered else None
    gaps = [c for c in range(covered[0], last + 1) if c not in covered] if covered else []
    return {"schema": COVERAGE_SCHEMA, "episodes": episodes, "chapters_covered": covered, "last_chapter": last,
            "next_chapter": (last + 1) if last is not None else None, "skipped_chapters": gaps}


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="measure a generation contract (free; exit 0 always unless --strict)")
    c.add_argument("--contract", required=True)
    c.add_argument("--language")
    c.add_argument("--out")
    c.add_argument("--strict", action="store_true", help="exit 3 when the check fails")
    v = sub.add_parser("coverage", help="source chapters covered so far and where the next episode starts")
    v.add_argument("--runtime-root", default=os.environ.get("NALU_RUNTIME_ROOT") or str(Path.home() / "nalu_runtime"))
    args = ap.parse_args(argv)
    if args.cmd == "coverage":
        print(json.dumps(coverage(Path(args.runtime_root).expanduser()), ensure_ascii=False, indent=1))
        return 0
    contract = _read(Path(args.contract))
    report = evaluate(contract, args.language)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        _write(Path(args.out), report)
    print(json.dumps({"status": report["status"], "active": report["active"], "failures": report["failures"],
                      "fixes": report["fixes"]}, ensure_ascii=False) if args.out else text)
    return 3 if (args.strict and report["status"] == "FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
