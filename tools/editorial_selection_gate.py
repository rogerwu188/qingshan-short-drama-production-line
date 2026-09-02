#!/usr/bin/env python3
"""Validate a real edit desk: explicit source windows, rhythm, and clean final frames."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

try:
    from tools.media_frame_integrity import analyze, recommend_window
except ModuleNotFoundError:
    from media_frame_integrity import analyze, recommend_window


def evaluate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    durations: list[float] = []
    tail_trims: list[float] = []
    for index, row in enumerate(rows, 1):
        source_id = str(row.get("source_id") or row.get("unit_id") or f"ROW_{index}")
        if row.get("selection_policy") == "USE_FULL_PROVIDER_MEDIA":
            failures.append(f"USE_FULL_PROVIDER_MEDIA_FORBIDDEN:{source_id}")
        if row.get("selected_in_seconds") is None or row.get("selected_out_seconds") is None:
            failures.append(f"SELECTED_WINDOW_MISSING:{source_id}")
            continue
        start = float(row["selected_in_seconds"])
        end = float(row["selected_out_seconds"])
        source_duration = float(row.get("source_duration_seconds") or end)
        if start < 0 or end <= start or end > source_duration + 0.05:
            failures.append(f"SELECTED_WINDOW_INVALID:{source_id}:{start}->{end}/{source_duration}")
            continue
        durations.append(end - start)
        tail_trims.append(max(0.0, source_duration - end))
    if rows and not any(value > 0.01 for value in tail_trims):
        failures.append("ALL_TAIL_TRIMS_ZERO")
    median_duration = statistics.median(durations) if durations else 0.0
    short_ratio = sum(value < 3.0 for value in durations) / len(durations) if durations else 0.0
    if durations and median_duration > 4.5:
        failures.append(f"MEDIAN_SHOT_DURATION_TOO_LONG:{median_duration:.3f}>4.5")
    if durations and short_ratio < 0.20:
        failures.append(f"SHORT_SHOT_RATIO_TOO_LOW:{short_ratio:.3f}<0.20")
    return {
        "schema": "qingshan.editorial_selection_gate.v1",
        "status": "PASS" if rows and not failures else "FAIL",
        "shot_count": len(rows),
        "median_selected_duration_seconds": median_duration,
        "under_3_seconds_ratio": short_ratio,
        "tail_trimmed_unit_count": sum(value > 0.01 for value in tail_trims),
        "failures": failures or ([] if rows else ["EDIT_PLAN_EMPTY"]),
    }


def build_rows(media_rows: list[dict[str, Any]], *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> list[dict[str, Any]]:
    results = []
    for index, row in enumerate(media_rows, 1):
        path = Path(str(row.get("path") or row.get("media_path") or ""))
        scan = analyze(path, ffmpeg=ffmpeg, ffprobe=ffprobe)
        window = recommend_window(scan, safety_handle_seconds=0.25)
        results.append({
            "source_id": row.get("source_id") or row.get("unit_id") or f"ROW_{index}",
            "path": str(path.expanduser().resolve()),
            "source_duration_seconds": scan["duration_seconds"],
            "selection_policy": "OBJECTIVE_EFFECTIVE_ACTION_WINDOW",
            **window,
            "frame_integrity": {key: scan[key] for key in ("frames_scanned", "median_luma", "median_frame_difference", "black_ranges", "solid_color_ranges", "freeze_ranges")},
        })
    return results


def validate_final(path: Path, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> dict[str, Any]:
    scan = analyze(path, ffmpeg=ffmpeg, ffprobe=ffprobe)
    failures: list[str] = []
    if scan["black_ranges"]:
        failures.append("FINAL_CONTAINS_YAVG_BELOW_8")
    if scan["solid_color_ranges"]:
        failures.append("FINAL_CONTAINS_SOLID_COLOR_FRAME")
    if scan["freeze_ranges"]:
        failures.append("FINAL_CONTAINS_FREEZE_RANGE")
    return {"status": "PASS" if not failures else "FAIL", "scan": scan, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("media_map", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    payload = json.loads(args.media_map.read_text(encoding="utf-8"))
    media_rows = payload.get("rows") or payload.get("units") or payload.get("media") or payload.get("segments") or []
    rows = build_rows(media_rows, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    report = {"rows": rows, "gate": evaluate_rows(rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["gate"]["status"], "rows": len(rows), "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["gate"]["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
