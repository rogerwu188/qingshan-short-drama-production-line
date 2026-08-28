#!/usr/bin/env python3
"""Authorize the exact S10-06 A2 image retry after zero-cost precheck."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
SOURCE = PROD / "E44_V5_S10_06_MIDDLE_ANCHOR_A2_PRECHECK_V1.json"
PRECHECK = QA / "E44_V5_S10_06_MIDDLE_ANCHOR_A2_ZERO_COST_PRECHECK_V1.json"
OUT = PROD / "E44_V5_S10_06_MIDDLE_ANCHOR_A2_AUTHORIZED_V1.json"
GATE = QA / "E44_V5_S10_06_MIDDLE_ANCHOR_A2_COST_GUARD_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    precheck = json.loads(PRECHECK.read_text(encoding="utf-8"))
    if (
        precheck.get("status") != "PASS"
        or precheck.get("precheck_pass") != 1
        or precheck.get("failed")
        or len(source.get("tasks") or []) != 1
    ):
        raise ValueError("S10-06 A2 exact zero-cost precheck is not PASS")
    task = copy.deepcopy(source["tasks"][0])
    task.update({
        "status": "READY_TO_SUBMIT",
        "provider_post_allowed": True,
        "maximum_new_submissions": 1,
    })
    payload = copy.deepcopy(source)
    payload.update({
        "schema": "qingshan.authorized_image_content_retry_manifest.v1",
        "status": "READY_TO_SUBMIT",
        "provider_post_allowed": True,
        "maximum_new_submissions": 1,
        "authorization_binding": {
            "source_precheck_manifest": rel(SOURCE),
            "source_precheck_manifest_sha256": sha(SOURCE),
            "zero_cost_precheck": rel(PRECHECK),
            "zero_cost_precheck_sha256": sha(PRECHECK),
        },
        "tasks": [task],
    })
    payload["machine_gate_reports"] = [*(source.get("machine_gate_reports") or []), rel(PRECHECK), rel(GATE)]
    write(OUT, payload)
    gate = {
        "schema": "qingshan.registered_reroll_cost_gate.v1",
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "episode": "E44",
        "status": "PASS",
        "task_class": "PROVIDER_HEALTHY_IMAGE_CONTENT_RETRY_ATTEMPT_2",
        "planned_new_paid_tasks": 1,
        "maximum_new_submissions": 1,
        "observed_unit_price": 11,
        "maximum_projected_credits": 11,
        "episode_credit_cap": 10000,
        "within_episode_credit_cap": True,
        "automatic_retry": False,
        "provider_posts": 0,
        "credits": 0,
        "reviewed_manifest": rel(OUT),
        "reviewed_manifest_sha256": sha(OUT),
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    write(GATE, gate)
    print(json.dumps({
        "status": "AUTHORIZED",
        "tasks": 1,
        "maximum_projected_credits": 11,
        "out": rel(OUT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
