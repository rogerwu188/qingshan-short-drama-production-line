#!/usr/bin/env python3
"""Authorize the exact seven E44 middle anchors after zero-cost precheck."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
SOURCE = PROD / "E44_V5_MIDDLE_ANCHOR_SUPPLEMENT_PRECHECK_V1.json"
PRECHECK = QA / "E44_V5_MIDDLE_ANCHOR_SUPPLEMENT_PROVIDER_PRECHECK_V1.json"
OUT = PROD / "E44_V5_MIDDLE_ANCHOR_SUPPLEMENT_AUTHORIZED_V1.json"
GATE = QA / "E44_V5_MIDDLE_ANCHOR_SUPPLEMENT_COST_GUARD_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    precheck = json.loads(PRECHECK.read_text(encoding="utf-8"))
    tasks = deepcopy(source.get("tasks") or [])
    if len(tasks) != 7 or precheck.get("status") != "PASS" or len(precheck.get("results") or []) != 7 or precheck.get("failed"):
        raise ValueError("exact seven-task supplement zero-cost precheck is not PASS")
    gate = {
        "schema": "qingshan.registered_reroll_cost_gate.v1", "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "episode": "E44", "status": "PASS", "task_class": "NEW_MISSING_SEMANTIC_ANCHORS_NOT_REROLLS",
        "planned_new_paid_tasks": 7, "maximum_new_submissions": 7, "observed_unit_price": 11,
        "maximum_projected_credits": 77, "episode_credit_cap": 10000, "within_episode_credit_cap": True,
        "automatic_retry": False, "provider_posts": 0, "credits": 0,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    for task in tasks:
        task.update({"status": "READY_TO_SUBMIT", "provider_post_allowed": True, "maximum_new_submissions": 1})
    payload = deepcopy(source)
    payload.update({
        "schema": "qingshan.authorized_image_submission_manifest.v1", "status": "READY_TO_SUBMIT",
        "authorization_ref": "ROGER-20260828-CONTINUE-E44-PRODUCTION",
        "provider_post_allowed": True, "maximum_new_submissions": 7,
        "zero_cost_precheck": rel(PRECHECK), "zero_cost_precheck_sha256": sha(PRECHECK),
        "tasks": tasks,
    })
    payload["machine_gate_reports"] = [*source["machine_gate_reports"], rel(PRECHECK), rel(GATE)]
    write(OUT, payload)
    gate.update({"reviewed_manifest": rel(OUT), "reviewed_manifest_sha256": sha(OUT)})
    write(GATE, gate)
    print(json.dumps({"status": "AUTHORIZED", "tasks": 7, "maximum_projected_credits": 77, "out": rel(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
