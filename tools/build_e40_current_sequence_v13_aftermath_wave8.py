#!/usr/bin/env python3
"""Insert the native-asset battle-aftermath editorial equivalent."""

from __future__ import annotations

from pathlib import Path

import build_e40_current_sequence_v12_native_cat_wave7 as v12


ROOT = Path(__file__).resolve().parents[1]
base = v12.base
base.OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V13_AFTERMATH_WAVE8.mp4"
base.QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V13_AFTERMATH_WAVE8_QA.json"

insert_after = next(index for index, row in enumerate(base.SEGMENTS) if row[0] == "R06C")
base.SEGMENTS.insert(
    insert_after + 1,
    (
        "E40-13-4-S06-BATTLE-AFTERMATH-NATIVE-MONTAGE",
        "working_assets/e40_remake_20260822/native_identity_composites_wave8_v1/E40_13_4_S06_BATTLE_AFTERMATH_NATIVE_MONTAGE_V1.mp4",
        False,
    ),
)


if __name__ == "__main__":
    raise SystemExit(base.main())
