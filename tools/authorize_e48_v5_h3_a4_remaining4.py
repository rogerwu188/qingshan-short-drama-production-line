#!/usr/bin/env python3
"""Authorize four E48 A4 units only after the official-Ref2VA probe passes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e48_v5_20260830"
QA = ROOT / "qa/e48_v5_h3_a4_official_ref2va"
SOURCE = PROD / "E48_V5_H3_A4_OFFICIAL_REF2VA_REMAINING4_HELD_V1.json"
PRECHECK = QA / "E48_V5_H3_A4_REMAINING4_ZERO_COST_PRECHECK_V1.json"
PROBE_QA = QA / "E48_V5_H3_A4_VU011_PROBE_FINAL_QA_V1.json"
OUT = PROD / "E48_V5_H3_A4_OFFICIAL_REF2VA_REMAINING4_AUTHORIZED_V1.json"
COST = QA / "E48_V5_H3_A4_REMAINING4_COST_OVERRIDE_V1.json"


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
    probe = json.loads(PROBE_QA.read_text(encoding="utf-8"))
    if precheck.get("status") != "PASS" or precheck.get("precheck_pass") != 4 or precheck.get("failed") != 0:
        raise RuntimeError("remaining-four zero-cost precheck is not 4/4 PASS")
    if precheck.get("manifest_sha256") != sha(SOURCE):
        raise RuntimeError("remaining-four precheck SHA binding mismatch")
    if probe.get("status") != "PASS" or probe.get("release_decision", "").split(";")[0] != "PASS_PROBE":
        raise RuntimeError("official Ref2VA probe QA is not PASS")
    tasks = manifest.get("tasks") or []
    expected_units = {"E48-VU-021", "E48-VU-023", "E48-VU-024", "E48-VU-027"}
    if len(tasks) != 4 or {task.get("unit_id") for task in tasks} != expected_units:
        raise RuntimeError("remaining-four authorization scope mismatch")
    expected = sum(14 * int(task["duration_seconds"]) + 6 for task in tasks)
    cost = {
        "schema": "qingshan.video_cost_guard.user_override.v1",
        "episode": "E48",
        "status": "PASS_USER_EXPLICIT_OVERRIDE",
        "scope": sorted(expected_units),
        "expected_remaining4_credits": expected,
        "authoritative_video_credits_before_a4": 4476,
        "a4_probe_credits": 90,
        "projected_video_credits_after_all_a4": 4476 + 90 + expected,
        "prior_episode_video_cap_credits": 4500,
        "cap_override": True,
        "cap_override_ref": "ROGER-2026-08-30-E48-FIVE-UNIT-OFFICIAL-REF2VA-REDO",
        "reason": "User explicitly authorized one fourth attempt after migrating H3 prompts to the official MiniMax Ref2VA schema.",
        "probe_qa_ref": rel(PROBE_QA),
        "probe_qa_sha256": sha(PROBE_QA),
        "precheck_ref": rel(PRECHECK),
        "precheck_sha256": sha(PRECHECK),
    }
    write(COST, cost)
    manifest["schema"] = "qingshan.authorized_giggle_h3_official_ref2va_remaining4.v1"
    manifest["status"] = "AUTHORIZED_REMAINING_FOUR_AFTER_PROBE_PASS"
    manifest["provider_post_allowed"] = True
    manifest["authorization_ref"] = "ROGER-2026-08-30-E48-FIVE-UNIT-OFFICIAL-REF2VA-REDO"
    manifest["authorization_binding"] = {
        "source_manifest": rel(SOURCE),
        "source_manifest_sha256": sha(SOURCE),
        "zero_cost_precheck": rel(PRECHECK),
        "zero_cost_precheck_sha256": sha(PRECHECK),
        "probe_final_qa": rel(PROBE_QA),
        "probe_final_qa_sha256": sha(PROBE_QA),
        "cost_override": rel(COST),
        "cost_override_sha256": sha(COST),
    }
    for task in tasks:
        task["provider_post_allowed"] = True
    write(OUT, manifest)
    print(json.dumps({
        "status": manifest["status"], "tasks": 4,
        "expected_credits": expected, "manifest": rel(OUT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
