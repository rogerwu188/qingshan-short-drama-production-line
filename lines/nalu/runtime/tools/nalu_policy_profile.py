#!/usr/bin/env python3
"""Select legacy replay rules or the current portable production policy.

Historical NALU episodes keep their recorded episode-number exceptions when no
profile is selected.  A new, non-default series must not inherit the old E01
report-only windows merely because its first episode is also named ``E01``.
StoryClaw sets ``NALU_POLICY_PROFILE=CURRENT_PORTABLE`` explicitly; a declared
non-default ``NALU_SERIES_SCOPE_ID`` selects the same profile as a fail-safe.
"""
from __future__ import annotations

import os


LEGACY = "LEGACY_EPISODE_COMPAT"
CURRENT = "CURRENT_PORTABLE"
ALLOWED = {LEGACY, CURRENT}
DEFAULT_SCOPE_ID = "NALU-YEWUJIANG"


def selected() -> str:
    explicit = str(os.environ.get("NALU_POLICY_PROFILE") or "").strip().upper()
    if explicit:
        if explicit not in ALLOWED:
            raise SystemExit(f"NALU_POLICY_PROFILE_INVALID:{explicit}")
        return explicit
    scope_id = str(os.environ.get("NALU_SERIES_SCOPE_ID") or "").strip()
    if scope_id and scope_id != DEFAULT_SCOPE_ID:
        return CURRENT
    return LEGACY


def is_current() -> bool:
    return selected() == CURRENT


def uses_legacy_first_episode_exception(episode: str) -> bool:
    return str(episode) == "E01" and not is_current()
