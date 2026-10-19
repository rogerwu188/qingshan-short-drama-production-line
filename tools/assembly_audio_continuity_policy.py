#!/usr/bin/env python3
"""Episode-level switch for the S7 cut-point audio dip (W1 wiring).

The dip itself already exists in ``audio_cut_overlap.py``.  This module only
answers "does this episode use it", following the same opt-in shape as
``measured_edit_policy.py``: a missing policy file or a null
``active_from_episode`` means no episode changes, so an in-production episode's
audio stays byte-identical until the line owner turns it on.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "nalu.assembly_audio_continuity.v1"
POLICY_PATH = Path(__file__).resolve().parents[1] / "configs" / "ASSEMBLY_AUDIO_CONTINUITY_V1.json"


def load_policy(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        path = POLICY_PATH
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _episode_number(value: Any) -> int | None:
    match = re.search(r"(?:^|[^A-Z])E(\d+)", str(value or "").upper())
    return int(match.group(1)) if match else None


def active_for(episode: str, *, contract: dict[str, Any] | None = None,
               line: str = "nalu", policy: dict[str, Any] | None = None) -> bool:
    declared = str((contract or {}).get("assembly_audio_continuity") or "").strip().upper()
    if declared == "ASSEMBLY_AUDIO_CONTINUITY_V1":
        return True
    policy = load_policy() if policy is None else policy
    if policy.get("schema") != SCHEMA:
        return False
    line_config = (policy.get("lines") or {}).get(line) or {}
    active_from = line_config.get("active_from_episode")
    number = _episode_number(episode)
    return active_from is not None and number is not None and number >= int(active_from)


def crossfade_seconds(policy: dict[str, Any] | None = None) -> float:
    policy = load_policy() if policy is None else policy
    try:
        value = float(policy.get("crossfade_seconds") or 0.08)
    except (TypeError, ValueError):
        return 0.08
    return value if value > 0 else 0.08


def boundaries_from_release_timeline(timeline: dict[str, Any]) -> list[float]:
    """Cut points are the output_start of every segment after the first."""
    starts = sorted(
        float(row["output_start"])
        for row in timeline.get("segments") or []
        if isinstance(row, dict) and row.get("output_start") is not None
    )
    return [round(value, 3) for value in starts[1:]]
