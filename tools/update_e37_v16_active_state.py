#!/usr/bin/env python3
"""Refresh authoritative E37 queue state after V15/V16 repair progress."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "workflow/work_queue.json"


def main() -> None:
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data["updated_at"] = now
    data["mode"] = "E37_V15_DIALOGUE_AND_V16_ACTION_REPAIR_ACTIVE"
    data["status"] = "E37_V16_ACTION_REBUILD_ACTIVE_DIALOGUE_V15_HARVESTED"
    data["occupied_scope_count"] = 1
    data["real_active_handle_count"] = 1
    data["updated_note_latest"] = (
        "Giggle balance recovered. All ten materially changed Pro1080p fixed-camera dialogue tasks completed and were harvested. "
        "Direct frame overview shows stable compositions pending per-source normal-speed/identity/OCR admission. The old V14 fight was revoked: "
        "canonical environmental ice screen had been incorrectly rewritten as a handheld small shield, and accepted action edit windows were compressed "
        "to 0.25-1.8 seconds. V16 now uses one-phase exact-tail serial action generation while unrelated generation/QA remains parallel. First A02A "
        "compound attempt was preserved FAIL for glass-panel geometry, premature arm intersection and no pre-impact tail distance. Materially changed "
        "A02A-R2 sidestep/miss-only task is running."
    )
    line = data.setdefault("lines", {}).setdefault("E37", {})
    line.update({
        "status": "V15_DIALOGUE_HARVESTED_V16_ACTION_REBUILD_ACTIVE",
        "current_phase": "Admit ten fixed-camera dialogue sources; rebuild canonical fire-fight as one-phase exact-tail Pro1080p shots; then rerender with subtitles, BGM and NALU outro, republish and hide V14 only after new public verification.",
        "blocked_by": None,
        "running_or_pending_task_ids": ["25dda385-473a-496d-abe8-ef58ad2a5342"],
        "latest_v15_submit_status": "COMPLETED_10_OF_10_HARVESTED",
        "latest_v15_harvest": "qa/e37_v15_fixed_camera_repair_20260804/harvest/E37_V15_FIXED_CAMERA_DIALOGUE_HARVEST.json",
        "latest_v16_action_plan": "workflow/tasks/E37_V16_ACTION_CAUSAL_PLAN_20260804.json",
        "latest_v16_action_compiled": "workflow/tasks/E37_V16_ACTION_CAUSAL_CHAIN_COMPILED_20260804.json",
        "latest_v16_action_failed_adjudication": "qa/e37_action_replacement_v16_20260804/a02a/E37_V16_A02A_DIRECT_ADJUDICATION_FAIL.json",
        "latest_v16_action_submit": "workflow/tasks/E37_V16_ACTION_A02A_R2_SUBMIT_20260804.json",
        "latest_v16_action_task_id": "25dda385-473a-496d-abe8-ef58ad2a5342",
        "old_v14_hide_policy": "DEFER_UNTIL_NEW_YOUTUBE_AND_DOUYIN_PUBLIC_MEDIA_VERIFIED"
    })
    QUEUE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"queue": str(QUEUE), "updated_at": now, "status": data["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
