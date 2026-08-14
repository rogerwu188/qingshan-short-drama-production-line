#!/usr/bin/env python3
"""Finalize E31 anchor counts from harvested visual evidence, not a preset count."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722"
PLAN = PRODUCTION / "E31_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
A1_HARVEST = PRODUCTION / "E31_IMAGE_BATCH_PERFORMANCE_V1_HARVEST.json"
R2_HARVEST = PRODUCTION / "E31_IMAGE_BATCH_ANCHOR_CONTINUITY_REPAIR_V3_HARVEST.json"
QA = ROOT / "qa/e31_performance_stills_20260722/E31_ANCHOR_ADMISSION_V4.json"


def rel(path: str) -> str:
    return str(Path(path).resolve().relative_to(ROOT))


def rows_by_unit(report: dict) -> dict[str, dict]:
    return {
        row["beat_id"]: row
        for row in report["results"]
        if row.get("remote_status") == "completed"
    }


def admitted(row: dict, role: str) -> dict:
    return {
        "role": role,
        "task_key": row["task_key"],
        "path": rel(row["output_path"]),
        "sha256": row["sha256"],
        "status": "PASS",
    }


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    by_unit = {row["unit_id"]: row for row in plan["units"]}
    a1 = rows_by_unit(json.loads(A1_HARVEST.read_text(encoding="utf-8")))
    r2 = rows_by_unit(json.loads(R2_HARVEST.read_text(encoding="utf-8")))
    required = {"E31-CW-U02", "E31-CW-U05", "E31-CW-U10"}
    if not required <= set(a1) or not required <= set(r2):
        raise SystemExit("All A1 and R2 candidates must be harvested before final anchor admission")

    outcomes = {
        "E31-CW-U02": {
            "status": "PASS_TWO_ANCHORS",
            "decision": "A1 and repaired A2 preserve the same principal faces, crowd correspondence, camera direction and lantern/list ownership; the torn-list and crushed-lantern terminal facts justify A2.",
            "failure_history": "Original A2 changed camera and population because A1 was not supplied as a real image reference.",
        },
        "E31-CW-U05": {
            "status": "PASS_TWO_ANCHORS",
            "decision": "A1 and repaired A2 preserve the seated flesh body, room, camera and spirit identity while advancing the separation state; the second entity remains a justified terminal anchor.",
            "failure_history": "Original A2 changed camera and identity presentation because A1 was not supplied as a real image reference.",
        },
        "E31-CW-U10": {
            "status": "PASS_SINGLE_ANCHOR_REEVALUATED",
            "decision": "Admitted A1 already shows the cat warning, both heroes, three distinct ambush origins and the protected list. Repaired A2 introduced a fourth attacker, so A2 is rejected and the unit returns to one anchor instead of forcing another draw.",
            "failure_history": "Both A2 attempts failed population/topology continuity; the latest adds one attacker not present in A1.",
        },
    }

    for unit_id in ("E31-CW-U02", "E31-CW-U05"):
        unit = by_unit[unit_id]
        unit["planned_reference_image_count"] = 2
        unit["reference_image_task_keys"] = [a1[unit_id]["task_key"], r2[unit_id]["task_key"]]
        unit["admitted_reference_images"] = [admitted(a1[unit_id], "A1"), admitted(r2[unit_id], "A2")]
        unit["anchor_count_decision"] = {
            "unit_id": unit_id,
            "planned_reference_image_count": 2,
            "decision": "TWO_ANCHORS_REQUIRED_AND_VISUALLY_ADMITTED",
            "reason": outcomes[unit_id]["decision"],
        }
        unit["keyframe_interpolation_gate"] = {
            "status": "PASS",
            "adjacent_pairs_checked": 1,
            "pair": "A1_TO_REPAIRED_A2",
            "visual_evidence": [a1[unit_id]["sha256"], r2[unit_id]["sha256"]],
        }

    unit_id = "E31-CW-U10"
    unit = by_unit[unit_id]
    unit["planned_reference_image_count"] = 1
    unit["reference_image_task_keys"] = [a1[unit_id]["task_key"]]
    unit["admitted_reference_images"] = [admitted(a1[unit_id], "A1")]
    unit["anchor_count_decision"] = {
        "unit_id": unit_id,
        "planned_reference_image_count": 1,
        "decision": "SINGLE_ANCHOR_SUFFICIENT_POST_HARVEST",
        "reason": outcomes[unit_id]["decision"],
    }
    unit["keyframe_interpolation_gate"] = {
        "status": "PASS",
        "adjacent_pairs_checked": 0,
        "reason": outcomes[unit_id]["decision"],
    }
    unit["rejected_reference_images"] = [
        {
            "task_key": r2[unit_id]["task_key"],
            "path": rel(r2[unit_id]["output_path"]),
            "sha256": r2[unit_id]["sha256"],
            "status": "FAIL_POPULATION_CONTINUITY",
        }
    ]

    plan["planned_reference_image_count"] = sum(
        row["planned_reference_image_count"] for row in plan["units"]
    )
    plan["anchor_admission_report"] = str(QA.relative_to(ROOT))
    plan["anchor_count_gate"] = "qa/e31_performance_preproduction_20260722/E31_VIDEO_UNIT_ANCHOR_COUNT_GATE_V4.json"
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "schema": "qingshan.anchor_admission.v1",
        "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "policy": "FINAL_COUNT_FOLLOWS_MODEL_CAPABILITY_AND_HARVESTED_ACTION_EVIDENCE; NEVER_FORCE_ONE_OR_MULTI",
        "video_unit_count": 20,
        "planned_reference_image_count": plan["planned_reference_image_count"],
        "single_anchor_units": 18,
        "two_anchor_units": 2,
        "outcomes": outcomes,
        "original_fail_preserved": True,
        "rollback": "Use each unit's admitted_reference_images; rejected A2 candidates remain audit-only and never enter video input.",
        "failures": [],
    }
    QA.parent.mkdir(parents=True, exist_ok=True)
    QA.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "video_units": 20, "anchors": plan["planned_reference_image_count"], "single": 18, "double": 2}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
