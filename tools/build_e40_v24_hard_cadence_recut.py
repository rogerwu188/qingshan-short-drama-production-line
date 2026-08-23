#!/usr/bin/env python3
"""Materialize V24 with the strictest authorized compact evidence cadence."""

import build_e40_v22_frame_cadence_safe_recut as builder


def main() -> int:
    builder.BUILD_VERSION = "V24"
    builder.EDGE_TRIM_SECONDS = 0.375
    builder.MAX_SHOT_SECONDS = 2.5
    builder.FAILURE_REF = "qa/e40_remake_20260822/final_qa_v23_script_equivalent/E40_V23_REGRESSION_CI_V1.json"
    builder.OUT = builder.ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V24_HARD_CADENCE_RECUT.mp4"
    builder.QA = builder.ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V24_HARD_CADENCE_RECUT_QA.json"
    return builder.main()


if __name__ == "__main__":
    raise SystemExit(main())
