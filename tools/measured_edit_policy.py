"""Measured edit policy: episode-level opt-in for ASR-driven source trimming.

Schema: qingshan.measured_edit_policy.v1
Structure parallels prompt_shot_scope_policy.py — reuses its active_for pattern.
"""
import json
from pathlib import Path
from typing import Any


def load_policy(path: Path | None = None) -> dict[str, Any]:
    """Load measured edit policy from config."""
    if path is None:
        path = Path(__file__).parent / "configs" / "MEASURED_EDIT_POLICY_V1.json"
    if not path.is_file():
        return
    return json.loads(path.read_text())


def active_for(episode: str, line: str = "nalu", policy: dict[str, Any] | None = None) -> bool:
    """Check if measured edit is active for this episode on this line.

    Returns True if episode number >= active_from_episode for the line.
    Extracts episode number from episode string (e.g. "E11" -> 11).
    """
    if policy is None:
        policy = load_policy()

    lines = policy.get("lines") or {}
    line_config = lines.get(line) or {}
    active_from = line_config.get("active_from_episode")

    if active_from is None:
        return False

    # Extract episode number
    ep_num = None
    for char in episode:
        if char.isdigit():
            ep_num = int(episode[episode.index(char):].lstrip("0") or "0")
            break

    if ep_num is None:
        return False

    return ep_num >= active_from


def get_policy_params(episode: str, line: str = "nalu", policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get policy parameters for this episode.

    Returns dict with lead_seconds, trail_seconds, etc. or empty dict if inactive.
    """
    if not active_for(episode, line, policy):
        return {}

    if policy is None:
        policy = load_policy()

    lines = policy.get("lines") or {}
    line_config = lines.get(line) or {}

    return {
        "lead_seconds": line_config.get("lead_seconds", 0.08),
        "trail_seconds": line_config.get("trail_seconds", 0.12),
        "min_interval_seconds": line_config.get("min_interval_seconds", 2.0),
    }
