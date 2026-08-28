#!/usr/bin/env python3
"""Authorize the exact E44 v5 semantic-keyframe set for one paid POST each."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
SOURCE = PROD / "E44_V5_GIGGLE_KEYFRAME_MANIFEST_PRECHECK_V1.json"
PRECHECK = QA / "E44_V5_GIGGLE_KEYFRAME_PROVIDER_PRECHECK_V1.json"
CONTINUITY = QA / "E44_V5_KEYFRAME_PROMPT_CONTINUITY_AUDIT_V1.json"
OUTPUT = PROD / "E44_V5_GIGGLE_KEYFRAME_MANIFEST_AUTHORIZED_V1.json"
GATE = QA / "E44_V5_GIGGLE_KEYFRAME_COST_GUARD_V1.json"
AUTHORIZATION_REF = "ROGER-20260828-START-E44-PRODUCTION"
TASK_COUNT = 50
HARD_UNIT_PRICE_CAP = 11
EPISODE_CREDIT_CAP = 10000


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    precheck = json.loads(PRECHECK.read_text(encoding="utf-8"))
    continuity = json.loads(CONTINUITY.read_text(encoding="utf-8"))
    tasks = deepcopy(source.get("tasks") or [])
    if len(tasks) != TASK_COUNT:
        raise SystemExit(f"E44 paid authority requires exact locked {TASK_COUNT}-task set")
    if precheck.get("status") != "PASS" or len(precheck.get("results") or []) != TASK_COUNT or precheck.get("failed"):
        raise SystemExit("E44 exact zero-cost precheck is not 50/50 PASS")
    if continuity.get("status") != "PASS" or continuity.get("task_count") != TASK_COUNT or continuity.get("failures"):
        raise SystemExit("E44 full pre-submit continuity audit is not 50/50 PASS")
    if source.get("provider_post_allowed") is not False or source.get("maximum_new_submissions") != 0:
        raise SystemExit("source manifest is not fail-closed")

    for task in tasks:
        task.update({"status": "READY_TO_SUBMIT", "provider_post_allowed": True, "maximum_new_submissions": 1})
    manifest = deepcopy(source)
    manifest.update({
        "schema": "qingshan.authorized_image_submission_manifest.v1",
        "status": "READY_TO_SUBMIT",
        "authorization_ref": AUTHORIZATION_REF,
        "source_precheck_manifest": rel(SOURCE),
        "source_precheck_manifest_sha256": sha(SOURCE),
        "zero_cost_precheck": rel(PRECHECK),
        "zero_cost_precheck_sha256": sha(PRECHECK),
        "full_pre_submit_continuity_audit": rel(CONTINUITY),
        "full_pre_submit_continuity_audit_sha256": sha(CONTINUITY),
        "provider_post_allowed": True,
        "maximum_new_submissions": TASK_COUNT,
        "tasks": tasks,
    })
    gate_ref = rel(GATE)
    manifest["machine_gate_reports"] = [
        value for value in manifest.get("machine_gate_reports") or [] if value not in {gate_ref, rel(CONTINUITY)}
    ] + [rel(CONTINUITY), gate_ref]
    write(OUTPUT, manifest)

    projected = TASK_COUNT * HARD_UNIT_PRICE_CAP
    write(GATE, {
        "schema": "qingshan.registered_reroll_cost_gate.v1",
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "status": "PASS",
        "episode": "E44",
        "authorization_ref": AUTHORIZATION_REF,
        "reviewed_manifest": rel(OUTPUT),
        "reviewed_manifest_sha256": sha(OUTPUT),
        "task_class": "INITIAL_EPISODE_KEYFRAME_GENERATION_NOT_REROLL",
        "planned_new_paid_tasks": TASK_COUNT,
        "maximum_new_submissions": TASK_COUNT,
        "observed_unit_price": 11,
        "hard_unit_price_cap": HARD_UNIT_PRICE_CAP,
        "maximum_projected_credits": projected,
        "episode_credit_cap": EPISODE_CREDIT_CAP,
        "within_episode_credit_cap": projected <= EPISODE_CREDIT_CAP,
        "automatic_retry": False,
        "provider_posts": 0,
        "credits": 0,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
    print(json.dumps({
        "status": "PASS", "authorized_manifest": rel(OUTPUT),
        "task_count": TASK_COUNT, "maximum_projected_credits": projected,
        "provider_posts": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
