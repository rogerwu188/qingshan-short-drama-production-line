#!/usr/bin/env python3
"""Build SHA-bound E20 v2 cutpoint and source-admission skeletons."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def distribute(items: list[str], count: int) -> list[list[str]]:
    buckets = [[] for _ in range(count)]
    for index, item in enumerate(items):
        buckets[min(count - 1, index * count // max(1, len(items)))].append(item)
    return buckets


def build(
    beat_sheet: dict[str, Any],
    duration: dict[str, Any],
    performance: dict[str, Any],
    sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if duration.get("beat_sheet_sha256") != sha256:
        raise ValueError("duration beat_sheet_sha256 mismatch")
    if performance.get("beat_sheet_sha256") != sha256:
        raise ValueError("performance beat_sheet_sha256 mismatch")

    performance_by_id = {row["dia_id"]: row for row in performance["lines"]}
    units: list[dict[str, Any]] = []
    for beat in duration["beats"]:
        dialogue_buckets = distribute(beat["dialogue_ids"], len(beat["units"]))
        for unit, dialogue_ids in zip(beat["units"], dialogue_buckets):
            units.append(
                {
                    "unit_id": unit["unit_id"],
                    "beat_id": beat["beat_id"],
                    "coverage_unit": unit["coverage_unit"],
                    "budget_seconds": unit["budget_seconds"],
                    "dialogue_ids": dialogue_ids,
                    "source_id": None,
                    "source_sequence_id": None,
                }
            )

    common = {
        "episode": "E20",
        "created_at_pdt": "2026-07-16 12:0x",
        "review_ref": "CL2X-186",
        "beat_sheet_sha256": sha256,
        "runtime_target_seconds": beat_sheet["runtime_target_seconds"]["target"],
        "unit_count": len(units),
        "dialogue_count": len(beat_sheet["dialogue_draft"]),
        "generation_allowed": False,
        "source_lock_allowed": False,
        "edit_allowed": False,
        "submittable": False,
        "provider_payload": None,
    }
    cutpoint = {
        "schema": "qingshan.timeline_cutpoint_contract.v2",
        **common,
        "status": "V2_LOCAL_CUTPOINT_CONTRACT_NO_SOURCE_ASSIGNMENT",
        "duration_skeleton": "configs/e20_timeline_duration_skeleton_v2_20260716.json",
        "coverage_contract": "configs/e20_coverage_plan_v2_20260716.json",
        "global_cut_rules": [
            "Every dialogue line remains complete before a listener reaction or spatial cut.",
            "Unit budgets require internal action boundaries and never authorize a held single shot.",
            "No speed change, stretch, freeze, loop or replay may reconcile timing.",
            "No source assignment, lock, edit, package or release is authorized."
        ],
        "units": units,
        "checks": {
            "unit_total_seconds": sum(row["budget_seconds"] for row in units),
            "all_source_ids_null": all(row["source_id"] is None for row in units),
            "dialogue_ids_unique_and_complete": len({dia for row in units for dia in row["dialogue_ids"]})
            == len(beat_sheet["dialogue_draft"]),
        },
    }

    admission_units = []
    for unit in units:
        blocked = [
            dia
            for dia in unit["dialogue_ids"]
            if performance_by_id[dia].get("voice_gate")
        ]
        admission_units.append(
            {
                **unit,
                "required_voice_gate_dialogue_ids": blocked,
                "admission_state": (
                    "BLOCKED_VOICE_AND_CANDIDATE_QA"
                    if blocked
                    else "WAITING_CANDIDATE_QA"
                ),
            }
        )
    admission = {
        "schema": "qingshan.source_admission_manifest_skeleton.v2",
        **common,
        "status": "V2_LOCAL_SOURCE_ADMISSION_ALL_SOURCES_NULL",
        "cutpoint_contract": "configs/e20_timeline_cutpoint_contract_v2_20260716.json",
        "universal_admission_gates": [
            "Candidate maps to exactly one current v2 unit and beat.",
            "Identity, era, geography, prop state and reveal timing pass current visual locks.",
            "Dialogue is complete and uses an approved immutable voice asset.",
            "OCR, cadence, freeze, brightness, motion, sentence and source-span gates pass.",
            "Final lock and edit follow episode, timeline and coverage manifest order."
        ],
        "units": admission_units,
        "checks": {
            "unit_count": len(admission_units),
            "all_source_ids_null": all(row["source_id"] is None for row in admission_units),
            "all_source_sequence_ids_null": all(row["source_sequence_id"] is None for row in admission_units),
            "dialogue_ids_unique_and_complete": len({dia for row in admission_units for dia in row["dialogue_ids"]})
            == len(beat_sheet["dialogue_draft"]),
        },
    }
    return cutpoint, admission


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--duration", required=True)
    parser.add_argument("--performance", required=True)
    parser.add_argument("--cutpoint-out", required=True)
    parser.add_argument("--admission-out", required=True)
    args = parser.parse_args()
    beat_path = Path(args.beat_sheet).resolve()
    raw = beat_path.read_bytes()
    beat_sheet = json.loads(raw)
    duration = json.loads(Path(args.duration).resolve().read_text())
    performance = json.loads(Path(args.performance).resolve().read_text())
    cutpoint, admission = build(
        beat_sheet,
        duration,
        performance,
        hashlib.sha256(raw).hexdigest(),
    )
    for value, payload in ((args.cutpoint_out, cutpoint), (args.admission_out, admission)):
        path = Path(value).resolve()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "PASS_LOCAL_NON_SUBMITTABLE", "unit_count": cutpoint["unit_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
