#!/usr/bin/env python3
"""LOCKED_DIALOGUE_CAMERA_V1 switch (line owner 2026-10-30, E12 成片审看 item 2).

Dialogue units default to a locked-off camera; a move needs the writer's own camera text to ask for
one, and a move never reverses direction inside a unit.  Never retroactive: an episode is under the
policy only when its generation contract declares ``locked_dialogue_camera_policy =
LOCKED_DIALOGUE_CAMERA_V1`` or configs/LOCKED_DIALOGUE_CAMERA_V1.json lists the episode.  Camera plans
built under the policy carry ``camera_policy = LOCKED_DIALOGUE_CAMERA_V1`` so the renderer and the
prompt lints can recognise them without an episode id.

Effects (each site documents its own branch):
  * adapt_v4_layers_to_runtime: dialogue shots default LOCKED/NONE unless the directing slug authors a
    move; one direction per family per scene (no PUSH_IN/PULL_OUT alternation between adjacent shots)
  * static_design_gate: R1/R2/R3/R4/R6 (forced motion) are advisories; R9 (dialogue shot moving without
    an authored move) and R10 (opposite directions of one family inside a scene) BLOCK
  * h3_provider_prompt_renderer: a LOCKED plan renders the fixed-camera sentence; a moving plan says
    "one direction only, never reverses"; every beat of a dialogue unit that has no dialogue literal
    carries an explicit no-speech instruction; a short line gets breathing room
  * prompt_batch_qa: vp_dialogue_unit_locked_camera / vp_camera_move_single_direction /
    vp_silent_beats_declared lints
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

POLICY_ID = "LOCKED_DIALOGUE_CAMERA_V1"
FIELD = "locked_dialogue_camera_policy"
PLAN_FIELD = "camera_policy"
POLICY_PATH = Path(__file__).resolve().parents[1] / "configs" / "LOCKED_DIALOGUE_CAMERA_V1.json"


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


def plan_under_policy(plan: dict[str, Any] | None) -> bool:
    """A camera plan stamped by a builder/adapter running under the policy."""
    return str((plan or {}).get(PLAN_FIELD) or "").strip().upper() == POLICY_ID


def stamp_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if isinstance(plan, dict):
        plan[PLAN_FIELD] = POLICY_ID
    return plan
