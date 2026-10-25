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
