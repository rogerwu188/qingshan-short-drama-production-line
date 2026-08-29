#!/usr/bin/env python3
"""Authorize only the exact E43 v6 batch that passed zero-cost precheck."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828"
QA = ROOT / "qa/e43_v6_preproduction_20260828"
SOURCE = PROD / "E43_V6_TRANSACTIONAL_VIDEO_MANIFEST_PRECHECK_V1.json"
PRECHECK = QA / "E43_V6_VIDEO_ZERO_COST_PRECHECK_V1.json"
COST = QA / "E43_V6_VIDEO_COST_GUARD_V1.json"
OUT = PROD / "E43_V6_TRANSACTIONAL_VIDEO_MANIFEST_AUTHORIZED_V1.json"
TASK_COUNT = 26
RUNTIME_SECONDS = 180
CONSERVATIVE_RATE_UPPER_BOUND = 25
EPISODE_CAP = 6000


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    precheck = json.loads(PRECHECK.read_text(encoding="utf-8"))
    if len(source.get("tasks") or []) != TASK_COUNT or int(source.get("runtime_seconds") or 0) != RUNTIME_SECONDS:
        raise ValueError("E43 v6 source manifest is not the exact 26-unit, 180-second batch")
    if precheck.get("status") != "PASS" or precheck.get("precheck_pass") != TASK_COUNT or precheck.get("failed") != 0:
        raise ValueError("exact E43 v6 manifest did not pass 26/26 zero-cost precheck")
    if precheck.get("manifest_sha256") != sha(SOURCE):
        raise ValueError("zero-cost precheck does not bind the current E43 v6 manifest SHA")
    if (precheck.get("authoritative_production_gate") or {}).get("status") != "PASS":
        raise ValueError("authoritative production video gate is not PASS")

    projected = RUNTIME_SECONDS * CONSERVATIVE_RATE_UPPER_BOUND
    cost = {
        "schema": "qingshan.video_cost_guard.v2_historical_upper_bound",
        "episode": "E43",
        "production_version": 6,
        "status": "PASS" if projected <= EPISODE_CAP else "FAIL",
        "task_count": TASK_COUNT,
        "runtime_seconds": RUNTIME_SECONDS,
        "model": "seedance-2.0-pro",
        "conservative_rate_upper_bound_credits_per_second": CONSERVATIVE_RATE_UPPER_BOUND,
        "maximum_projected_credits": projected,
        "episode_cap_credits": EPISODE_CAP,
        "within_cap": projected <= EPISODE_CAP,
        "precheck_ref": rel(PRECHECK),
        "precheck_sha256": sha(PRECHECK),
        "note": "Safety ceiling only. Actual spend is reconciled from authoritative Pay/Refund ledger rows.",
    }
    if not cost["within_cap"]:
        raise ValueError("E43 v6 cost guard exceeds episode cap")
    write(COST, cost)

    source["schema"] = "qingshan.authorized_giggle_video_transaction_manifest.v2_complete_creative_contract"
    source["provider_post_allowed"] = True
    source["authorization_ref"] = (
        "ROGER-20260828-START-E43+PLOT-DRIVEN-TRANSITIONS+STRICT-PRE-SUBMIT-CONTINUITY-QA"
        "+TECHNICAL-BASIC-PLOT-POST-QA+NO-PER-RELEASE-REVIEW"
    )
    source["authorization_binding"] = {
        "source_precheck_manifest": rel(SOURCE),
        "source_precheck_manifest_sha256": sha(SOURCE),
        "zero_cost_precheck": rel(PRECHECK),
        "zero_cost_precheck_sha256": sha(PRECHECK),
        "cost_guard": rel(COST),
        "cost_guard_sha256": sha(COST),
    }
    source["machine_gate_reports"] = [*source["machine_gate_reports"], rel(PRECHECK), rel(COST)]
    for task in source["tasks"]:
        task["provider_post_allowed"] = True
    write(OUT, source)
    print(json.dumps({
        "status": "AUTHORIZED",
        "tasks": len(source["tasks"]),
        "maximum_projected_credits": projected,
        "manifest": rel(OUT),
        "sha256": sha(OUT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
