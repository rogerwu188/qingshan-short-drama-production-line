#!/usr/bin/env python3
"""Rebuild AgentCut dialogue and caption windows from source-level ASR timing."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


def chinese_only(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", text))


def span_score(expected: str, text: str) -> tuple[float, float, int]:
    exp = chinese_only(expected)
    got = chinese_only(text)
    if not exp or not got:
        return (0.0, 0.0, -len(got))
    ratio = SequenceMatcher(None, exp, got).ratio()
    matched = sum(
        block.size for block in SequenceMatcher(None, exp, got).get_matching_blocks()
    )
    recall = matched / len(exp)
    return (ratio, recall, -abs(len(got) - len(exp)))


def best_speech_span(expected: str, segments: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = []
    for left in range(len(segments)):
        for right in range(left, len(segments)):
            selected = segments[left : right + 1]
            text = "".join(row["text"] for row in selected)
            candidates.append(
                {
                    "start": float(selected[0]["start"]),
                    "end": float(selected[-1]["end"]),
                    "text": text,
                    "segment_indices": [left, right],
                    "score": span_score(expected, text),
                }
            )
    if not candidates:
        raise ValueError("No ASR segments available")
    return max(candidates, key=lambda row: row["score"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--sentence-report", type=Path, required=True)
    parser.add_argument("--out-project", type=Path, required=True)
    parser.add_argument("--out-report", type=Path, required=True)
    parser.add_argument("--output-media", type=Path, required=True)
    parser.add_argument("--head-pad", type=float, default=0.12)
    parser.add_argument("--tail-pad", type=float, default=0.12)
    parser.add_argument("--min-gap", type=float, default=0.04)
    args = parser.parse_args()

    project = json.loads(args.project.read_text())
    sentences = json.loads(args.sentence_report.read_text())
    sentence_by_id = {row["id"]: row for row in sentences["sentences"]}
    rebuilt = deepcopy(project)
    rebuilt["output"]["path"] = str(args.output_media.expanduser().resolve())

    dialogue_track = next(
        track
        for track in rebuilt["timeline"]["audioTracks"]
        if track.get("clips")
        and all(clip.get("metadata", {}).get("dialogue_id") for clip in track["clips"])
    )
    captions = rebuilt["timeline"]["subtitleTracks"][0]["clips"]
    caption_by_id = {row["dialogue_id"]: row for row in captions}
    audio_by_id = {
        clip["metadata"]["dialogue_id"]: clip for clip in dialogue_track["clips"]
    }
    rows = []

    for clip in dialogue_track["clips"]:
        dialogue_id = clip["metadata"]["dialogue_id"]
        sentence = sentence_by_id[dialogue_id]
        span = best_speech_span(sentence["expected"], sentence["segments"])
        source_duration = float(sentence["source_duration"])
        source_in = max(0.0, span["start"] - args.head_pad)
        source_out = min(source_duration, span["end"] + args.tail_pad)
        duration = source_out - source_in
        clip["in"] = round(source_in, 6)
        clip["duration"] = round(duration, 6)
        clip["transitionIn"] = {"type": "fade", "duration": 0.02}
        clip["transitionOut"] = {"type": "fade", "duration": 0.02}
        clip.setdefault("metadata", {})["asr_window_rebuilt"] = True
        clip["metadata"]["asr_selected_text"] = span["text"]

        caption = caption_by_id[dialogue_id]
        caption["start"] = round(
            float(clip["start"]) + span["start"] - source_in, 6
        )
        caption["duration"] = round(span["end"] - span["start"], 6)
        rows.append(
            {
                "dialogue_id": dialogue_id,
                "expected": sentence["expected"],
                "selected_asr": span["text"],
                "selection_score": {
                    "ratio": round(span["score"][0], 3),
                    "recall": round(span["score"][1], 3),
                },
                "source_in": round(source_in, 6),
                "source_out": round(source_out, 6),
                "audio_timeline_start": clip["start"],
                "audio_timeline_end": round(float(clip["start"]) + duration, 6),
                "caption_start": caption["start"],
                "caption_end": round(caption["start"] + caption["duration"], 6),
            }
        )

    ordered = sorted(rows, key=lambda row: row["audio_timeline_start"])
    shifts = []
    for index, row in enumerate(ordered):
        if index == 0:
            continue
        previous = ordered[index - 1]
        required_start = previous["audio_timeline_end"] + args.min_gap
        if row["audio_timeline_start"] + 0.000001 >= required_start:
            continue
        delta = required_start - row["audio_timeline_start"]
        row["audio_timeline_start"] = round(required_start, 6)
        row["audio_timeline_end"] = round(row["audio_timeline_end"] + delta, 6)
        row["caption_start"] = round(row["caption_start"] + delta, 6)
        row["caption_end"] = round(row["caption_end"] + delta, 6)
        audio_by_id[row["dialogue_id"]]["start"] = row["audio_timeline_start"]
        caption_by_id[row["dialogue_id"]]["start"] = row["caption_start"]
        shifts.append(
            {
                "dialogue_id": row["dialogue_id"],
                "shift_seconds": round(delta, 6),
                "reason": "prevent_dialogue_overlap",
            }
        )

    overlaps = []
    for left, right in zip(ordered, ordered[1:]):
        available = right["audio_timeline_start"] - left["audio_timeline_end"]
        if available + 0.000001 < args.min_gap:
            overlaps.append(
                {
                    "left": left["dialogue_id"],
                    "right": right["dialogue_id"],
                    "gap_seconds": round(available, 6),
                }
            )

    timeline_end = max(
        float(clip["start"]) + float(clip["duration"])
        for clip in rebuilt["timeline"]["videoTracks"][0]["clips"]
    )
    out_of_bounds = [
        row for row in rows if row["audio_timeline_end"] > timeline_end + 0.001
    ]
    report = {
        "schema": "qingshan.agentcut_dialogue_window_rebuild.v1",
        "status": "PASS" if not overlaps and not out_of_bounds else "FAIL",
        "source_project": str(args.project.resolve()),
        "source_sentence_report": str(args.sentence_report.resolve()),
        "dialogue_count": len(rows),
        "caption_count": len(captions),
        "head_pad": args.head_pad,
        "tail_pad": args.tail_pad,
        "minimum_gap": args.min_gap,
        "timeline_shifts": shifts,
        "overlaps": overlaps,
        "out_of_bounds": out_of_bounds,
        "rows": rows,
    }
    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if report["status"] == "PASS":
        args.out_project.parent.mkdir(parents=True, exist_ok=True)
        args.out_project.write_text(
            json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n"
        )
    print(
        json.dumps(
            {
                "status": report["status"],
                "dialogues": len(rows),
                "overlaps": len(overlaps),
                "out_of_bounds": len(out_of_bounds),
                "out_project": str(args.out_project),
                "out_report": str(args.out_report),
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
