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
