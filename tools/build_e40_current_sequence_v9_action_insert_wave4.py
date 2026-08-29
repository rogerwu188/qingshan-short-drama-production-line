#!/usr/bin/env python3
"""Replace the short arrow placeholder and add a distinct red-jade retract insert."""

from __future__ import annotations

from pathlib import Path

import build_e40_current_sequence_v8_zero_cost_wave3 as v8


ROOT = Path(__file__).resolve().parents[1]
base = v8.base
base.OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V9_ACTION_INSERT_WAVE4.mp4"
base.QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V9_ACTION_INSERT_WAVE4_QA.json"

arrow_index = next(index for index, row in enumerate(base.SEGMENTS) if row[0] == "R07")
base.SEGMENTS[arrow_index] = ("E40-13-4-S05-ARROW-INTERCEPT", "working_assets/e40_remake_20260822/canonical_gap_zero_cost_wave4_v1/E40_13_4_S05_ARROW_INTERCEPT_V1.mp4", False)

ending_index = next(index for index, row in enumerate(base.SEGMENTS) if row[0] == "E40-13-5-S06-HALL-PULLBACK-PARTIAL")
base.SEGMENTS.insert(ending_index, ("E40-13-5-S06-RED-JADE-RETRACT", "working_assets/e40_remake_20260822/canonical_gap_zero_cost_wave4_v1/E40_13_5_S06_RED_JADE_RETRACT_V1.mp4", False))


if __name__ == "__main__":
    raise SystemExit(base.main())
