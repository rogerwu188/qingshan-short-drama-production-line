#!/usr/bin/env python3
"""Add three distinct identity-safe canonical-gap coverage shots to E40 V7."""

from __future__ import annotations

from pathlib import Path

import build_e40_current_sequence_v7_identity_coverage as v7


ROOT = Path(__file__).resolve().parents[1]
base = v7.base
base.OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V8_ZERO_COST_WAVE3.mp4"
base.QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V8_ZERO_COST_WAVE3_QA.json"

cat_at = next(index for index, row in enumerate(base.SEGMENTS) if row[0] == "R05")
base.SEGMENTS.insert(cat_at, ("E40-13-2-S06-WUYUN-ALERT", "working_assets/e40_remake_20260822/canonical_gap_zero_cost_wave3_v1/E40_13_2_S06_WUYUN_ALERT_V1.mp4", False))

silence_at = next(index for index, row in enumerate(base.SEGMENTS) if row[0] == "R06A")
base.SEGMENTS.insert(silence_at, ("E40-13-3-S05-CURTAIN-SILENCE", "working_assets/e40_remake_20260822/canonical_gap_zero_cost_wave3_v1/E40_13_3_S05_CURTAIN_SILENCE_V1.mp4", False))

base.SEGMENTS.append(("E40-13-5-S06-HALL-PULLBACK-PARTIAL", "working_assets/e40_remake_20260822/canonical_gap_zero_cost_wave3_v1/E40_13_5_S06_HALL_PULLBACK_PARTIAL_V1.mp4", False))


if __name__ == "__main__":
    raise SystemExit(base.main())
