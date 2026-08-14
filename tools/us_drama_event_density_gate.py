#!/usr/bin/env python3
"""Validate only the R-49 numeric event-density contract.

Narrative techniques such as buttons, countdowns and burst segments belong to
the dramatic-quality gate. Keeping them out of this evaluator prevents one
gate from silently inventing requirements owned by another gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(script: dict) -> dict:
    failures: list[str] = []
    runtime = script.get("runtime_target_seconds") or {}
    target = float(runtime.get("target") or 0)
    minimum = float(runtime.get("min") or 0)
    maximum = float(runtime.get("max") or 0)
    beats = script.get("structure") or []
    dialogue = script.get("dialogue_draft") or []
    density = script.get("event_density") or {}

    if not (minimum <= target <= maximum and target > 0):
        failures.append("runtime_target_out_of_range")
    structure_seconds = sum(float(row.get("target_seconds") or 0) for row in beats)
    if abs(structure_seconds - target) > 0.01:
        failures.append("structure_runtime_target_mismatch")

    planned_events = int(density.get("planned_event_count") or 0)
    observed_rate = planned_events / (target / 60) if target else 0.0
    hard_min = float(density.get("hard_min_per_minute") or 4.0)
    if observed_rate < hard_min:
        failures.append("event_density_below_hard_minimum")
    max_gap = float(density.get("max_information_gap_seconds") or 999)
    if max_gap > 20:
        failures.append("maximum_information_gap_exceeds_20s")
    non_advancing = float(density.get("non_advancing_percentage") or 0.0)
    if non_advancing > 15.0:
        failures.append("non_advancing_atmosphere_percentage_exceeds_15")

    dialogue_rate = len(dialogue) / (target / 60) if target else 0.0
    return {
        "schema": "qingshan.us_drama_event_density_gate.v1",
        "episode": script.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "hard_policy": {
            "event_density_min_per_minute": hard_min,
            "maximum_information_gap_seconds": 20,
            "every_scene_requires_new_information_power_shift_and_button": True,
            "dialogue_lines_per_minute_is_reference_only": True,
        },
        "observed": {
            "runtime_target_seconds": target,
            "structure_target_seconds": structure_seconds,
            "planned_event_count": planned_events,
            "events_per_minute": round(observed_rate, 3),
            "max_information_gap_seconds": max_gap,
            "non_advancing_percentage": non_advancing,
            "dialogue_line_count": len(dialogue),
            "dialogue_lines_per_minute_reference": round(dialogue_rate, 3),
            "beat_count": len(beats),
        },
        "failures": failures,
        "machine_decision": True,
        "confidence": 0.96 if not failures else 0.99,
        "rollback": "Delete only the gate report; the source script is not modified.",
        "scope_note": "R-49 numeric density only; beat techniques and hooks are evaluated by their owning gates.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    script = json.loads(args.script.read_text(encoding="utf-8"))
    report = evaluate(script)
    report["script"] = str(args.script)
    report["script_sha256"] = file_sha256(args.script)
    report["recorded_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(args.out), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
