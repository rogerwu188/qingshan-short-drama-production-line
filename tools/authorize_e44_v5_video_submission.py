#!/usr/bin/env python3
"""Authorize exactly the E44 V5 video manifest that passed all prechecks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_preproduction_20260828"
SOURCE = PROD / "E44_V5_TRANSACTIONAL_VIDEO_MANIFEST_PRECHECK_V1.json"
PRECHECK = QA / "E44_V5_VIDEO_PROVIDER_PRECHECK_V1.json"
CREATIVE_QA = QA / "E44_V5_VIDEO_PROMPT_FULL_CREATIVE_CONTINUITY_QA_V1.json"
COST = QA / "E44_V5_VIDEO_COST_GUARD_V1.json"
OUT = PROD / "E44_V5_TRANSACTIONAL_VIDEO_MANIFEST_AUTHORIZED_V1.json"


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
    creative = json.loads(CREATIVE_QA.read_text(encoding="utf-8"))
    source_sha = sha(SOURCE)
    if (
        precheck.get("status") != "PASS"
        or precheck.get("precheck_pass") != 25
        or precheck.get("failed") != 0
        or precheck.get("manifest_sha256") != source_sha
    ):
        raise ValueError("exact E44 video manifest did not pass 25/25 zero-cost provider precheck")
    if creative.get("status") != "PASS" or creative.get("manifest_sha256") != source_sha:
        raise ValueError("exact E44 video manifest did not pass full creative continuity QA")
    projected = int(source["runtime_seconds"]) * 25
    cost = {
        "schema": "qingshan.video_cost_guard.v2_historical_upper_bound",
        "episode": "E44",
        "production_version": 5,
        "status": "PASS",
        "task_count": 25,
        "runtime_seconds": 180,
        "model": "seedance-2.0-pro",
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "conservative_rate_upper_bound_credits_per_second": 25,
        "maximum_projected_credits": projected,
        "episode_cap_credits": 6000,
        "within_cap": projected <= 6000,
        "precheck_ref": rel(PRECHECK),
        "precheck_sha256": sha(PRECHECK),
        "creative_qa_ref": rel(CREATIVE_QA),
        "creative_qa_sha256": sha(CREATIVE_QA),
        "note": "Safety ceiling only; actual net spend is reconciled from authoritative Pay/Refund ledger rows.",
    }
    if not cost["within_cap"]:
        raise ValueError("E44 video cost guard exceeds episode cap")
    write(COST, cost)
    source["schema"] = "qingshan.authorized_giggle_video_transaction_manifest.v2_full_creative_contract"
    source["provider_post_allowed"] = True
    source["authorization_ref"] = "ROGER-20260828-CONTINUE-E44+DIRECT-PUBLISH-NO-PER-RELEASE-REVIEW"
    source["authorization_binding"] = {
        "source_precheck_manifest": rel(SOURCE),
        "source_precheck_manifest_sha256": source_sha,
        "zero_cost_precheck": rel(PRECHECK),
        "zero_cost_precheck_sha256": sha(PRECHECK),
        "full_creative_continuity_qa": rel(CREATIVE_QA),
        "full_creative_continuity_qa_sha256": sha(CREATIVE_QA),
        "cost_guard": rel(COST),
        "cost_guard_sha256": sha(COST),
    }
    source["machine_gate_reports"] = [
        *source["machine_gate_reports"], rel(PRECHECK), rel(CREATIVE_QA), rel(COST),
    ]
    for task in source["tasks"]:
        task["provider_post_allowed"] = True
    write(OUT, source)
    print(json.dumps({
        "status": "AUTHORIZED", "tasks": len(source["tasks"]),
        "maximum_projected_credits": projected, "manifest": rel(OUT), "sha256": sha(OUT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
