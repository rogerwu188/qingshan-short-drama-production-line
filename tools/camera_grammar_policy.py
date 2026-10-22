#!/usr/bin/env python3
"""Camera grammar policy (CAMERA_GRAMMAR_V1): motivated motion and real cuts.

Line owner 2026-10-22 (Twelve Gazes E01 viewer review): the camera pans and
orbits with no reason, the direction alternates mechanically, scripted cuts
render as slow drifts from the previous unit's tail, and there is no shot-scale
grammar.  This module holds the switch and the shared vocabulary; the rules
live where the old ones did (static_design_gate, grouped_camera_contract,
build_keyframe_manifest, nalu_pipeline previs).

Never retroactive: an episode is under the policy only when its generation
contract declares ``camera_grammar_policy = CAMERA_GRAMMAR_V1`` or the episode
is listed in configs/CAMERA_GRAMMAR_V1.json ``enabled_episodes``.  The writer
workflow stamps the field on contracts sealed from this engine version on
(``stamp_contract``); every contract sealed before carries no field and keeps
its old verdicts byte for byte.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

POLICY_ID = "CAMERA_GRAMMAR_V1"
OPT_OUT = "LEGACY_FORCED_MOTION"
CONTRACT_FIELD = "camera_grammar_policy"
POLICY_PATH = Path(__file__).resolve().parents[1] / "configs" / "CAMERA_GRAMMAR_V1.json"

MOTION_MOTIVATIONS = frozenset({"FOLLOW_SUBJECT", "REVEAL", "EMPHASIS", "SUBJECTIVE"})
#: families that move the camera through space (static_design_gate / nalu_prompt_rules MOVING_CAMERA)
MOVING_FAMILIES = frozenset({"ARC", "TRACK", "CRANE", "HANDHELD", "ORBIT", "PAN", "TILT"})
REST_FAMILIES = frozenset({"", "LOCKED", "STATIC"})
CUT_TRANSITION_MODES = frozenset({"MOTIVATED_CUT", "REACTION_CUT", "MATCH_CUT", "HARD_CUT"})
ESTABLISHING_SCALES = frozenset({"WIDE", "MEDIUM_WIDE", "FULL", "EXTREME_WIDE", "LONG", "LONG_SHOT"})
#: shot_size prose (zh / en) used only when camera_plan.shot_scale is absent
_SIZE_TO_SCALE = (
    ("大远景", "WIDE"), ("远景", "WIDE"), ("中全景", "MEDIUM_WIDE"), ("全景", "WIDE"),
    ("大特写", "EXTREME_CLOSE_UP"), ("特写", "CLOSE_UP"), ("中近景", "MEDIUM_CLOSE_UP"),
    ("近景", "MEDIUM_CLOSE_UP"), ("中景", "MEDIUM"),
)
DEFAULT_THRESHOLDS = {"hold_insert_max_seconds": 3.0, "same_scale_run_max": 2,
                      "establishing_within_first_shots": 2}

#: English body-level action stems (nalu_prompt_rules.BODY_VERBS is Chinese only, so an English
#: line could never show "body motion" and every no-dialogue shot was pushed into a camera move).
_EN_BODY_STEMS = (
    "walk", "step", "stride", "strode", "pace", "turns around", "turned around", "turning around",
    "turn around", "turns away", "turned away", "turning away", "turn away", "spin", "spun", "whirl",
    "pivot", "rise", "rises", "rose", "stand", "stood", "sit", "sat", "kneel", "knelt", "crouch",
    "squat", "fall", "fell", "stumbl", "stagger", "lurch", "collaps", "run", "ran", "rush", "sprint",
    "dash", "lung", "leap", "leapt", "jump", "climb", "crawl", "drag", "pull", "push", "shove",
    "throw", "threw", "hurl", "grab", "seiz", "lean", "bend", "bent", "stoop", "straighten",
    "duck", "dodg", "recoil", "retreat", "back away", "backs away", "backed away", "approach",
    "enter", "cross", "strik", "struck", "swing", "swung", "kick", "punch", "wrestl", "embrac",
    "writh", "lie down", "lies down", "lay down", "roll", "slump", "carr", "haul",
)
_EN_BODY_RE = re.compile(r"\b(?:" + "|".join(re.escape(s) for s in _EN_BODY_STEMS) + r")[a-z]*\b")


def policy_settings() -> dict[str, Any]:
    try:
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def thresholds() -> dict[str, float]:
    out = dict(DEFAULT_THRESHOLDS)
    out.update({k: v for k, v in (policy_settings().get("thresholds") or {}).items() if k in out})
    return out


def _episode(contract: dict[str, Any] | None, episode: str | None) -> str:
    raw = str(episode or (contract or {}).get("episode") or (contract or {}).get("episode_id") or "")
    match = re.match(r"(E\d+)", raw.strip().upper())
    return match.group(1) if match else ""


def active(contract: dict[str, Any] | None, *, episode: str | None = None) -> bool:
    """Whether CAMERA_GRAMMAR_V1 governs this episode (contract declaration or config listing)."""
    declared = str((contract or {}).get(CONTRACT_FIELD) or "").strip().upper()
    if declared == POLICY_ID:
        return True
    if declared:  # any other declared value (LEGACY_FORCED_MOTION) is an explicit opt-out
        return False
    ep = _episode(contract, episode)
    listed = {str(v).strip().upper() for v in policy_settings().get("enabled_episodes") or []}
    return bool(ep and ep in listed)


def stamp_contract(contract: dict[str, Any]) -> bool:
    """Add camera_grammar_policy=CAMERA_GRAMMAR_V1 right after ``episode`` when the writer left it out.

    Returns True when the dict changed.  A declared value (including the opt-out) is never overwritten.
    """
    if not isinstance(contract, dict) or CONTRACT_FIELD in contract:
        return False
    items = list(contract.items())
    contract.clear()
    inserted = False
    for key, value in items:
        contract[key] = value
        if key == "episode":
            contract[CONTRACT_FIELD] = POLICY_ID
            inserted = True
    if not inserted:
        contract[CONTRACT_FIELD] = POLICY_ID
    return True


def declared_motivation(plan: dict[str, Any] | None) -> str | None:
    """The camera_plan's valid motion_motivation, or None."""
    value = str((plan or {}).get("motion_motivation") or "").strip().upper()
    return value if value in MOTION_MOTIVATIONS else None


def is_rest(plan: dict[str, Any] | None) -> bool:
    """Camera at rest for grammar purposes: LOCKED/STATIC/missing, or a slow DOLLY PUSH_IN."""
    plan = plan or {}
    family = str(plan.get("motion_family") or "").upper()
    direction = str(plan.get("motion_direction") or "").upper()
    return family in REST_FAMILIES or family == "PUSH_IN" or (family == "DOLLY" and direction == "PUSH_IN")


def has_body_motion(*texts: str) -> bool:
    """Body-level action in the authored action text (Chinese BODY_VERBS or English stems)."""
    joined = " ".join(str(t or "") for t in texts)
    try:
        import nalu_prompt_rules as _npr  # lines/nalu/runtime/tools on sys.path
        zh = _npr.BODY_VERBS
    except Exception:  # noqa: BLE001 — the English check still works without the rule module
        zh = ()
    if any(v in joined for v in zh):
        return True
    return bool(_EN_BODY_RE.search(joined.lower()))


def shot_scale(shot: dict[str, Any]) -> str:
    plan = ((shot.get("prompt_spec") or {}).get("camera_plan") or {})
    scale = str(plan.get("shot_scale") or "").strip().upper()
    if scale:
        return scale
    size = str(shot.get("shot_size") or "")
    for token, mapped in _SIZE_TO_SCALE:
        if token in size:
            return mapped
    low = size.lower()
    if "wide" in low or "full" in low or "long" in low:
        return "WIDE"
    return ""


def _scene_locations(contract: dict[str, Any]) -> dict[str, str]:
    return {str(s.get("scene_id")): str(s.get("location_id") or "")
            for s in contract.get("scene_states") or [] if s.get("scene_id")}


def authored_transition_mode(contract: dict[str, Any], from_shot: str, to_shot: str) -> str:
    for row in contract.get("internal_transition_authoring") or []:
        if str(row.get("from_shot_id")) == str(from_shot) and str(row.get("to_shot_id")) == str(to_shot):
            return str(row.get("transition_mode") or "").strip().upper()
    return ""


def opener_cut_reason(contract: dict[str, Any], previous_last_shot: str, first_shot: str) -> str | None:
    """Why a unit opening on ``first_shot`` after ``previous_last_shot`` must start from its own keyframe.

    None means the boundary is continuous and keeps the previous unit's real tail as start frame.
    """
    shots = {str(s.get("shot_id")): s for s in contract.get("shots") or []}
    left, right = shots.get(str(previous_last_shot)), shots.get(str(first_shot))
    if left is None or right is None:
        return None
    if str(left.get("scene_id") or "") != str(right.get("scene_id") or ""):
        return "SCENE_CHANGE"
    locations = _scene_locations(contract)
    l_loc = str(((left.get("prompt_spec") or {}).get("space") or {}).get("location")
                or locations.get(str(left.get("scene_id"))) or "")
    r_loc = str(((right.get("prompt_spec") or {}).get("space") or {}).get("location")
                or locations.get(str(right.get("scene_id"))) or "")
    if l_loc and r_loc and l_loc != r_loc:
        return "LOCATION_CHANGE"
    mode = authored_transition_mode(contract, str(previous_last_shot), str(first_shot))
    if mode in CUT_TRANSITION_MODES:
        return f"AUTHORED_{mode}"
    return None
