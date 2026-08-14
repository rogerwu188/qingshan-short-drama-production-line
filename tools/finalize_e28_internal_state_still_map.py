#!/usr/bin/env python3
"""Finalize E28's 38-state still map from exact existing assets and harvested gaps."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load(path: str) -> dict:
    return json.loads(resolve(path).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def key(value: str) -> str:
    value = re.sub(r"-STILL-(?:V|R)\d+$", "", value)
    match = re.fullmatch(r"(.+-U\d+)-C0*(\d+)", value)
    if not match:
        raise ValueError(f"Unsupported internal-shot id: {value}")
    return f"{match.group(1)}-C{int(match.group(2))}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-plan", required=True)
    parser.add_argument("--harvest-report", action="append", required=True)
    parser.add_argument("--tier-gate", required=True)
    parser.add_argument("--review-result", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--admission-out", required=True)
    args = parser.parse_args()

    plan = load(args.state_plan)
    gate = load(args.tier_gate)
    review = load(args.review_result)
    gate_rows = {key(item["shot_id"]): item for item in gate["items"]}

    harvested = {}
    harvest_sources = []
    for name in args.harvest_report:
        report_path = resolve(name)
        report = load(name)
        if not report.get("all_completed"):
            raise ValueError(f"Incomplete harvest: {report_path}")
        harvest_sources.append({"path": str(report_path), "sha256": sha256(report_path)})
        for item in report["results"]:
            if item.get("remote_status") != "completed":
                continue
            harvested[key(item["task_key"])] = item

    review_by_sha = {}
    for item in review["items"]:
        analysis = item.get("capabilities", {}).get("image_analysis", {})
        candidate_sha = analysis.get("candidate_sha256")
        if candidate_sha:
            review_by_sha[candidate_sha] = item

    final = deepcopy(plan)
    final["schema"] = "qingshan.e28.internal_state_still_plan.v5.final"
    final["status"] = "READY_FOR_VIDEO_REFERENCE_CONSUMPTION"
    final["recorded_at"] = datetime.now(timezone.utc).isoformat()
    final["source_state_plan"] = {
        "path": str(resolve(args.state_plan)),
        "sha256": sha256(resolve(args.state_plan)),
    }
    final["source_harvest_reports"] = harvest_sources
    final["tier_gate"] = {
        "path": str(resolve(args.tier_gate)),
        "sha256": sha256(resolve(args.tier_gate)),
    }

    admission = None
    for slot in final["slots"]:
        slot_key = key(slot["internal_shot_id"])
        if slot["coverage"] == "EXACT":
            path = resolve(slot["image_path"])
            if not path.is_file() or sha256(path) != slot["image_sha256"]:
                raise ValueError(f"Existing asset integrity failure: {slot_key}")
            slot["qa_decision"] = "PREVIOUSLY_ACCEPTED_EXACT"
            continue
        result = harvested.get(slot_key)
        gate_row = gate_rows.get(slot_key)
        if not result or not gate_row:
            raise ValueError(f"Missing harvested/gate evidence: {slot_key}")
        path = resolve(result["output_path"])
        actual_sha = sha256(path)
        if actual_sha != result["sha256"] or actual_sha != gate_row["candidate_sha256"]:
            raise ValueError(f"Harvest/gate SHA mismatch: {slot_key}")
        slot["coverage"] = "EXACT"
        slot["image_path"] = str(path)
        slot["image_sha256"] = actual_sha
        slot["task_id"] = result["task_id"]
        slot["score_100"] = gate_row["score_100"]
        slot["minimum_score_100"] = gate_row["minimum_score_100"]
        if gate_row["decision"] == "PASS":
            slot["production_resolution"] = "GENERATED_ONCE_TIER_GATE_PASS"
            slot["qa_decision"] = "PASS"
            continue
        if slot_key != "E28-CW-U10-C1":
            raise ValueError(f"Unexpected failed state: {slot_key}")
        review_item = review_by_sha[actual_sha]
        slot["production_resolution"] = "CONDITIONAL_MACHINE_ADMISSION"
        slot["qa_decision"] = "CONDITIONAL_MACHINE_ADMISSION"
        admission = {
            "schema": "qingshan.conditional_machine_admission.v1",
            "episode": "E28",
            "state_id": slot["state_id"],
            "internal_shot_id": slot["internal_shot_id"],
            "source_shot_id": slot["source_shot_id"],
            "decision": "CONDITIONAL_MACHINE_ADMISSION",
            "candidate_path": str(path),
            "candidate_sha256": actual_sha,
            "original_qa_status": gate_row["decision"],
            "original_score_100": gate_row["score_100"],
            "required_score_100": gate_row["minimum_score_100"],
            "preserved_failures": gate_row["hard_fact_failures"],
            "selection_reason": (
                "Among available candidates this is the only image that preserves the ice-break escape event, "
                "snow-night scene, motion direction, anatomy, text safety and technical integrity. Identity is "
                "weakened by a same-body motion residual, but no extra independent person is asserted."
            ),
            "machine_confidence": 0.74,
            "rollback_point": str(resolve(args.state_plan)),
            "replacement_condition": (
                "Replace only if a future already-paid or explicitly approved candidate preserves the same event "
                "and passes canonical identity at 80 or above; do not auto-regenerate."
            ),
            "review_id": review_item["review_id"],
            "review_result": str(resolve(args.review_result)),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }

    if admission is None:
        raise RuntimeError("Expected U10-C1 conditional admission was not recorded")
    paths = [slot["image_path"] for slot in final["slots"]]
    hashes = [slot["image_sha256"] for slot in final["slots"]]
    if len(final["slots"]) != 38 or len(set(paths)) != 38 or len(set(hashes)) != 38:
        raise ValueError("Final map must contain 38 distinct state images and SHA-256 values")
    final["final_state_count"] = 38
    final["exact_distinct_image_count"] = 38
    final["direct_pass_count"] = 37
    final["conditional_machine_admission_count"] = 1
    final["missing_count"] = 0
    final["duplicate_reference_sha_count"] = 0

    out = resolve(args.out)
    admission_out = resolve(args.admission_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    admission_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    admission_out.write_text(json.dumps(admission, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": final["status"],
        "states": 38,
        "direct_pass": 37,
        "conditional": 1,
        "out": str(out),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
