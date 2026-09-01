#!/usr/bin/env python3
"""Authorize only the user-approved E48 VU011 official-Ref2VA probe."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e48_v5_20260830"
QA = ROOT / "qa/e48_v5_h3_a4_official_ref2va"
SOURCE = PROD / "E48_V5_H3_A4_OFFICIAL_REF2VA_VU011_PROBE_V1.json"
PRECHECK = QA / "E48_V5_H3_A4_VU011_PROBE_ZERO_COST_PRECHECK_V1.json"
OUT = PROD / "E48_V5_H3_A4_OFFICIAL_REF2VA_VU011_PROBE_AUTHORIZED_V1.json"
COST = QA / "E48_V5_H3_A4_VU011_PROBE_COST_OVERRIDE_V1.json"


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
    if precheck.get("status") != "PASS" or precheck.get("precheck_pass") != 1 or precheck.get("failed") != 0:
        raise RuntimeError("E48 VU011 official Ref2VA zero-cost precheck is not PASS")
    if precheck.get("manifest_sha256") != sha(SOURCE):
        raise RuntimeError("E48 VU011 official Ref2VA precheck SHA binding mismatch")
    tasks = manifest.get("tasks") or []
    if len(tasks) != 1 or tasks[0].get("unit_id") != "E48-VU-011":
        raise RuntimeError("probe authorization scope must be exactly E48-VU-011")
    expected = 14 * int(tasks[0]["duration_seconds"]) + 6
    cost = {
        "schema": "qingshan.video_cost_guard.user_override.v1",
        "episode": "E48",
        "status": "PASS_USER_EXPLICIT_OVERRIDE",
        "scope": ["E48-VU-011"],
        "expected_probe_credits": expected,
        "authoritative_video_credits_before_a4": 4476,
        "projected_video_credits_after_probe": 4476 + expected,
        "prior_episode_video_cap_credits": 4500,
        "cap_override": True,
        "cap_override_ref": "ROGER-2026-08-30-E48-FIVE-UNIT-OFFICIAL-REF2VA-REDO",
        "reason": "MiniMax official provider-schema migration requested after three prompts used invalid Ref2VA grammar.",
        "precheck_ref": rel(PRECHECK),
        "precheck_sha256": sha(PRECHECK),
    }
    write(COST, cost)
    manifest["schema"] = "qingshan.authorized_giggle_h3_official_ref2va_probe.v1"
    manifest["status"] = "AUTHORIZED_ONE_UNIT_PROBE"
    manifest["provider_post_allowed"] = True
    manifest["authorization_ref"] = "ROGER-2026-08-30-E48-FIVE-UNIT-OFFICIAL-REF2VA-REDO"
    manifest["authorization_binding"] = {
        "source_precheck_manifest": rel(SOURCE),
        "source_precheck_manifest_sha256": sha(SOURCE),
        "zero_cost_precheck": rel(PRECHECK),
        "zero_cost_precheck_sha256": sha(PRECHECK),
        "cost_override": rel(COST),
        "cost_override_sha256": sha(COST),
    }
    for task in tasks:
        task["provider_post_allowed"] = True
    write(OUT, manifest)
    print(json.dumps({
        "status": "AUTHORIZED_ONE_UNIT_PROBE",
        "tasks": 1,
        "expected_credits": expected,
        "manifest": rel(OUT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
