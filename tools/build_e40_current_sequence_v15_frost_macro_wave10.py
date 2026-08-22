#!/usr/bin/env python3
"""Insert the no-face frost-finger recognition macro."""

from __future__ import annotations

from pathlib import Path

import build_e40_current_sequence_v14_first_look_wave9 as v14


ROOT = Path(__file__).resolve().parents[1]
base = v14.base
base.OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V15_FROST_MACRO_WAVE10.mp4"
base.QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V15_FROST_MACRO_WAVE10_QA.json"

insert_before = next(index for index, row in enumerate(base.SEGMENTS) if row[0] == "R02")
base.SEGMENTS.insert(
    insert_before,
    (
        "E40-13-1-S04-FROST-FINGER-NOFACE-MACRO",
        "working_assets/e40_remake_20260822/native_identity_composites_wave10_v1/E40_13_1_S04_FROST_FINGER_NOFACE_MACRO_V1.mp4",
        False,
    ),
)


if __name__ == "__main__":
    raise SystemExit(base.main())
