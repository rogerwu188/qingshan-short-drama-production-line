#!/usr/bin/env python3
"""Sequence-level rhythm gate for combat runs."""

from __future__ import annotations

from itertools import groupby
from typing import Any

try:
    from tools.video_physical_continuity_contract import is_combat_unit
except ModuleNotFoundError:
    from video_physical_continuity_contract import is_combat_unit


SCHEMA = "qingshan.video_sequence_rhythm.v1_scene_combat_duration_contrast"


def _approved_override(unit: dict[str, Any]) -> bool:
    row = unit.get("combat_rhythm_override") or {}
    return (
        row.get("status") == "APPROVED"
        and bool(str(row.get("reason") or "").strip())
        and bool(str(row.get("approved_by") or "").strip())
    )


def validate_combat_sequence_rhythm(units: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    sequences: list[dict[str, Any]] = []
    for scene_id, rows_iter in groupby(units, key=lambda row: str(row.get("scene_id") or "UNKNOWN")):
        rows = list(rows_iter)
        current: list[dict[str, Any]] = []
        runs: list[list[dict[str, Any]]] = []
        for row in rows:
            if is_combat_unit(row):
                current.append(row)
            elif current:
                runs.append(current)
                current = []
        if current:
            runs.append(current)
        for run_index, run in enumerate(runs, 1):
            if len(run) < 5:
                continue
            durations = [float(row.get("duration_seconds") or 0) for row in run]
            overridden = all(_approved_override(row) for row in run)
            local: list[str] = []
            if len(set(durations)) < 2:
                local.append("COMBAT_SEQUENCE_DURATION_VARIETY_MISSING")
            if max(durations, default=0) < 7:
                local.append("COMBAT_SEQUENCE_EXCHANGE_MISSING")
            longest = max(
                (sum(1 for _ in group) for _, group in groupby(durations)), default=0
            )
            if longest > 4:
                local.append(f"COMBAT_SEQUENCE_IDENTICAL_DURATION_RUN:{longest}>4")
            if local and not overridden:
                failures.extend(f"{code}:{scene_id}:RUN_{run_index}" for code in local)
            sequences.append({
                "scene_id": scene_id,
                "run_index": run_index,
                "unit_count": len(run),
                "durations": durations,
                "longest_identical_duration_run": longest,
                "approved_override": overridden,
                "failures": [] if overridden else local,
            })
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "sequences": sequences,
        "failures": failures,
    }
