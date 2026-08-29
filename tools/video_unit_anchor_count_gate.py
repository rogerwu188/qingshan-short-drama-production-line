#!/usr/bin/env python3
"""Block fixed anchor-count defaults and require a justified per-unit decision."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


FIXED_DEFAULT_MARKERS = (
    "always one",
    "one image per unit",
    "one anchor per unit",
    "always multiple",
    "fixed minimum",
    "minimum state",
    "固定1张",
    "固定一张",
    "每单元一张",
    "每个单元一张",
    "固定多张",
    "至少两张",
    "至少2张",
    "至少三张",
    "至少3张",
)


def evaluate(plan: dict) -> dict:
    failures: list[dict] = []
    decisions: list[dict] = []
    units = plan.get("units")
    if not isinstance(units, list) or not units:
        failures.append({"code": "UNITS_MISSING", "detail": "Plan must contain a non-empty units list."})
        units = []

    for unit in units:
        unit_id = str(unit.get("unit_id") or "UNKNOWN")
        count = unit.get("planned_reference_image_count")
        decision = unit.get("anchor_count_decision")
        reasons: list[str] = []

        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            reasons.append("planned_reference_image_count must be an integer >= 1")
        if not isinstance(decision, dict):
            reasons.append("anchor_count_decision is required")
            decision = {}

        decision_count = decision.get("planned_reference_image_count")
        reason = str(decision.get("reason") or "").strip()
        criteria = decision.get("criteria")
        anchor_roles = decision.get("anchor_roles")
        action_design_class = str(decision.get("action_design_class") or "").strip()
        if decision_count != count:
            reasons.append("decision count does not match planned_reference_image_count")
        if len(reason) < 24:
            reasons.append("unit-level action/model capability reason is missing or too vague")
        reason_lower = reason.lower()
        if any(marker in reason_lower for marker in FIXED_DEFAULT_MARKERS):
            reasons.append("reason uses a forbidden fixed anchor-count default")

        task_keys = unit.get("reference_image_task_keys")
        if not isinstance(task_keys, list) or len(task_keys) != count:
            reasons.append("reference_image_task_keys count does not match the planned count")

        required_criteria = {
            "continuous_motion_from_single_start",
            "identity_or_space_reanchor",
            "prop_ownership_transition",
            "non_interpolable_terminal_state",
        }
        if not isinstance(criteria, dict) or set(criteria) != required_criteria:
            reasons.append("anchor_count_decision.criteria must explicitly assess all four action-design signals")
        elif any(not isinstance(criteria[key], bool) for key in required_criteria):
            reasons.append("every anchor-count criterion must be boolean")
        else:
            needs_extra_anchor = any(
                criteria[key]
                for key in (
                    "identity_or_space_reanchor",
                    "prop_ownership_transition",
                    "non_interpolable_terminal_state",
                )
            )
            if count == 1 and not criteria["continuous_motion_from_single_start"]:
                reasons.append("single-anchor decision does not establish that one start frame can drive the motion")
            if count == 1 and needs_extra_anchor:
                reasons.append("single-anchor decision conflicts with a declared re-anchor or terminal-state need")
            if count > 1 and not needs_extra_anchor:
                reasons.append("multi-anchor decision declares no action-design condition requiring extra anchors")

        if not isinstance(anchor_roles, list) or len(anchor_roles) != count:
            reasons.append("anchor_count_decision.anchor_roles must name the role of every planned anchor")
        elif any(not str(role).strip() for role in anchor_roles):
            reasons.append("anchor roles cannot be blank")
        if len(action_design_class) < 4:
            reasons.append("anchor_count_decision.action_design_class is required")

        if isinstance(count, int) and count > 1:
            strategy = unit.get("reference_transport_strategy")
            if strategy in {"OMNI_MULTI_REFERENCE", "STANDARD_MULTI_REFERENCE"}:
                coverage = unit.get("semantic_reference_coverage_gate")
                if not isinstance(coverage, dict) or coverage.get("status") != "PASS":
                    reasons.append("multi-reference unit lacks a passing semantic reference coverage gate")
                elif coverage.get("references_checked") != count:
                    reasons.append("semantic reference coverage gate did not check every reference")
            else:
                continuity = unit.get("keyframe_interpolation_gate")
                if not isinstance(continuity, dict) or continuity.get("status") != "PASS":
                    reasons.append("multi-anchor unit lacks a passing physical interpolation gate")
                elif continuity.get("adjacent_pairs_checked") != count - 1:
                    reasons.append("physical interpolation gate did not check every adjacent anchor pair")

        decisions.append({
            "unit_id": unit_id,
            "planned_reference_image_count": count,
            "reason": reason,
            "criteria": criteria,
            "anchor_roles": anchor_roles,
            "action_design_class": action_design_class,
            "status": "FAIL" if reasons else "PASS",
            "failures": reasons,
        })
        if reasons:
            failures.append({"code": "UNIT_ANCHOR_DECISION_INVALID", "unit_id": unit_id, "detail": reasons})

    total = sum(
        row.get("planned_reference_image_count", 0)
        for row in decisions
        if isinstance(row.get("planned_reference_image_count"), int)
    )
    declared_total = plan.get("planned_reference_image_count")
    if declared_total is not None and declared_total != total:
        failures.append({
            "code": "ANCHOR_TOTAL_MISMATCH",
            "detail": f"Plan declares {declared_total}, but unit decisions total {total}.",
        })

    valid_counts = [
        row["planned_reference_image_count"]
        for row in decisions
        if isinstance(row.get("planned_reference_image_count"), int)
    ]
    if len(valid_counts) >= 4 and len(set(valid_counts)) == 1:
        audit = plan.get("uniform_count_independence_audit")
        signatures = {
            json.dumps(
                {
                    "criteria": row.get("criteria"),
                    "action_design_class": row.get("action_design_class"),
                },
                sort_keys=True,
            )
            for row in decisions
            if isinstance(row.get("criteria"), dict)
        }
        if not isinstance(audit, dict) or audit.get("status") != "PASS":
            failures.append({
                "code": "UNIFORM_COUNT_INDEPENDENCE_AUDIT_MISSING",
                "detail": "A batch with one anchor count across every unit needs an explicit independent-assessment audit.",
            })
        elif audit.get("evaluated_individually") is not True:
            failures.append({
                "code": "UNIFORM_COUNT_NOT_INDEPENDENTLY_EVALUATED",
                "detail": "Uniform count audit must confirm that every unit was evaluated independently.",
            })
        elif len(signatures) < 2 or int(audit.get("distinct_action_design_classes") or 0) < 2:
            failures.append({
                "code": "UNIFORM_COUNT_MECHANICAL_RESULT",
                "detail": "Uniform count is unsupported because the batch shows fewer than two distinct action-design classes.",
            })

    return {
        "schema": "qingshan.video_unit_anchor_count_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL" if failures else "PASS",
        "policy": "DECIDE_PER_UNIT_FROM_MODEL_CAPABILITY_AND_ACTION_DESIGN; NEVER FIX_ONE_OR_FIXED_MULTI",
        "video_unit_count": len(units),
        "planned_reference_image_count": total,
        "decisions": decisions,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = evaluate(json.loads(args.plan.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "video_units": report["video_unit_count"],
        "anchors": report["planned_reference_image_count"],
        "failures": len(report["failures"]),
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
