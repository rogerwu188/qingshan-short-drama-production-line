#!/usr/bin/env python3
"""Run the shared no-poll exact-two executor against the authorized U18 V5 package."""

from pathlib import Path
import e40_execute_u18_exact_two_authorized_no_poll as runner

ROOT = Path(__file__).resolve().parents[1]
runner.MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/keyframe_precompile/u18_isolated_asset_acquisition_v1/E40_U18_V5_CHANGED_COMPACT_EXACT_TWO_NO_SUBMIT_MANIFEST_V1.json"
runner.AUTH = ROOT / "workflow/approvals/E40_U18_V5_CHANGED_COMPACT_EXACT_TWO_IMAGE_AUTHORIZATION_20260813.json"
runner.READINESS = ROOT / "qa/e40_preproduction_20260813/u18_v5_changed_compact_precheck_v1/E40_U18_V5_CHANGED_COMPACT_EXECUTION_READINESS_AUDIT_V1.json"
runner.OUT_DIR = ROOT / "qa/e40_production_20260813/u18_v5_changed_compact_execution_v1"
runner.REPORT = runner.OUT_DIR / "E40_U18_V5_EXACT_TWO_ONE_POST_TASK_ID_BINDING_RECEIPT_V1.json"

if __name__ == "__main__":
    raise SystemExit(runner.main())
