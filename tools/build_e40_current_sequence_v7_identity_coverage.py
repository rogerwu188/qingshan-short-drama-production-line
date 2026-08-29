#!/usr/bin/env python3
"""Rebuild E40 story-order assembly with the identity-safe S03/S04 coverage decision."""

from __future__ import annotations

from pathlib import Path

import build_e40_current_sequence_v6_all_dialogue_covered as base


ROOT = Path(__file__).resolve().parents[1]
base.OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V7_IDENTITY_SAFE.mp4"
base.QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V7_IDENTITY_SAFE_QA.json"

# S03 is already represented by the exact same admitted no-face curtain reaction
# used by V6's R03 segment; do not duplicate it merely to inflate runtime.
insert_at = next(index for index, row in enumerate(base.SEGMENTS) if row[0] == "R04")
base.SEGMENTS.insert(
    insert_at,
    (
        "E40-13-2-S04-IDENTITY-SAFE",
        "working_assets/e40_remake_20260822/identity_authority_switch_coverage_v1/E40_S04_FOUR_FROST_HAND_NOFACE_COVERAGE_V1.mp4",
        False,
    ),
)


if __name__ == "__main__":
    raise SystemExit(base.main())
