#!/usr/bin/env python3
"""The shortest MiniMax-H3 unit the line requests: ONE knob (line owner 2026-11-23).

HopsAPI accepts integer 2-15 s since 2026-11-24; the shipped config is 2 (live 2 s probe passed 2026-11-24).
Resolution, first hit wins:

1. env ``NALU_H3_MIN_UNIT_SECONDS``;
2. ``configs/H3_LIMITS_V1.json`` ``min_unit_seconds``;
3. 4.

The value is an integer clamped to ``ALLOWED`` (2..4); anything unreadable falls through to the next source.
Two values (owner 2026-11-24: the 2 s minimum must not turn LEGACY talking units into 2 s units):

* :func:`min_unit_seconds` -- what HopsAPI accepts: request validation, pricing, the BILI_V1 director pass (dedicated
  reaction / insert units at 1.5-2.5 s, requested at 2 s) and the per-unit provider minimum of those short units;
* :func:`unit_floor_seconds` -- the grouping / speaking-unit floor every other unit is padded to (LEGACY behaviour):
  env ``NALU_H3_UNIT_FLOOR_SECONDS`` > config ``unit_floor_seconds`` > 4, never below :func:`min_unit_seconds`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ENV = "NALU_H3_MIN_UNIT_SECONDS"
FLOOR_ENV = "NALU_H3_UNIT_FLOOR_SECONDS"
DEFAULT = 4
DEFAULT_FLOOR = 4
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


def _resolve(env_name: str, key: str, default: int, environ: dict[str, str] | None,
             config_path: Path | None) -> int:
    env = os.environ if environ is None else environ
    value = _valid(env.get(env_name))
    if value is not None:
        return value
    try:
        data = json.loads(Path(config_path or CONFIG).read_text(encoding="utf-8"))
        value = _valid(data.get(key))
    except (OSError, ValueError, AttributeError):
        value = None
    return default if value is None else value


def min_unit_seconds(environ: dict[str, str] | None = None, config_path: Path | None = None) -> int:
    """The shortest H3 request HopsAPI accepts."""
    return _resolve(ENV, "min_unit_seconds", DEFAULT, environ, config_path)


def unit_floor_seconds(environ: dict[str, str] | None = None, config_path: Path | None = None) -> int:
    """The floor ordinary (grouped / speaking) units are padded to; LEGACY stays at 4 when the provider takes 2."""
    floor = _resolve(FLOOR_ENV, "unit_floor_seconds", DEFAULT_FLOOR, environ, config_path)
    return max(floor, min_unit_seconds(environ, config_path))


def short_units_enabled(environ: dict[str, str] | None = None) -> bool:
    """True once the router takes 2 s units (the director may then plan 1.5-2.5 s reaction / insert units)."""
    return min_unit_seconds(environ) <= 2
