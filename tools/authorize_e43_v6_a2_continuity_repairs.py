#!/usr/bin/env python3
"""Authorize the exact prechecked five-unit E43 v6 A2 repair batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828"
QA = ROOT / "qa/e43_v6_a2_continuity_repairs"
SOURCE = PROD / "E43_V6_A2_CONTINUITY_REPAIRS_PRECHECK_V1.json"
PRECHECK = QA / "E43_V6_A2_ZERO_COST_PRECHECK_V1.json"
COST = QA / "E43_V6_A2_COST_GUARD_V1.json"
OUT = PROD / "E43_V6_A2_CONTINUITY_REPAIRS_AUTHORIZED_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    manifest = json.loads(SOURCE.read_text(encoding="utf-8"))
    precheck = json.loads(PRECHECK.read_text(encoding="utf-8"))
    if (
        precheck.get("status") != "PASS"
        or precheck.get("precheck_pass") != 5
        or precheck.get("failed") != 0
        or precheck.get("manifest_sha256") != sha(SOURCE)
    ):
        raise ValueError("exact five-task zero-cost precheck binding failed")
    projected = int(manifest["runtime_seconds"]) * 25
    cost = {
        "schema": "qingshan.video_cost_guard.v2_historical_upper_bound",
        "episode": "E43",
        "production_version": 6,
        "repair_scope": manifest["repair_scope"],
        "status": "PASS",
        "task_count": 5,
        "runtime_seconds": int(manifest["runtime_seconds"]),
        "model": "seedance-2.0-pro",
        "conservative_rate_upper_bound_credits_per_second": 25,
        "maximum_projected_credits": projected,
        "repair_cap_credits": 1000,
        "within_cap": projected <= 1000,
        "precheck_ref": rel(PRECHECK),
        "precheck_sha256": sha(PRECHECK),
        "note": "Safety ceiling only; actual spend is reconciled from authoritative Pay/Refund rows.",
    }
    if not cost["within_cap"]:
        raise ValueError("E43 A2 repair cost guard exceeded")
    write(COST, cost)
    manifest["schema"] = "qingshan.authorized_giggle_video_content_retry_manifest.v2_internal_continuity"
    manifest["provider_post_allowed"] = True
    manifest["authorization_ref"] = "ROGER-20260828-UPGRADE-PIPELINE-THEN-REPAIR-CURRENT-FIVE-E43-UNITS+A2"
    manifest["authorization_binding"] = {
        "source_precheck_manifest": rel(SOURCE),
        "source_precheck_manifest_sha256": sha(SOURCE),
        "zero_cost_precheck": rel(PRECHECK),
        "zero_cost_precheck_sha256": sha(PRECHECK),
        "cost_guard": rel(COST),
        "cost_guard_sha256": sha(COST),
    }
    manifest["machine_gate_reports"] = [*manifest["machine_gate_reports"], rel(PRECHECK), rel(COST)]
    for task in manifest["tasks"]:
        task["provider_post_allowed"] = True
    write(OUT, manifest)
    report = {
        "status": "AUTHORIZED",
        "tasks": 5,
        "maximum_projected_credits": projected,
        "manifest": rel(OUT),
        "manifest_sha256": sha(OUT),
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
