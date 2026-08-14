#!/usr/bin/env python3
"""Validate integer-frame replacement bindings before an episode render."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _span(value: Any, label: str, errors: list[str]) -> tuple[int, int] | None:
    if not isinstance(value, list) or len(value) != 2:
        errors.append(f"{label}: expected [start, end]")
        return None
    start, end = value
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
        errors.append(f"{label}: invalid half-open frame range {value!r}")
        return None
    return start, end


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return max(left[0], right[0]) < min(left[1], right[1])


def evaluate(plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    check_names = [
        "AUDIO_CUT_RANGE_MATCHES_REMOVED_FRAMES",
        "SOURCE_EXCLUSION_RANGES_VALID",
        "SEGMENT_SOURCE_FRAME_COUNTS_MATCH",
        "SEGMENT_OUTPUT_FRAME_COUNTS_MATCH",
        "OUTPUT_SEGMENTS_CONTIGUOUS_PER_WINDOW",
        "REPLACEMENT_WINDOW_FRAME_COUNTS_MATCH",
        "POST_CUT_OUTPUT_SHIFT_MATCHES",
        "SOURCE_RANGES_NON_OVERLAPPING",
        "EXCLUDED_SOURCE_RANGES_NOT_USED",
        "OUTPUT_WINDOWS_NON_OVERLAPPING",
        "FRAME_ACCOUNTING_TOTAL_MATCHES",
        "RETIME_FREEZE_LOOP_COUNTS_ZERO",
        "TARGET_FRAMES_FPS_SECONDS_CONSISTENT",
    ]
    windows = plan.get("replacement_windows") or []
    cut = plan.get("audio_cut") or {}
    cut_frames = cut.get("video_frames_removed")
    cut_source = _span(cut.get("video_source_frames"), "audio_cut.video_source_frames", errors)
    if cut_source and cut_frames != cut_source[1] - cut_source[0]:
        errors.append("audio_cut.video_frames_removed does not match its frame range")

    exclusions: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for index, item in enumerate(plan.get("source_exclusion_ranges") or []):
        span = _span(item.get("source_frames"), f"source_exclusion_ranges[{index}]", errors)
        path = item.get("path")
        if span and isinstance(path, str) and path:
            exclusions[path].append(span)
        elif not path:
            errors.append(f"source_exclusion_ranges[{index}]: missing path")

    source_ranges: dict[str, list[tuple[tuple[int, int], str]]] = defaultdict(list)
    output_ranges: list[tuple[tuple[int, int], str]] = []
    replacement_total = 0

    for window_index, window in enumerate(windows):
        window_id = str(window.get("window_id") or f"window[{window_index}]")
        original = _span(window.get("original_timeline_frames"), f"{window_id}.original", errors)
        output = _span(window.get("output_timeline_frames"), f"{window_id}.output", errors)
        required = window.get("required_frames")
        if output and required != output[1] - output[0]:
            errors.append(f"{window_id}: required_frames does not match output range")
        if original and required != original[1] - original[0]:
            errors.append(f"{window_id}: required_frames does not match original range")
        if original and output and cut_source and isinstance(cut_frames, int):
            expected_shift = cut_frames if original[0] >= cut_source[1] else 0
            if output != (original[0] - expected_shift, original[1] - expected_shift):
                errors.append(f"{window_id}: output range does not preserve the declared cut shift")

        segments = window.get("segments") or []
        cursor = output[0] if output else None
        segment_total = 0
        for segment_index, segment in enumerate(segments):
            label = f"{window_id}.segments[{segment_index}]"
            source = _span(segment.get("source_frames"), f"{label}.source_frames", errors)
            segment_output = _span(
                segment.get("output_timeline_frames"),
                f"{label}.output_timeline_frames",
                errors,
            )
            count = segment.get("frame_count")
            if source and count != source[1] - source[0]:
                errors.append(f"{label}: frame_count does not match source range")
            if segment_output and count != segment_output[1] - segment_output[0]:
                errors.append(f"{label}: frame_count does not match output range")
            if segment_output and cursor is not None and segment_output[0] != cursor:
                errors.append(f"{label}: output segments are not contiguous")
            if segment_output:
                cursor = segment_output[1]
            if isinstance(count, int):
                segment_total += count

            path = segment.get("path")
            if source and isinstance(path, str) and path:
                for excluded in exclusions[path]:
                    if _overlaps(source, excluded):
                        errors.append(f"{label}: source range overlaps excluded frames {excluded}")
                for prior, prior_label in source_ranges[path]:
                    if _overlaps(source, prior):
                        errors.append(f"{label}: source range overlaps {prior_label}")
                source_ranges[path].append((source, label))
            elif not path:
                errors.append(f"{label}: missing path")

        if output and cursor != output[1]:
            errors.append(f"{window_id}: segments do not cover the full output window")
        if isinstance(required, int) and segment_total != required:
            errors.append(f"{window_id}: segment frame sum does not equal required_frames")
        if isinstance(required, int):
            replacement_total += required
        if output:
            for prior, prior_label in output_ranges:
                if _overlaps(output, prior):
                    errors.append(f"{window_id}: output window overlaps {prior_label}")
            output_ranges.append((output, window_id))

    accounting = plan.get("frame_accounting") or {}
    if accounting.get("total_replacement_frames") != replacement_total:
        errors.append("frame_accounting.total_replacement_frames does not match window sum")
    if accounting.get("source_range_overlap_count") != 0:
        errors.append("frame_accounting.source_range_overlap_count must be zero")
    for key in ("retime_count", "freeze_count", "loop_count"):
        if accounting.get(key) != 0:
            errors.append(f"frame_accounting.{key} must be zero")

    target_frames = plan.get("target_output_frames")
    fps = plan.get("fps")
    target_seconds = plan.get("target_output_seconds")
    if isinstance(target_frames, int) and isinstance(fps, (int, float)) and isinstance(target_seconds, (int, float)):
        if abs(target_frames / fps - target_seconds) > 1e-9:
            errors.append("target_output_frames/fps does not equal target_output_seconds")
    else:
        errors.append("target frame, fps, or duration metadata is missing")

    return {
        "schema": "qingshan.frame_binding_validation.v2",
        "status": "PASS" if not errors else "FAIL",
        "checks_performed": [
            {"name": name, "result": "PASS" if not errors else "EXECUTED_WITH_FAILURES"}
            for name in check_names
        ],
        "check_count": len(check_names),
        "window_count": len(windows),
        "replacement_frames": replacement_total,
        "source_path_count": len(source_ranges),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.plan.read_text(encoding="utf-8")))
    rendered = json.dumps(result, indent=2, ensure_ascii=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
