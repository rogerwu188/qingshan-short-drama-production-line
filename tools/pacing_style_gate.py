#!/usr/bin/env python3
"""Automate the pacing-style ban from final CI and the exact edit plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _duration(row: dict[str, Any]) -> float:
    return float(row.get("duration_sec", row.get("duration_seconds", 0)) or 0)


def evaluate(ci_report: dict[str, Any], edit_plan: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    static_hold = ci_report.get("static_hold_gate") or {}
    freeze = ci_report.get("freeze") or {}
    repeats = ci_report.get("frame_repeat") or {}
    thresholds = ci_report.get("thresholds") or {}

    if str(static_hold.get("status") or "").upper() != "PASS":
        failures.append("static_hold_gate_not_pass")
    freeze_ratio = freeze.get("freeze_ratio")
    freeze_max = thresholds.get("freeze_ratio_max")
    if freeze_ratio is None or freeze_max is None:
        failures.append("freeze_ratio_evidence_missing")
    elif float(freeze_ratio) > float(freeze_max):
        failures.append(f"freeze_ratio_exceeded:{float(freeze_ratio):.4f}")
    repeat_ratio = repeats.get("near_duplicate_ratio")
    repeat_max = thresholds.get("near_duplicate_ratio_max")
    if repeat_ratio is None or repeat_max is None:
        failures.append("frame_repeat_evidence_missing")
    elif float(repeat_ratio) > float(repeat_max):
        failures.append(f"near_duplicate_ratio_exceeded:{float(repeat_ratio):.4f}")

    rows = edit_plan.get("segments") or edit_plan.get("video_segments") or []
    if not isinstance(rows, list) or not rows:
        failures.append("edit_plan_segments_missing")
        rows = []
    decisions = []
    for index, row in enumerate(rows, start=1):
        shot_id = str(row.get("source_id") or row.get("shot_id") or f"SHOT_{index}")
        duration = _duration(row)
        row_failures: list[str] = []
        is_insert = bool(row.get("is_insert")) or str(row.get("shot_type") or "").lower() == "insert"
        if is_insert and duration > 2.0:
            row_failures.append(f"insert_duration_exceeds_2s:{duration:.3f}")
        speed_factor = float(row.get("speed_factor", 1.0) or 1.0)
        if abs(speed_factor - 1.0) > 0.001 or row.get("slow_motion") is True:
            row_failures.append(f"retime_or_slow_motion_forbidden:{speed_factor:.3f}")
        if duration > 6.0 and not str(row.get("long_take_motivation") or "").strip():
            row_failures.append(f"unmotivated_long_take:{duration:.3f}")
        failures.extend(f"{shot_id}:{item}" for item in row_failures)
        decisions.append({"shot_id": shot_id, "status": "PASS" if not row_failures else "FAIL", "failures": row_failures})

    return {
        "schema": "qingshan.pacing_style_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "fail_closed": True,
        "decisions": decisions,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ci-report", required=True, type=Path)
    parser.add_argument("--edit-plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(
        json.loads(args.ci_report.read_text(encoding="utf-8")),
        json.loads(args.edit_plan.read_text(encoding="utf-8")),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
