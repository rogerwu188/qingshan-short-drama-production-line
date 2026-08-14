#!/usr/bin/env python3
"""Use the shared exact-two scheduler transition for U18 V5."""

from pathlib import Path
import e40_u18_exact_two_execution_task_lane as lane

ROOT = Path(__file__).resolve().parents[1]
lane.AUTH = ROOT / "workflow/approvals/E40_U18_V5_CHANGED_COMPACT_EXACT_TWO_IMAGE_AUTHORIZATION_20260813.json"
lane.REPORT = ROOT / "qa/e40_production_20260813/u18_v5_changed_compact_execution_v1/E40_U18_V5_EXACT_TWO_ONE_POST_TASK_ID_BINDING_RECEIPT_V1.json"
lane.WAIT_ID = "E40-U18-V5-CHANGED-COMPACT-EXACT-TWO-ROOT-AUTHORIZATION-TASK-LOCAL-REMOTE-WAIT"
lane.EXEC_ID = "E40-U18-V6-CHANGED-COMPACT-EXACT-TWO-IMAGE-ONE-POST-TASK-ID-BINDING"

if __name__ == "__main__":
    raise SystemExit(lane.main())
