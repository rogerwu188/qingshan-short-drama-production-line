#!/usr/bin/env python3
"""Episode/model switch for the shot-scope upgrade (configs/PROMPT_SHOT_SCOPE_POLICY_V1.json).

Every consumer (SD2 + H3 renderers, the submit-boundary conflict gate, the loaded-module audit)
asks this one function, so a line opts in by episode and every earlier episode compiles
byte-for-byte as before -- no fingerprint change for submitted or in-flight tasks.

A missing or unreadable config means "not active" (legacy behaviour), never an exception:
the upgrade must not be able to stop a line that has not opted in.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "PROMPT_SHOT_SCOPE_POLICY_V1.json"


def load_policy(path: Path | None = None) -> dict[str, Any]:
    try:
        return json.loads((path or POLICY_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def episode_number(value: Any) -> int | None:
    match = re.search(r"E(\d{1,3})", str(value or ""), re.I)
    return int(match.group(1)) if match else None


def _line_for(model: str, policy: dict[str, Any]) -> dict[str, Any] | None:
    model = str(model or "").lower()
    for row in (policy.get("lines") or {}).values():
        if model in {str(m).lower() for m in row.get("models") or []}:
            return row
    return None


def active_for(episode: Any, model: Any, *, policy: dict[str, Any] | None = None) -> bool:
    """True when the shot-scope upgrade governs this episode on this model's line."""
    policy = load_policy() if policy is None else policy
    row = _line_for(str(model or ""), policy)
    number = episode_number(episode)
    if not row or number is None or row.get("active_from_episode") is None:
        return False
    return number >= int(row["active_from_episode"])
