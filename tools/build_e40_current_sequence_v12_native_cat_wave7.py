#!/usr/bin/env python3
"""Insert the native-registry Chenji/Wuyun shoulder-motion coverage."""

from __future__ import annotations

from pathlib import Path

import build_e40_current_sequence_v11_snow_wave6 as v11


ROOT = Path(__file__).resolve().parents[1]
base = v11.base
base.OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V12_NATIVE_CAT_WAVE7.mp4"
base.QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V12_NATIVE_CAT_WAVE7_QA.json"

insert_after = next(index for index, row in enumerate(base.SEGMENTS) if row[0] == "R08")
base.SEGMENTS.insert(
    insert_after + 1,
    (
        "E40-13-5-S02-CHENJI-WUYUN-NATIVE-MOTION",
        "working_assets/e40_remake_20260822/native_identity_composites_wave7_v1/E40_13_5_S02_CHENJI_WUYUN_NATIVE_MOTION_COVERAGE_V1.mp4",
        False,
    ),
)


if __name__ == "__main__":
    raise SystemExit(base.main())
