#!/usr/bin/env python3
"""Build a frame-exact E17 pacing diagnostic by weaving real A/B/insert sources."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GROUPS = [(7, 8), (11, 12, 13, 14, 15), (16, 17), (23, 24)]


def split_segment(
    segment: dict, fps: int, max_chunk_frames: int, min_chunk_frames: int = 20
) -> list[dict]:
    total = int(segment["expected_frames"])
    base_in_frame = round(float(segment.get("in_sec", 0.0)) * fps)
    chunk_count = max(1, (total + max_chunk_frames - 1) // max_chunk_frames)
    base_size, larger_chunks = divmod(total, chunk_count)
    sizes = [base_size + 1] * larger_chunks + [base_size] * (chunk_count - larger_chunks)
    if chunk_count > 1 and min(sizes) < min_chunk_frames:
        raise ValueError(
            f"Cannot split {total} frames into chunks between "
            f"{min_chunk_frames} and {max_chunk_frames} frames"
        )
    chunks = []
    offset = 0
    for index, frames in enumerate(sizes, start=1):
        row = deepcopy(segment)
        row["in_sec"] = (base_in_frame + offset) / fps
        row["duration_sec"] = frames / fps
        row["expected_frames"] = frames
        row["pacing_chunk_index"] = index
        row["pacing_parent_expected_frames"] = total
        chunks.append(row)
        offset += frames
    return chunks


def weave_group(segments: list[dict], fps: int, max_chunk_frames: int) -> list[dict]:
    queues = [split_segment(row, fps, max_chunk_frames) for row in segments]
    output = []
    while any(queues):
        for queue in queues:
            if queue:
                output.append(queue.pop(0))
    return output


def build(plan: dict, groups: list[tuple[int, ...]], max_chunk_frames: int) -> dict:
    fps = int(plan["fps"])
    original = plan["segments"]
    grouped = {index for group in groups for index in group}
    if len(grouped) != sum(len(group) for group in groups):
        raise ValueError("Pacing groups overlap.")
    if not grouped or min(grouped) < 1 or max(grouped) > len(original):
        raise ValueError("Pacing group index is outside the render plan.")

    by_start = {group[0]: group for group in groups}
    output = []
    index = 1
    while index <= len(original):
        if index in by_start:
            group = by_start[index]
            if tuple(range(group[0], group[-1] + 1)) != group:
                raise ValueError("Each pacing group must be contiguous.")
            rows = [original[pos - 1] for pos in group]
            output.extend(weave_group(rows, fps, max_chunk_frames))
            index = group[-1] + 1
        elif index in grouped:
            index += 1
        else:
            output.append(deepcopy(original[index - 1]))
            index += 1

    result = deepcopy(plan)
    result["schema"] = "qingshan.frame_exact_video_plan.v3"
    result["status"] = "LOCAL_PACING_DIAGNOSTIC_ONLY"
    result["supersedes"] = "configs/e17_remake_full_compiled_render_plan_v2_20260716.json"
    result["pacing_contract"] = {
        "method": "WEAVE_UNIQUE_CONTIGUOUS_SUBRANGES_ACROSS_EXISTING_A_B_INSERT_SOURCES",
        "group_indices_one_based": [list(group) for group in groups],
        "max_chunk_frames": max_chunk_frames,
        "max_chunk_seconds": max_chunk_frames / fps,
        "retime_freeze_loop": False,
        "candidate_audio_included": False,
    }
    result["segments"] = output
    result["expected_frames"] = sum(int(row["expected_frames"]) for row in output)
    result["expected_duration_seconds"] = result["expected_frames"] / fps
    result["pacing_summary"] = {
        "original_segment_count": len(original),
        "finecut_segment_count": len(output),
        "average_shot_length_seconds": result["expected_duration_seconds"] / len(output),
        "segments_over_8_seconds": sum(float(row["duration_sec"]) > 8.0 for row in output),
        "unique_source_subranges_only": True,
    }
    if result["expected_frames"] != int(plan["expected_frames"]):
        raise ValueError("Fine-cut frame total changed.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--plan",
        default=str(ROOT / "configs/e17_remake_full_compiled_render_plan_v2_20260716.json"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "configs/e17_remake_pacing_finecut_plan_v1_20260716.json"),
    )
    parser.add_argument("--max-chunk-frames", type=int, default=72)
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    result = build(plan, DEFAULT_GROUPS, args.max_chunk_frames)
    out = Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["pacing_summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
