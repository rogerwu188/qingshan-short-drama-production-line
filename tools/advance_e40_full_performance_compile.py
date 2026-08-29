#!/usr/bin/env python3
"""Terminalize E40 dialogue compilation and dispatch keyframe compilation."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
PLAN = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_NATIVE_DIALOGUE_PLAN_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    evidence_ref = str(PLAN.relative_to(ROOT))
    evidence_sha = sha(PLAN)
    scheduler = json.loads(SCHEDULER.read_text(encoding="utf-8"))
    tasks = scheduler.setdefault("tasks", [])
    by_id = {row.get("task_id"): row for row in tasks}
    current_id = "E40-FULL-PERFORMANCE-NATIVE-DIALOGUE-COMPILE-V1"
    current = by_id[current_id]
    current.update({
        "state": "TERMINAL",
        "wait_scope": "NONE",
        "progress": "COMPILED_13_NATIVE_DIALOGUE_PERFORMANCE_UNITS_20_LINES_76_GENERATED_SECONDS",
        "last_progress_at": now,
        "completed_at": now,
        "next_due_at": None,
        "evidence_ref": evidence_ref,
        "evidence_sha256": evidence_sha,
        "next_action": "Consume the compiled plan in the exact-SHA native-registry keyframe builder.",
    })
    successor_id = "E40-FULL-PERFORMANCE-KEYFRAME-BATCH-COMPILE-V1"
    successor = {
        "task_id": successor_id,
        "lane_id": "E40_FULL_EPISODE_RUNTIME_COMPLETION",
        "state": "READY",
        "wait_scope": "NONE",
        "zero_cost": True,
        "deliverable_type": "NATIVE_REGISTRY_AND_SPATIAL_BOUND_KEYFRAME_MANIFESTS_FOR_13_DIALOGUE_UNITS",
        "liveness_role": "PRODUCING",
        "provider_post_allowed": False,
        "provider_query_allowed": False,
        "download_allowed": False,
        "maximum_new_submissions": 0,
        "progress": "DIALOGUE_PLAN_COMPILED_AWAITING_NATIVE_REGISTRY_KEYFRAME_BINDING",
        "last_progress_at": now,
        "next_due_at": now,
        "next_action": "Resolve native character assets first, bind EGSM/GSM/subspace and visible speaker blocking for all 13 units, then build and precheck keyframe manifests; do not submit video before exact-SHA Q1 admission.",
        "evidence_ref": evidence_ref,
        "evidence_sha256": evidence_sha,
    }
    if successor_id in by_id:
        by_id[successor_id].update(successor)
    else:
        tasks.append(successor)
    scheduler.update({
        "updated_at": now,
        "status": "READY_FULL_PERFORMANCE_KEYFRAME_BATCH_COMPILE",
        "target_slots": 1,
        "real_active_handle_count": 0,
    })
    write(SCHEDULER, scheduler)

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue.update({
        "updated_at": now,
        "mode": "FULL_PERFORMANCE_KEYFRAME_BATCH_COMPILE",
        "status": "READY_13_NATIVE_DIALOGUE_UNITS_FOR_NATIVE_REGISTRY_SPATIAL_KEYFRAME_BINDING",
    })
    queue["latest_e40_full_performance_dialogue_plan"] = {
        "status": "COMPILED_AWAITING_KEYFRAME_Q1",
        "path": evidence_ref,
        "sha256": evidence_sha,
        "unit_count": 13,
        "dialogue_line_count": 20,
        "planned_generated_seconds": 76,
        "next_task_id": successor_id,
    }
    write(QUEUE, queue)
    print(json.dumps({
        "status": "PASS",
        "scheduler_sha256": sha(SCHEDULER),
        "queue_sha256": sha(QUEUE),
        "terminalized": current_id,
        "successor": successor_id,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
