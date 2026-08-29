#!/usr/bin/env python3
"""Rebuild E40 after correcting the canonical R04 dialogue order."""

from __future__ import annotations

from pathlib import Path

import build_e40_current_sequence_v15_frost_macro_wave10 as v15


ROOT = Path(__file__).resolve().parents[1]
base = v15.base
base.OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V16_R04_DIALOGUE_ORDER_FIX.mp4"
base.QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V16_R04_DIALOGUE_ORDER_FIX_QA.json"


if __name__ == "__main__":
    raise SystemExit(base.main())
