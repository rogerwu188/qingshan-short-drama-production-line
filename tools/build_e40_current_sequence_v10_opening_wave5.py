#!/usr/bin/env python3
"""Replace the R01 placeholder with the canonical 8-second opening establishing shot."""

from __future__ import annotations

from pathlib import Path

import build_e40_current_sequence_v9_action_insert_wave4 as v9


ROOT = Path(__file__).resolve().parents[1]
base = v9.base
base.OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V10_OPENING_WAVE5.mp4"
base.QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V10_OPENING_WAVE5_QA.json"

opening_index = next(index for index, row in enumerate(base.SEGMENTS) if row[0] == "R01")
base.SEGMENTS[opening_index] = (
    "E40-13-1-S01-OPENING-ESTABLISHING",
    "working_assets/e40_remake_20260822/canonical_gap_zero_cost_wave5_v1/E40_13_1_S01_OPENING_ESTABLISHING_V1.mp4",
    False,
)


if __name__ == "__main__":
    raise SystemExit(base.main())
