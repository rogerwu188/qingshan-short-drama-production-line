#!/usr/bin/env python3
"""Enforce blocker, minor-budget, and opening/tail zero-tolerance rules."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROTECTED_GATES = {"AUDIENCE_SCORE_PRE_RELEASE", "WATCH_LISTEN", "ROGER_VETO"}


def evaluate(report: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    shot_count = int(report.get("shot_count") or 0)
    duration = float(report.get("duration_seconds") or 0)
    defects = [row for row in report.get("defects") or [] if isinstance(row, dict)]
    if shot_count <= 0 or duration <= 0:
        failures.append("shot_count_and_duration_must_be_positive")

    minor_shots: set[int] = set()
    minor_categories: list[tuple[int, str]] = []
    for row in defects:
        severity = str(row.get("severity") or "").upper()
        scope = str(row.get("scope") or "SHOT").upper()
        category = str(row.get("category") or "UNCLASSIFIED")
        if severity == "BLOCKER":
            failures.append(f"blocker_defect:{category}")
        elif severity != "MINOR":
            failures.append(f"invalid_defect_severity:{category}:{severity or 'MISSING'}")
            continue
        if scope == "SHOT":
            shot_index = int(row.get("shot_index") or 0)
            if shot_index <= 0:
                failures.append(f"minor_shot_index_missing:{category}")
                continue
            minor_shots.add(shot_index)
            minor_categories.append((shot_index, category))
            start = float(row.get("start_seconds") or 0)
            end = float(row.get("end_seconds") or start)
            if start < 10.0 or end > duration - 5.0:
                failures.append(f"minor_in_zero_tolerance_zone:{shot_index}:{category}")

    minor_pct = (len(minor_shots) * 100.0 / shot_count) if shot_count else 100.0
    if minor_pct > 10.0:
        failures.append("minor_shot_budget_exceeds_10_percent")
    by_category: dict[str, list[int]] = {}
    for shot_index, category in minor_categories:
        by_category.setdefault(category, []).append(shot_index)
    for category, indices in by_category.items():
        ordered = sorted(set(indices))
        for left, middle, right in zip(ordered, ordered[1:], ordered[2:]):
            if middle == left + 1 and right == middle + 1:
                failures.append(f"three_consecutive_same_minor_escalates:{category}:{left}-{right}")
                break

    overridden = {str(value).upper() for value in report.get("conditional_admission_overrides") or []}
    for gate in sorted(overridden & PROTECTED_GATES):
        failures.append(f"conditional_admission_cannot_override:{gate}")
    return {
        "schema": "qingshan.defect_tolerance_gate.v1",
        "episode": report.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "minor_unique_shot_count": len(minor_shots),
        "minor_shot_pct": round(minor_pct, 4),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.report.read_text(encoding="utf-8")))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
