#!/usr/bin/env python3
"""Verify that a frame-exact render report materializes the declared edit plan."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(plan_path: Path, render_report_path: Path, video_path: Path) -> dict:
    failures: list[str] = []
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    report = json.loads(render_report_path.read_text(encoding="utf-8"))
    if not video_path.is_file() or video_path.stat().st_size == 0:
        failures.append("materialized_video_missing")
    expected_plan_sha = sha256(plan_path)
    reported_plan_sha = str(report.get("plan_sha256") or report.get("render_plan_sha256") or "")
    if reported_plan_sha != expected_plan_sha:
        failures.append("render_report_plan_sha_mismatch")
    reported_video_sha = str(report.get("output_sha256") or report.get("video_sha256") or "")
    actual_video_sha = sha256(video_path) if video_path.is_file() else ""
    if reported_video_sha != actual_video_sha:
        failures.append("render_report_video_sha_mismatch")
    segment_count = len(plan.get("segments") or plan.get("video_segments") or [])
    rendered_count = int(report.get("segment_count", -1))
    if rendered_count != segment_count:
        failures.append(f"rendered_segment_count_mismatch:{rendered_count}:{segment_count}")
    if str(report.get("status") or "").upper() != "PASS":
        failures.append("frame_exact_render_report_not_pass")
    return {
        "schema": "qingshan.frame_exact_materialization_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "plan": str(plan_path),
        "render_report": str(render_report_path),
        "video": str(video_path),
        "video_sha256": actual_video_sha or None,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--render-report", required=True, type=Path)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(args.plan.resolve(), args.render_report.resolve(), args.video.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
