#!/usr/bin/env python3
"""Remove E17 fine-cut flash fragments without retime, freeze, loop, or frame loss."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FPS = 24


def balanced_sizes(total: int, maximum: int = 72, minimum: int = 20) -> list[int]:
    count = max(1, (total + maximum - 1) // maximum)
    base, remainder = divmod(total, count)
    sizes = [base + 1] * remainder + [base] * (count - remainder)
    if count > 1 and min(sizes) < minimum:
        raise ValueError(f"Cannot balance {total} frames within {minimum}..{maximum}")
    return sizes


def rebalance_split_parents(segments: list[dict]) -> None:
    groups: dict[tuple, list[dict]] = {}
    for row in segments:
        if "pacing_parent_expected_frames" not in row:
            continue
        key = (row["source_id"], row["path"], row["pacing_parent_expected_frames"])
        groups.setdefault(key, []).append(row)
    for rows in groups.values():
        rows.sort(key=lambda item: item["pacing_chunk_index"])
        total = int(rows[0]["pacing_parent_expected_frames"])
        start_frame = min(round(float(item["in_sec"]) * FPS) for item in rows)
        sizes = balanced_sizes(total)
        if len(sizes) != len(rows):
            raise ValueError("Existing pacing chunk count differs from balanced count")
        offset = 0
        for index, (row, frames) in enumerate(zip(rows, sizes), start=1):
            row["in_sec"] = (start_frame + offset) / FPS
            row["duration_sec"] = frames / FPS
            row["expected_frames"] = frames
            row["pacing_chunk_index"] = index
            offset += frames


def replace_early_flash_pair(segments: list[dict]) -> None:
    ids = [row["source_id"] for row in segments]
    first = ids.index("REPL_EARLY_BED01_R2")
    if ids[first + 1] != "REPL_EARLY_BED07_TAIL":
        raise ValueError("Early flash pair is no longer adjacent")
    frames = int(segments[first]["expected_frames"]) + int(segments[first + 1]["expected_frames"])
    replacement = {
        "source_id": "V6_001_E17-EST-01_RESIDUAL_HOLD",
        "path": "working_assets/e17_second_wave_video_20260714/E17-EST-01/result_01.mp4",
        "in_sec": 2.5,
        "duration_sec": frames / FPS,
        "expected_frames": frames,
        "refinement_reason": "REPLACE_TWO_SUB_0_8_SECOND_FLASH_CUTS_WITH_UNUSED_CONTIGUOUS_ESTABLISHING_ACTION",
    }
    segments[first : first + 2] = [replacement]


def absorb_src007_separator(segments: list[dict]) -> None:
    ids = [row["source_id"] for row in segments]
    separator = ids.index("REPL_SRC007_SEPARATOR")
    frames = int(segments[separator]["expected_frames"])
    if frames != 7:
        raise ValueError("Expected the known seven-frame SRC007 separator")
    ins05 = segments[ids.index("REPL_INS05_R2")]
    ins03b = segments[ids.index("REPL_INS03_B")]
    ins05["expected_frames"] += 1
    ins05["duration_sec"] = ins05["expected_frames"] / FPS
    ins05["refinement_reason"] = "ABSORB_ONE_AVAILABLE_CONTIGUOUS_SOURCE_FRAME"
    ins03b["expected_frames"] += 6
    ins03b["duration_sec"] = ins03b["expected_frames"] / FPS
    ins03b["refinement_reason"] = "EXTEND_INSERT_TO_EXACT_TWO_SECOND_LIMIT"
    del segments[separator]


def assert_no_overlap(segments: list[dict]) -> None:
    by_path: dict[str, list[tuple[int, int, str]]] = {}
    for row in segments:
        start = round(float(row.get("in_sec", 0.0)) * FPS)
        end = start + int(row["expected_frames"])
        by_path.setdefault(row["path"], []).append((start, end, row["source_id"]))
    for path, intervals in by_path.items():
        intervals.sort()
        for left, right in zip(intervals, intervals[1:]):
            if right[0] < left[1]:
                raise ValueError(f"Source overlap in {path}: {left} vs {right}")


def refine(plan: dict) -> dict:
    result = deepcopy(plan)
    before_frames = sum(int(row["expected_frames"]) for row in result["segments"])
    rebalance_split_parents(result["segments"])
    replace_early_flash_pair(result["segments"])
    absorb_src007_separator(result["segments"])
    after_frames = sum(int(row["expected_frames"]) for row in result["segments"])
    if after_frames != before_frames or after_frames != int(result["expected_frames"]):
        raise ValueError("Residual refinement changed the frame total")
    assert_no_overlap(result["segments"])
    short = [row for row in result["segments"] if int(row["expected_frames"]) < 20]
    if short:
        raise ValueError(f"Residual sub-0.8-second segments remain: {short}")
    result["schema"] = "qingshan.frame_exact_video_plan.v4"
    result["status"] = "LOCAL_PACING_REFINED_DIAGNOSTIC_ONLY"
    result["supersedes"] = "configs/e17_remake_pacing_finecut_plan_v1_20260716.json"
    result["refinement_contract"] = {
        "minimum_segment_frames": 20,
        "minimum_segment_seconds": 20 / FPS,
        "retime_freeze_loop": False,
        "source_subrange_overlap": False,
        "frame_total_preserved": True,
        "operations": [
            "BALANCE_SPLIT_PARENT_CHUNKS",
            "REPLACE_EARLY_DOUBLE_FLASH_WITH_UNUSED_EST01_SUBRANGE",
            "ABSORB_SEVEN_FRAME_SEPARATOR_INTO_CONTIGUOUS_INSERT_SOURCE_FRAMES",
        ],
    }
    count = len(result["segments"])
    result["pacing_summary"].update(
        {
            "finecut_segment_count": count,
            "average_shot_length_seconds": result["expected_duration_seconds"] / count,
            "segments_under_0_8_seconds": 0,
            "segments_over_8_seconds": sum(float(row["duration_sec"]) > 8.0 for row in result["segments"]),
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=ROOT / "configs/e17_remake_pacing_finecut_plan_v1_20260716.json")
    parser.add_argument("--out", type=Path, default=ROOT / "configs/e17_remake_pacing_finecut_plan_v2_20260716.json")
    args = parser.parse_args()
    result = refine(json.loads(args.plan.read_text(encoding="utf-8")))
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["pacing_summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
