#!/usr/bin/env python3
"""Replace only E28 U10-C1 after exact-SHA identity repair passes the tier gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = "E28-CW-U10-C01"
EXPECTED_OLD_SHA = "abf5a6a6c8c8b01a3cc5e871aec80a17161373d2c9586e19ebe349cfc0de3cef"


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load(value: str) -> dict:
    return json.loads(resolve(value).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--harvest", required=True)
    parser.add_argument("--tier-gate", required=True)
    parser.add_argument("--review-result", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--receipt-out", required=True)
    args = parser.parse_args()

    baseline_path = resolve(args.baseline)
    harvest_path = resolve(args.harvest)
    gate_path = resolve(args.tier_gate)
    review_path = resolve(args.review_result)
    baseline = load(args.baseline)
    harvest = load(args.harvest)
    gate = load(args.tier_gate)
    review = load(args.review_result)

    results = [item for item in harvest.get("results", []) if item.get("remote_status") == "completed"]
    if len(results) != 1:
        raise ValueError("identity repair harvest must contain exactly one completed candidate")
    result = results[0]
    rows = gate.get("items", [])
    if gate.get("status") != "PASS" or len(rows) != 1 or rows[0].get("decision") != "PASS":
        raise ValueError("identity repair must pass the tier gate")
    row = rows[0]
    candidate = resolve(result["output_path"])
    candidate_sha = sha256(candidate)
    if candidate_sha != result["sha256"] or candidate_sha != row["candidate_sha256"]:
        raise ValueError("candidate, harvest and tier-gate SHA values do not match")
    review_items = review.get("items", [])
    if len(review_items) != 1:
        raise ValueError("identity review must contain exactly one item")
    analysis = review_items[0].get("capabilities", {}).get("image_analysis", {})
    if analysis.get("candidate_sha256") != candidate_sha or analysis.get("status") != "PASS":
        raise ValueError("image analysis did not pass for the exact candidate SHA")

    final = deepcopy(baseline)
    matches = [slot for slot in final["slots"] if slot.get("internal_shot_id") == TARGET]
    if len(matches) != 1:
        raise ValueError(f"expected one {TARGET} slot")
    slot = matches[0]
    if slot.get("image_sha256") != EXPECTED_OLD_SHA:
        raise ValueError("baseline U10-C1 SHA is not the audited conditional candidate")
    old_snapshot = deepcopy(slot)
    slot.update({
        "image_path": str(candidate),
        "image_sha256": candidate_sha,
        "task_id": result["task_id"],
        "score_100": row["score_100"],
        "minimum_score_100": row["minimum_score_100"],
        "production_resolution": "IDENTITY_REPAIR_R1_TIER_GATE_PASS",
        "qa_decision": "PASS",
    })
    paths = [item["image_path"] for item in final["slots"]]
    hashes = [item["image_sha256"] for item in final["slots"]]
    if len(final["slots"]) != 38 or len(set(paths)) != 38 or len(set(hashes)) != 38:
        raise ValueError("final map must preserve 38 distinct exact images")
    final.update({
        "schema": "qingshan.e28.internal_state_still_plan.v6.final",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_FOR_VIDEO_REFERENCE_CONSUMPTION",
        "source_state_plan": {"path": str(baseline_path), "sha256": sha256(baseline_path)},
        "u10_c1_identity_repair": {
            "harvest_report": {"path": str(harvest_path), "sha256": sha256(harvest_path)},
            "tier_gate": {"path": str(gate_path), "sha256": sha256(gate_path)},
            "review_result": {"path": str(review_path), "sha256": sha256(review_path)},
            "old_candidate_sha256": EXPECTED_OLD_SHA,
            "new_candidate_sha256": candidate_sha,
        },
        "direct_pass_count": 38,
        "conditional_machine_admission_count": 0,
        "missing_count": 0,
        "duplicate_reference_sha_count": 0,
    })

    out = resolve(args.out)
    receipt_out = resolve(args.receipt_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.e28.u10_c1_identity_replacement_receipt.v1",
        "episode": "E28",
        "status": "PASS",
        "changed_slot_count": 1,
        "unchanged_slot_count": 37,
        "changed_internal_shot_id": TARGET,
        "old_slot": old_snapshot,
        "new_slot": slot,
        "final_map": str(out),
        "final_map_sha256": sha256(out),
        "image_generation_credit": result.get("credit", 11),
        "video_generation_calls": 0,
        "video_generation_credit": 0,
    }
    receipt_out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "changed": 1,
        "unchanged": 37,
        "new_sha256": candidate_sha,
        "out": str(out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
