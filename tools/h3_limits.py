#!/usr/bin/env python3
"""The shortest MiniMax-H3 unit the line requests: ONE knob (line owner 2026-11-23).

HopsAPI accepts integer 4-15 s today; the owner was told it will accept 2 s.  Until he flips it, the default stays 4
(current behaviour everywhere).  Resolution, first hit wins:

1. env ``NALU_H3_MIN_UNIT_SECONDS``;
2. ``configs/H3_LIMITS_V1.json`` ``min_unit_seconds``;
3. 4.

The value is an integer clamped to ``ALLOWED`` (2..4); anything unreadable falls through to the next source.
Every place that used to hard-code the 4 s floor calls :func:`min_unit_seconds` (see the config's ``read_by``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ENV = "NALU_H3_MIN_UNIT_SECONDS"
DEFAULT = 4
ALLOWED = (2, 4)
CONFIG = Path(__file__).resolve().parents[1] / "configs" / "H3_LIMITS_V1.json"


def _valid(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != int(number) or not ALLOWED[0] <= number <= ALLOWED[1]:
        return None
    return int(number)


def min_unit_seconds(environ: dict[str, str] | None = None, config_path: Path | None = None) -> int:
    env = os.environ if environ is None else environ
    value = _valid(env.get(ENV))
    if value is not None:
        return value
    try:
        data = json.loads(Path(config_path or CONFIG).read_text(encoding="utf-8"))
        value = _valid(data.get("min_unit_seconds"))
    except (OSError, ValueError, AttributeError):
        value = None
    return DEFAULT if value is None else value


def short_units_enabled(environ: dict[str, str] | None = None) -> bool:
    """True once the router takes 2 s units (the director may then plan 1.5-2.5 s reaction / insert units)."""
    return min_unit_seconds(environ) <= 2
