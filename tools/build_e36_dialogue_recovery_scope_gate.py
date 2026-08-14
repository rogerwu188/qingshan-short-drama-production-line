#!/usr/bin/env python3
"""Reconcile E36 canonical dialogue gaps with motion coverage and credit floor."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_DIALOGUE_NATIVE_VIDEO_CONTRACT_V1.json"
PLAN = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_NATURAL_VIDEO_UNITS_AND_ANCHOR_PLAN_V2.json"
SOURCE_MAP = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V1.json"
TRANSCRIPT_AUDIT = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V2.json"
CREDIT_AUDIT = ROOT / "qa/e36_v2_stills_repair_20260729/E36_ACTUAL_CREDIT_SPEND_AUDIT_5863_V9.json"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_CANONICAL_DIALOGUE_RECOVERY_SCOPE_AND_CREDIT_GATE_V1.json"


# Canonical script order reconciled against the authored natural-unit plan and
# later production splits (U18A-D, U19A-C, U20A/B). Inclusive line ranges.
UNIT_LINE_RANGES = {
    "U02": (1, 3),
    "U08": (4, 5),
    "U09": (6, 10),
    "U10": (11, 15),
    "U11": (16, 17),
    "U12": (18, 19),
    "U13": (20, 21),
    "U14": (22, 28),
    "U15": (29, 31),
    "U16": (32, 33),
    "U18": (34, 37),
    "U19": (38, 39),
    "U20A": (40, 42),
    "U20B": (43, 45),
    "U21": (46, 47),
}

# Exact production split durations required for a native-video dialogue retry.
DIALOGUE_REPAIR_SECONDS = {"U02": 7, "U11": 10, "U13": 8, "U18": 5, "U21": 8}
MISSING_MOTION_UNITS = {"U04", "U08", "U09", "U10", "U14", "U20A"}
LOWEST_OBSERVED_FAST_RATE_CREDITS_PER_SECOND = 16


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    contract = load(CONTRACT)
    plan = load(PLAN)
    source_map = load(SOURCE_MAP)
    transcript_audit = load(TRANSCRIPT_AUDIT)
    credit_audit = load(CREDIT_AUDIT)

    line_to_unit = {}
    for unit, (start, end) in UNIT_LINE_RANGES.items():
        for line_number in range(start, end + 1):
            if line_number in line_to_unit:
                raise ValueError(f"duplicate canonical line mapping: {line_number}")
            line_to_unit[line_number] = unit
    expected_lines = set(range(1, len(contract["lines"]) + 1))
    if set(line_to_unit) != expected_lines:
        raise ValueError("unit-to-dialogue mapping does not cover the canonical contract exactly")

    planned_seconds = {row["unit_id"]: row["duration_seconds"] for row in plan["units"]}
    planned_seconds["U20A"] = 12
    missing_motion_seconds = sum(planned_seconds[unit] for unit in MISSING_MOTION_UNITS)

    unproven = {row["contract_line_number"]: row for row in transcript_audit["unproven_lines"]}
    rows = []
    for line_number in sorted(unproven):
        unit = line_to_unit[line_number]
        recovery_class = "MISSING_MOTION_AND_NATIVE_DIALOGUE" if unit in MISSING_MOTION_UNITS else "ACCEPTED_MOTION_BUT_CANONICAL_NATIVE_DIALOGUE_UNPROVEN"
        rows.append({**unproven[line_number], "canonical_unit": unit, "recovery_class": recovery_class})

    dialogue_repair_units = sorted({row["canonical_unit"] for row in rows if row["canonical_unit"] not in MISSING_MOTION_UNITS})
    unexpected = set(dialogue_repair_units) - set(DIALOGUE_REPAIR_SECONDS)
    if unexpected:
        raise ValueError(f"missing retry-duration authority for: {sorted(unexpected)}")
    dialogue_repair_seconds = sum(DIALOGUE_REPAIR_SECONDS[unit] for unit in dialogue_repair_units)
    total_recovery_seconds = missing_motion_seconds + dialogue_repair_seconds
    floor_credits = total_recovery_seconds * LOWEST_OBSERVED_FAST_RATE_CREDITS_PER_SECOND
    current_credits = credit_audit["net_actual_credits"]
    cap = credit_audit["episode_limit"]
    projected = current_credits + floor_credits

    unit_summary = []
    for unit in sorted({row["canonical_unit"] for row in rows} | MISSING_MOTION_UNITS):
        line_numbers = [row["contract_line_number"] for row in rows if row["canonical_unit"] == unit]
        if unit in MISSING_MOTION_UNITS:
            recovery_class = "MISSING_MOTION_SOURCE"
            seconds = planned_seconds[unit]
        else:
            recovery_class = "ACCEPTED_MOTION_DIALOGUE_REPAIR_REQUIRED"
            seconds = DIALOGUE_REPAIR_SECONDS[unit]
        unit_summary.append(
            {
                "canonical_unit": unit,
                "recovery_class": recovery_class,
                "unproven_canonical_lines": line_numbers,
                "unproven_line_count": len(line_numbers),
                "minimum_video_seconds": seconds,
                "minimum_fast_credits_at_observed_floor": seconds * LOWEST_OBSERVED_FAST_RATE_CREDITS_PER_SECOND,
            }
        )

    payload = {
        "schema": "qingshan.e36_canonical_dialogue_recovery_scope_and_credit_gate.v1",
        "episode": "E36",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": "CL2X-787",
        "source_mailbox_sha256": "f45fbf158922ab8eebc3651fb0fcae8f4b5cc5d3d9f237e564a1366aacc44387",
        "inputs": {
            "canonical_dialogue_contract": {"path": str(CONTRACT.relative_to(ROOT)), "sha256": sha256(CONTRACT)},
            "natural_unit_plan": {"path": str(PLAN.relative_to(ROOT)), "sha256": sha256(PLAN)},
            "accepted_source_map": {"path": str(SOURCE_MAP.relative_to(ROOT)), "sha256": sha256(SOURCE_MAP)},
            "accepted_transcript_audit": {"path": str(TRANSCRIPT_AUDIT.relative_to(ROOT)), "sha256": sha256(TRANSCRIPT_AUDIT)},
            "exact_credit_audit": {"path": str(CREDIT_AUDIT.relative_to(ROOT)), "sha256": sha256(CREDIT_AUDIT)},
        },
        "coverage_reconciliation": {
            "canonical_lines": len(contract["lines"]),
            "proven_lines": len(contract["lines"]) - len(rows),
            "unproven_lines": len(rows),
            "unproven_lines_on_missing_motion_units": sum(row["canonical_unit"] in MISSING_MOTION_UNITS for row in rows),
            "unproven_lines_on_accepted_motion_units": sum(row["canonical_unit"] not in MISSING_MOTION_UNITS for row in rows),
            "missing_motion_units": sorted(MISSING_MOTION_UNITS),
            "accepted_motion_units_requiring_native_dialogue_repair": dialogue_repair_units,
        },
        "unit_summary": unit_summary,
        "unproven_line_assignments": rows,
        "credit_floor": {
            "current_episode_credits": current_credits,
            "episode_cap": cap,
            "headroom": cap - current_credits,
            "lowest_observed_fast_rate_credits_per_second": LOWEST_OBSERVED_FAST_RATE_CREDITS_PER_SECOND,
            "missing_motion_video_seconds": missing_motion_seconds,
            "accepted_motion_dialogue_repair_video_seconds": dialogue_repair_seconds,
            "total_minimum_video_seconds": total_recovery_seconds,
            "minimum_additional_video_credits": floor_credits,
            "projected_episode_credits": projected,
            "minimum_cap_shortfall": max(0, projected - cap),
            "image_repair_credits_included": False,
            "status": "FAIL_EXCEEDS_CAP" if projected > cap else "PASS_WITHIN_CAP",
        },
        "gate_results": {
            "canonical_line_to_unit_mapping": "PASS_47_OF_47_EXACTLY_ONCE",
            "accepted_transcript_coverage": f"FAIL_{len(contract['lines']) - len(rows)}_OF_{len(contract['lines'])}",
            "recovery_scope": f"FAIL_{len(MISSING_MOTION_UNITS)}_MISSING_MOTION_PLUS_{len(dialogue_repair_units)}_DIALOGUE_REPAIR_UNITS",
            "credit_cap": f"FAIL_PROJECTED_{projected}_GT_{cap}_SHORTFALL_{max(0, projected - cap)}",
            "agentcut_render": "BLOCKED",
        },
        "blocked_by": f"CREDIT_CAP_SHORTFALL_{max(0, projected - cap)}_FOR_COMPLETE_MOTION_AND_CANONICAL_NATIVE_DIALOGUE_RECOVERY",
        "next_action": "Obtain a revised E36 cap or explicit above-cap ceiling before any remote recovery. Then regenerate six missing-motion units and five accepted-motion dialogue-defective units, rerun exact transcript coverage to47/47 and motion coverage to30/30, and only then render AgentCut.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "sha256": sha256(OUT), "coverage": payload["coverage_reconciliation"], "credit_floor": payload["credit_floor"]}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
