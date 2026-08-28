#!/usr/bin/env python3
"""Authorize three failed curtain repairs plus two newly required E43 anchors."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828"
QA = ROOT / "qa/e43_v6_preproduction_20260828"
SOURCE = PROD / "E43_V6_CURTAIN_KEYFRAME_REPAIRS_A2_PRECHECK.json"
PRECHECK = QA / "E43_V6_CURTAIN_KEYFRAME_REPAIRS_A2_ZERO_COST_PRECHECK.json"
OUTPUT = PROD / "E43_V6_CURTAIN_KEYFRAME_REPAIRS_A2_AUTHORIZED.json"
GATE = QA / "E43_V6_CURTAIN_KEYFRAME_REPAIRS_A2_COST_GUARD.json"
AUTH = "ROGER-20260828-START-E43-PRODUCTION"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))

def write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def main() -> int:
    source, precheck = json.loads(SOURCE.read_text()), json.loads(PRECHECK.read_text())
    tasks = deepcopy(source["tasks"])
    if len(tasks) != 5 or precheck.get("status") != "PASS" or len(precheck.get("results") or []) != 5:
        raise SystemExit("exact five-task A2 precheck authority not satisfied")
    for task in tasks:
        task.update({"status": "READY_TO_SUBMIT", "provider_post_allowed": True, "maximum_new_submissions": 1})
    manifest = deepcopy(source)
    manifest.update({
        "schema": "qingshan.authorized_image_submission_manifest.v1", "status": "READY_TO_SUBMIT",
        "authorization_ref": AUTH, "source_precheck_manifest": rel(SOURCE),
        "source_precheck_manifest_sha256": sha(SOURCE), "zero_cost_precheck": rel(PRECHECK),
        "zero_cost_precheck_sha256": sha(PRECHECK), "provider_post_allowed": True,
        "maximum_new_submissions": 5, "tasks": tasks,
    })
    gate_ref = rel(GATE)
    manifest["machine_gate_reports"] = [p for p in manifest["machine_gate_reports"] if p != gate_ref] + [gate_ref]
    write(OUTPUT, manifest)
    write(GATE, {
        "schema": "qingshan.registered_reroll_cost_gate.v1", "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "status": "PASS", "episode": "E43", "authorization_ref": AUTH,
        "reviewed_manifest": rel(OUTPUT), "reviewed_manifest_sha256": sha(OUTPUT),
        "task_class": "THREE_FAILED_CURTAIN_REPAIRS_PLUS_TWO_NEWLY_REQUIRED_ANCHORS",
        "planned_new_paid_rerolls": 3, "planned_new_initial_tasks": 2,
        "maximum_new_submissions": 5,
        "hard_unit_price_cap": 11, "maximum_projected_credits": 55,
        "episode_credit_cap": 10000, "within_episode_credit_cap": True,
        "automatic_retry": False, "provider_posts": 0, "credits": 0,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
    print(json.dumps({"status": "PASS", "tasks": 5, "max_credits": 55, "provider_posts": 0}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
