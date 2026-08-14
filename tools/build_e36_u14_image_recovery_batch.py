#!/usr/bin/env python3
"""Build the current-cap, U14-only E36 recovery anchor manifest."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
SCRIPT_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/recovery_10000_20260730/E36_RECOVERY_IMAGE_BATCH_7_ANCHORS_V1.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/recovery_10000_20260730/u14_images/E36_U14_RECOVERY_IMAGE_BATCH_V1.json"
EXPECTED_SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
CURRENT_EPISODE_CREDITS = 7339
CAP = 10000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads(SCRIPT_MANIFEST.read_text(encoding="utf-8"))
    if sha256(SCRIPT) != EXPECTED_SCRIPT_SHA or manifest.get("sha256") != EXPECTED_SCRIPT_SHA:
        raise SystemExit("canonical script/manifest SHA drift")

    base = json.loads(BASE.read_text(encoding="utf-8"))
    tasks = [row for row in base["tasks"] if row["task_key"].startswith("E36-CW-U14-")]
    if [row["task_key"] for row in tasks] != [
        "E36-CW-U14-A1-STILL-V3-RECOVERY-10000",
        "E36-CW-U14-A2-STILL-V3-RECOVERY-10000",
    ]:
        raise SystemExit("U14 task extraction mismatch")

    for index, task in enumerate(tasks, start=1):
        task["generation_authority"]["episode_credit_ceiling"] = CAP
        task["generation_authority"]["episode_credits_before_submit"] = CURRENT_EPISODE_CREDITS + 11 * (index - 1)
        task["generation_authority"]["episode_credits_after_success"] = CURRENT_EPISODE_CREDITS + 11 * index
        task["status"] = "AUTHORIZED_READY_TO_SUBMIT_AFTER_FOCUSED_PRECHECK"

    payload = {
        "schema": "qingshan.image_batch_manifest.v2",
        "episode": "E36",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": "CL2X-825",
        "source_mailbox_sha256": "b83bdb784856d282140c1219a03c7904d753e9bf5c2ec4606c27e1eb1692cc0e",
        "source_script_sha256": EXPECTED_SCRIPT_SHA,
        "generation_authority": {
            "route": "A",
            "episode_credit_ceiling": CAP,
            "current_episode_credits": CURRENT_EPISODE_CREDITS,
            "batch_planned_credits": 22,
            "episode_credits_after_batch_success": CURRENT_EPISODE_CREDITS + 22,
            "attributable_headroom_after_batch_success": CAP - CURRENT_EPISODE_CREDITS - 22,
            "unchanged_paid_retry_allowed": False,
            "maximum_automatic_changed_input_paid_repair_per_unit": 1,
        },
        "consumer_contract": {
            "consumer": "U14 natural split video generation only after each anchor image QA PASS",
            "planned_anchor_count": 2,
            "submission_policy": "Submit A1 once, harvest and QA it, then submit A2 once only with accepted A1 continuity; preserve every failure.",
        },
        "machine_gate_reports": base["machine_gate_reports"],
        "source_manifest": str(BASE.relative_to(ROOT)),
        "source_manifest_sha256": sha256(BASE),
        "tasks": tasks,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "sha256": sha256(OUT), "task_count": len(tasks)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
