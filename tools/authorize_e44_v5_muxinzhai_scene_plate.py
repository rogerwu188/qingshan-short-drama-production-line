#!/usr/bin/env python3
"""Authorize exactly one prechecked E44 Muxinzhai clean scene plate."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
SOURCE = PROD / "E44_V5_MUXINZHAI_SCENE_PLATE_MANIFEST_PRECHECK_V1.json"
PRECHECK = QA / "E44_V5_MUXINZHAI_SCENE_PLATE_PROVIDER_PRECHECK_V1.json"
OUTPUT = PROD / "E44_V5_MUXINZHAI_SCENE_PLATE_MANIFEST_AUTHORIZED_V1.json"
GATE = QA / "E44_V5_MUXINZHAI_SCENE_PLATE_COST_GUARD_V1.json"


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
    if len(tasks) != 1 or tasks[0].get("task_key") != "SCENE-E44-MUXINZHAI-CLEAN-V1":
        raise SystemExit("exact one-task Muxinzhai scene plate set required")
    if precheck.get("status") != "PASS" or precheck.get("precheck_pass") != 1 or precheck.get("failed"):
        raise SystemExit("exact zero-cost scene plate precheck is not PASS")
    tasks[0].update({
        "status": "READY_TO_SUBMIT",
        "provider_post_allowed": True,
        "maximum_new_submissions": 1,
    })
    manifest = deepcopy(source)
    manifest.update({
        "schema": "qingshan.authorized_image_submission_manifest.v1",
        "status": "READY_TO_SUBMIT",
        "authorization_ref": "ROGER-20260828-START-E44-PRODUCTION",
        "source_precheck_manifest": rel(SOURCE),
        "source_precheck_manifest_sha256": sha(SOURCE),
        "zero_cost_precheck": rel(PRECHECK),
        "zero_cost_precheck_sha256": sha(PRECHECK),
        "provider_post_allowed": True,
        "maximum_new_submissions": 1,
        "tasks": tasks,
    })
    gate_ref = rel(GATE)
    manifest["machine_gate_reports"] = [
        value for value in manifest.get("machine_gate_reports") or [] if value != gate_ref
    ] + [gate_ref]
    write(OUTPUT, manifest)
    write(GATE, {
        "schema": "qingshan.registered_reroll_cost_gate.v1",
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "status": "PASS",
        "episode": "E44",
        "authorization_ref": "ROGER-20260828-START-E44-PRODUCTION",
        "reviewed_manifest": rel(OUTPUT),
        "reviewed_manifest_sha256": sha(OUTPUT),
        "task_class": "INITIAL_EPISODE_SCENE_MATERIAL_GENERATION_NOT_REROLL",
        "planned_new_paid_tasks": 1,
        "maximum_new_submissions": 1,
        "observed_unit_price": 11,
        "hard_unit_price_cap": 11,
        "maximum_projected_credits": 11,
        "episode_credit_cap": 10000,
        "within_episode_credit_cap": True,
        "automatic_retry": False,
        "provider_posts": 0,
        "credits": 0,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
    # Gate binds the final authorized-manifest SHA, so write it after the
    # manifest itself and do not mutate the manifest again.
    print(json.dumps({"status": "PASS", "manifest": rel(OUTPUT), "task_count": 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
