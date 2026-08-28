#!/usr/bin/env python3
"""Derive only the new E44 middle-state anchors; exclude all 50 bound tasks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
SOURCE = PROD / "E44_V5_GIGGLE_KEYFRAME_MANIFEST_PRECHECK_V1.json"
BOUND_SUBMISSION = QA / "E44_V5_GIGGLE_KEYFRAME_SUBMISSION_V1.json"
CONTINUITY = QA / "E44_V5_KEYFRAME_PROMPT_CONTINUITY_AUDIT_V1.json"
OUT = PROD / "E44_V5_MIDDLE_ANCHOR_SUPPLEMENT_PRECHECK_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    bound = json.loads(BOUND_SUBMISSION.read_text(encoding="utf-8"))
    continuity = json.loads(CONTINUITY.read_text(encoding="utf-8"))
    if continuity.get("status") != "PASS" or continuity.get("task_count") != 57:
        raise ValueError("57/57 keyframe prompt continuity audit is not PASS")
    bound_keys = {str(row["task_key"]) for row in bound.get("results") or [] if row.get("task_id")}
    tasks = [row for row in source["tasks"] if str(row["task_key"]) not in bound_keys]
    expected = {
        "E44-S02-02-KF-V1", "E44-S05-02-KF-V1", "E44-S06-02-KF-V1",
        "E44-S06-04-KF-V1", "E44-S09-06-KF-V1", "E44-S10-03-KF-V1",
        "E44-S10-06-KF-V1",
    }
    if {str(row["task_key"]) for row in tasks} != expected or len(tasks) != 7:
        raise ValueError("supplement is not the exact seven new semantic anchors")
    payload = dict(source)
    payload.update({
        "schema": "qingshan.giggle_image_middle_anchor_supplement.v1",
        "status": "PRECHECK_ONLY",
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "source_complete_manifest": rel(SOURCE),
        "source_complete_manifest_sha256": sha(SOURCE),
        "bound_submission_exclusion_ref": rel(BOUND_SUBMISSION),
        "bound_submission_exclusion_sha256": sha(BOUND_SUBMISSION),
        "supplement_reason": "MIDDLE_BEAT_INTRODUCES_ENTITY_ABSENT_FROM_FIRST_AND_TERMINAL_ANCHORS",
        "consumer_contract": {
            **(source.get("consumer_contract") or {}),
            "planned_anchor_count": 7,
            "full_episode_planned_anchor_count": 57,
            "already_bound_anchor_count": 50,
        },
        "machine_gate_reports": [*source["machine_gate_reports"], rel(CONTINUITY)],
        "tasks": tasks,
    })
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "new_tasks": 7, "excluded_bound_tasks": len(bound_keys), "out": rel(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
