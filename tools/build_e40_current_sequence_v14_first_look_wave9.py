#!/usr/bin/env python3
"""Insert the exact-native first-look eyeline editorial equivalent."""

from __future__ import annotations

from pathlib import Path

import build_e40_current_sequence_v13_aftermath_wave8 as v13


ROOT = Path(__file__).resolve().parents[1]
base = v13.base
base.OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V14_FIRST_LOOK_WAVE9.mp4"
base.QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V14_FIRST_LOOK_WAVE9_QA.json"

insert_before = next(index for index, row in enumerate(base.SEGMENTS) if row[0] == "E40-13-5-S06-RED-JADE-RETRACT")
base.SEGMENTS.insert(
    insert_before,
    (
        "E40-13-5-S05-FIRST-LOOK-NATIVE-EYELINE",
        "working_assets/e40_remake_20260822/native_identity_composites_wave9_v1/E40_13_5_S05_FIRST_LOOK_NATIVE_EYELINE_V1.mp4",
        False,
    ),
)


if __name__ == "__main__":
    raise SystemExit(base.main())
