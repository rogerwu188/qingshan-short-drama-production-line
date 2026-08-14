#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from frame_cadence_audit import media_fps
    from run_regression_ci import default_ffmpeg, duration_seconds
except ModuleNotFoundError:
    from tools.frame_cadence_audit import media_fps
    from tools.run_regression_ci import default_ffmpeg, duration_seconds


FORBIDDEN_RENDER_PATTERNS = {
    "setpts_speed_change": re.compile(r"setpts\s*=\s*(?!PTS-STARTPTS)", re.IGNORECASE),
    "frame_interpolation": re.compile(r"\bminterpolate\b", re.IGNORECASE),
    "video_loop": re.compile(r"(?:-stream_loop|\bloop\s*=)", re.IGNORECASE),
    "still_frame_extension": re.compile(r"\btpad\b[^,\n]*(?:clone|stop_duration)", re.IGNORECASE),
}


def renderer_source_failures(text: str) -> list[str]:
    return [
        f"forbidden_renderer_operation:{name}"
        for name, pattern in FORBIDDEN_RENDER_PATTERNS.items()
        if pattern.search(text)
    ]


def evaluate_plan_rows(rows: list[dict[str, Any]], target_fps: float, tolerance: float = 0.05) -> list[str]:
    failures: list[str] = []
    for row in rows:
        source_id = row["source_id"]
        if float(row["in_sec"]) < 0 or float(row["duration_sec"]) <= 0:
            failures.append(f"invalid_source_window:{source_id}")
        if float(row["in_sec"]) + float(row["duration_sec"]) > float(row["source_duration_sec"]) + 0.05:
            failures.append(f"source_window_exceeds_media:{source_id}")
        if abs(float(row["source_fps"]) - target_fps) > tolerance:
            failures.append(
                f"target_source_fps_mismatch:{source_id}:target={target_fps:.3f}:source={float(row['source_fps']):.3f}"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject retime/freeze cheats before episode assembly.")
    parser.add_argument("--render-plan", required=True)
    parser.add_argument("--renderer", required=True)
    parser.add_argument("--target-fps", type=float, required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ffmpeg", default=default_ffmpeg())
    args = parser.parse_args()

    plan_path = Path(args.render_plan).expanduser().resolve()
    renderer_path = Path(args.renderer).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    if not plan_path.is_file() or not renderer_path.is_file():
        raise SystemExit("Missing render plan or renderer.")
    if not args.ffmpeg or not Path(args.ffmpeg).is_file():
        raise SystemExit("Missing ffmpeg.")
    ffmpeg = str(Path(args.ffmpeg).resolve())

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    plan_rows = plan.get("segments") or plan.get("video_segments") or []
    for index, item in enumerate(plan_rows, start=1):
        raw_path = item.get("path")
        if not raw_path:
            continue
        source = Path(raw_path).expanduser().resolve()
        if not source.is_file():
            continue
        rows.append(
            {
                "source_id": item.get("source_id") or item.get("role") or f"segment-{index}",
                "path": str(source),
                "in_sec": float(item.get("in_sec", item.get("source_in_sec", 0)) or 0),
                "duration_sec": float(item.get("duration_sec", 0) or 0),
                "source_duration_sec": duration_seconds(source, ffmpeg),
                "source_fps": media_fps(ffmpeg, source),
            }
        )
    failures = renderer_source_failures(renderer_path.read_text(encoding="utf-8"))
    failures.extend(evaluate_plan_rows(rows, args.target_fps))
    report = {
        "schema": "qingshan.edit_plan_integrity_gate.v1",
        "render_plan": str(plan_path),
        "renderer": str(renderer_path),
        "target_fps": args.target_fps,
        "rows": rows,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "rule": "Coverage gaps must be solved by new source coverage or a real edit. Retime, interpolation, looping and still-frame extension are C7 process cheating.",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(out), "failures": failures}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
