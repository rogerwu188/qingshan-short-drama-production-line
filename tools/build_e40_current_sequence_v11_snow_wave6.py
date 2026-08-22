#!/usr/bin/env python3
"""Replace the partial hall pullback with the masked exterior-snow completion."""

from __future__ import annotations

from pathlib import Path

import build_e40_current_sequence_v10_opening_wave5 as v10


ROOT = Path(__file__).resolve().parents[1]
base = v10.base
base.OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V11_SNOW_WAVE6.mp4"
base.QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V11_SNOW_WAVE6_QA.json"

ending_index = next(index for index, row in enumerate(base.SEGMENTS) if row[0] == "E40-13-5-S06-HALL-PULLBACK-PARTIAL")
base.SEGMENTS[ending_index] = (
    "E40-13-5-S06-HALL-PULLBACK-SNOW-COMPLETE",
    "working_assets/e40_remake_20260822/canonical_gap_zero_cost_wave6_v1/E40_13_5_S06_HALL_PULLBACK_SNOW_COMPLETE_V1.mp4",
    False,
)


if __name__ == "__main__":
    raise SystemExit(base.main())
