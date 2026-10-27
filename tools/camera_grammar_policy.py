#!/usr/bin/env python3
"""CAMERA_GRAMMAR_V1 switch (line owner 2026-10-22, Twelve Gazes viewer review).

Never retroactive: an episode is under the policy only when its generation contract declares
``camera_grammar_policy = CAMERA_GRAMMAR_V1`` (storyclaw finalize stamps every newly sealed
contract) or configs/CAMERA_GRAMMAR_V1.json lists the episode.  Any other declared value
(``LEGACY_FORCED_MOTION``) is an explicit opt-out.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

POLICY_ID = "CAMERA_GRAMMAR_V1"
FIELD = "camera_grammar_policy"
POLICY_PATH = Path(__file__).resolve().parents[1] / "configs" / "CAMERA_GRAMMAR_V1.json"


def active(contract: dict[str, Any] | None, *, episode: str | None = None) -> bool:
    declared = str((contract or {}).get(FIELD) or "").strip().upper()
    if declared:
        return declared == POLICY_ID
    match = re.match(r"E\d+", str(episode or (contract or {}).get("episode") or "").strip().upper())
    try:
        listed = json.loads(POLICY_PATH.read_text(encoding="utf-8")).get("enabled_episodes") or []
    except (OSError, ValueError):
        listed = []
    return bool(match and match.group(0) in {str(v).upper() for v in listed})


def stamp_contract(contract: dict[str, Any]) -> bool:
    """Insert the field right after ``episode`` unless the writer declared one; True when changed."""
    if not isinstance(contract, dict) or FIELD in contract:
        return False
    items = list(contract.items())
    contract.clear()
    for key, value in items:
        contract[key] = value
        if key == "episode":
            contract[FIELD] = POLICY_ID
    contract.setdefault(FIELD, POLICY_ID)
    return True


#: Keyframe framing vs. the mapped fixed elements (line owner 2026-10-24, lab Holmes E03: a
#: MEDIUM_CLOSE_UP keyframe prompt demanded all five room fixed elements, so the image model drew a
#: wide room with Helen small at the left and H3 panned away from her).  Scale-aware for stamped
#: contracts only: close scales require no fixed element, MEDIUM at most two, wider scales unchanged.
CLOSE_SCALES = ("CLOSE_UP", "EXTREME_CLOSE_UP", "MEDIUM_CLOSE_UP")
MEDIUM_SCALES = ("MEDIUM",)
MEDIUM_MAX_FIXED_ELEMENTS = 2

#: explicit picture range per close/medium scale (the keyframe prompt states it, the reviewer reads it)
PICTURE_RANGE = {
    "EXTREME_CLOSE_UP": ("只取脸部或一个局部（face or one detail only），主体位于画面中央并占满画面",
                         "face or one detail only, centred and filling the frame"),
    "CLOSE_UP": ("头肩（framed head and shoulders），脸位于画面中央三分之一，人物占满画面",
                 "head and shoulders, face in the central third, the person fills the frame"),
    "MEDIUM_CLOSE_UP": ("胸口中部以上（framed from mid-chest up），脸位于画面中央三分之一，人物占满画面",
                        "framed from mid-chest up, face in the central third, the person fills the frame"),
    "MEDIUM": ("腰部以上（framed from the waist up），人物位于画面中部",
               "framed from the waist up, the person in the middle of the frame"),
}


def normalise_scale(value: Any) -> str:
    return re.sub(r"[^A-Z]+", "_", str(value or "").strip().upper()).strip("_")


def fixed_element_rule(shot_size: Any) -> dict[str, Any]:
    """{scale, mode, max_required, picture_range_zh/en, rule_en} for one keyframe's shot size.

    mode: NONE_REQUIRED (close scales), AT_MOST_TWO (MEDIUM), ALL_MAPPED (anything wider / unknown)."""
    scale = normalise_scale(shot_size)
    zh, en = PICTURE_RANGE.get(scale, ("", ""))
    if scale in CLOSE_SCALES:
        return {"scale": scale, "mode": "NONE_REQUIRED", "max_required": 0,
                "picture_range_zh": zh, "picture_range_en": en,
                "rule_en": (f"{scale}: no mapped fixed element is required; at most one or two may show partly or "
                            f"soft behind the person; the frame is {en}. A frame filled by the person is correct.")}
    if scale in MEDIUM_SCALES:
        return {"scale": scale, "mode": "AT_MOST_TWO", "max_required": MEDIUM_MAX_FIXED_ELEMENTS,
                "picture_range_zh": zh, "picture_range_en": en,
                "rule_en": (f"MEDIUM: at most {MEDIUM_MAX_FIXED_ELEMENTS} of the mapped fixed elements need to "
                            f"show (in their mapped relationship); the frame is {en}.")}
    return {"scale": scale, "mode": "ALL_MAPPED", "max_required": None, "picture_range_zh": "",
            "picture_range_en": "", "rule_en": "Every mapped fixed element shows in its mapped relationship."}


#: Speaking-shot eyeline (line owner 2026-10-26, lab Holmes E05): "eyes on the listener" alone let the speaker
#: stare into the lens.  The speaker looks just off the lens toward the listener's screen side; shot/reverse
#: singles of one pair look to opposite sides so the two singles face each other.
GAZE_SIDES = ("left", "right")
_SIDE_WORDS = {"LEFT": "left", "SCREEN_LEFT": "left", "FRAME_LEFT": "left", "L": "left",
               "RIGHT": "right", "SCREEN_RIGHT": "right", "FRAME_RIGHT": "right", "R": "right"}
#: optional writer fields naming the listener's screen side (role_semantic_disambiguation or prompt_spec)
LISTENER_SIDE_FIELDS = ("dialogue_listener_screen_side", "listener_screen_side", "listener_side")


def _side_word(value: Any) -> str:
    return _SIDE_WORDS.get(normalise_scale(value), "")


def speaker_gaze_side(speaker_id: Any, listener_id: Any = None, *, declared: Any = None,
                      cast_ids: list[Any] | None = None) -> dict[str, str]:
    """{side, method} of a speaker's off-lens eyeline.

    1. a declared listener screen side (writer field) wins;
    2. a speaker/listener pair: the two ids in sorted order — the first looks right, the second left (stable across
       every unit of the scene, so the shot and its reverse face each other);
    3. no listener: alternate by the speaker's position among the unit's declared cast (first right)."""
    side = _side_word(declared)
    if side:
        return {"side": side, "method": "DECLARED_LISTENER_SIDE"}
    speaker, listener = str(speaker_id or "").strip(), str(listener_id or "").strip()
    if speaker and listener and speaker != listener:
        return {"side": "right" if sorted([speaker, listener])[0] == speaker else "left",
                "method": "PAIR_ORDER_SHOT_REVERSE"}
    cast = sorted({str(v) for v in cast_ids or [] if str(v or "").strip()} | ({speaker} if speaker else set()))
    index = cast.index(speaker) if speaker in cast else 0
    return {"side": GAZE_SIDES[1 - index % 2], "method": "SPEAKER_ORDER_DEFAULT"}


def declared_listener_side(*rows: Any) -> str:
    for row in rows:
        if isinstance(row, dict):
            for key in LISTENER_SIDE_FIELDS:
                if _side_word(row.get(key)):
                    return _side_word(row.get(key))
    return ""


def speaker_gaze_sentence(label: str, side: str, listener: str = "") -> str:
    """The H3 speaking-unit eyeline sentence."""
    target = listener.strip() or "the other person"
    return (f"{label} looks just off the lens to the {side}, at {target}, never into the camera; "
            "the camera does not follow the gaze.")


def keyframe_eyeline_line(speaker: str, side: str, listener: str = "") -> str:
    """The keyframe prompt's eyeline line for a speaking shot (zh + the English picture instruction)."""
    side_zh = "左" if side == "left" else "右"
    target = listener.strip() or "对方"
    return (f"视线：{speaker}的眼睛看向镜头{side_zh}侧略偏处、看着画外的{target}，不直视镜头"
            f"（eyes just off-camera to the {side}, not looking into the lens）。")
