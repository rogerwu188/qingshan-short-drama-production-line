#!/usr/bin/env python3
"""Pre-generation structure gate for CL2X-605 action-visualization reasoning."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "intent",
    "invisible_element",
    "externalized_visible_phenomenon",
    "ability_logic",
    "force_feedback",
    "expression",
    "viewer_read",
)


def evaluate(plan: dict[str, Any]) -> dict[str, Any]:
    failures = []
    rows = []
    for unit in plan.get("units") or []:
        unit_id = str(unit.get("unit_id") or "UNKNOWN")
        beats = ((unit.get("performance_spec") or {}).get("motion_beats") or [])
        if not beats:
            failures.append({"unit_id": unit_id, "error": "motion_beats_missing"})
            continue
        for index, beat in enumerate(beats, 1):
            missing = [field for field in REQUIRED if not str(beat.get(field) or "").strip()]
            if missing:
                failures.append({"unit_id": unit_id, "beat": index, "error": "action_visualization_fields_missing", "fields": missing})
                continue
            if str(beat["externalized_visible_phenomenon"]).strip() == str(beat["intent"]).strip():
                failures.append({"unit_id": unit_id, "beat": index, "error": "intent_repeated_without_visible_externalization"})
                continue
            rows.append({
                "unit_id": unit_id,
                "beat": index,
                "status": "PASS",
                "blind_viewer_question": "Can a first-time viewer infer what happened and why from the generated image sequence alone?",
                "expected_viewer_read": beat["viewer_read"],
            })
    return {
        "schema": "qingshan.action_visualization_readability_gate.v1",
        "episode": plan.get("episode"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if rows and not failures else "FAIL",
        "gate_id": "30_BLIND_VIEWER_ACTION_PURPOSE_AND_CAUSALITY",
        "policy": "This is a pre-generation reasoning gate. The generated video must repeat the blind-viewer readability test during visual QA; no specific effect is required.",
        "checked_beats": len(rows),
        "rows": rows,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    report = evaluate(json.loads(plan_path.read_text(encoding="utf-8")))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "checked_beats": report["checked_beats"], "failures": len(report["failures"])}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
