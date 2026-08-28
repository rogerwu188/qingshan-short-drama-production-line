#!/usr/bin/env python3
"""Authorize E44 VU010's exact final A3 retry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_a3_vu010_burned_text"
SOURCE = PROD / "E44_V5_VU010_A3_BURNED_TEXT_PRECHECK_V1.json"
PRECHECK = QA / "E44_V5_VU010_A3_ZERO_COST_PRECHECK_V1.json"
COST = QA / "E44_V5_VU010_A3_COST_GUARD_V1.json"
OUT = PROD / "E44_V5_VU010_A3_BURNED_TEXT_AUTHORIZED_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def main() -> int:
    manifest, precheck = json.loads(SOURCE.read_text(encoding="utf-8")), json.loads(PRECHECK.read_text(encoding="utf-8"))
    if precheck.get("status") != "PASS" or precheck.get("precheck_pass") != 1 or precheck.get("failed") != 0 or precheck.get("manifest_sha256") != sha(SOURCE):
        raise RuntimeError("VU010 A3 exact precheck binding failed")
    projected = int(manifest["runtime_seconds"]) * 25
    cost = {
        "schema": "qingshan.video_cost_guard.v2_historical_upper_bound",
        "episode": "E44",
        "production_version": 5,
        "status": "PASS" if projected <= 200 else "FAIL",
        "task_count": 1,
        "runtime_seconds": int(manifest["runtime_seconds"]),
        "model": "seedance-2.0-pro",
        "maximum_projected_credits": projected,
        "repair_cap_credits": 200,
        "within_cap": projected <= 200,
        "precheck_ref": rel(PRECHECK),
        "precheck_sha256": sha(PRECHECK),
    }
    if not cost["within_cap"]:
        raise RuntimeError("VU010 A3 cost guard failed")
    COST.parent.mkdir(parents=True, exist_ok=True)
    COST.write_text(json.dumps(cost, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["provider_post_allowed"] = True
    manifest["authorization_ref"] += "+CONTENT_RETRY_FINAL_ATTEMPT_3"
    manifest["authorization_binding"] = {
        "source_precheck_manifest": rel(SOURCE),
        "source_precheck_manifest_sha256": sha(SOURCE),
        "zero_cost_precheck": rel(PRECHECK),
        "zero_cost_precheck_sha256": sha(PRECHECK),
        "cost_guard": rel(COST),
        "cost_guard_sha256": sha(COST),
    }
    manifest["machine_gate_reports"] = [*manifest["machine_gate_reports"], rel(PRECHECK), rel(COST)]
    manifest["tasks"][0]["provider_post_allowed"] = True
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "AUTHORIZED", "manifest": rel(OUT), "maximum_projected_credits": projected}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
