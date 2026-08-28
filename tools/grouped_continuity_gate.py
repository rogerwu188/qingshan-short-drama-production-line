#!/usr/bin/env python3
"""Registered preflight gate for cross-unit transitions and start-frame semantics."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.compile_grouped_seedance_manifest import compile_manifest
except ModuleNotFoundError:
    from compile_grouped_seedance_manifest import compile_manifest


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load(value: str | Path) -> dict[str, Any]:
    return json.loads(resolve(value).read_text(encoding="utf-8"))


def evaluate(grouping: dict[str, Any], anchors: dict[str, Any], editorial: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    compiled: dict[str, Any] | None = None
    try:
        compiled = compile_manifest(grouping, anchors, editorial)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        failures.append(str(exc))
    units = (compiled or {}).get("units") or []
    return {
        "schema": "qingshan.grouped_continuity_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "video_unit_count": len(units),
        "boundary_count": max(0, len(units) - 1),
        "transition_contract_count": sum(bool(row.get("incoming_transition_contract")) for row in units),
        "start_frame_semantic_contract_count": sum(
            (row.get("start_frame_semantic_contract") or {}).get("status") == "PASS" for row in units
        ),
        "policy": (
            "EVERY_ADJACENT_VIDEO_UNIT_BOUNDARY_REQUIRES_DIRECTOR_OR_EDITOR_AUTHORED_VISUAL_ACTION_SOUND_AND_AXIS_CONTINUITY;"
            "EVERY_START_ANCHOR_REQUIRES_EXACT_SHA_SEMANTIC_EVIDENCE_MATCHING_FIRST_BEAT_CAST_SPACE_AND_CAMERA_FRAMING"
        ),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grouping-plan", required=True)
    parser.add_argument("--anchor-plan", required=True)
    parser.add_argument("--editorial-seedance-manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = evaluate(load(args.grouping_plan), load(args.anchor_plan), load(args.editorial_seedance_manifest))
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(out), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
