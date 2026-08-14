#!/usr/bin/env python3
"""Bind E37 burned-subtitle timing to full-cut native-dialogue ASR evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


def chinese(value: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", value))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timed_asr_characters(segments: list[dict]) -> tuple[str, list[tuple[float, float]]]:
    chars: list[str] = []
    times: list[tuple[float, float]] = []
    for segment in segments:
        text = chinese(str(segment.get("text") or ""))
        if not text:
            continue
        start = float(segment["start"])
        end = float(segment["end"])
        step = max(0.01, (end - start) / len(text))
        for index, char in enumerate(text):
            chars.append(char)
            times.append((start + step * index, min(end, start + step * (index + 1))))
    return "".join(chars), times


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--asr", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    project = json.loads(args.project.read_text(encoding="utf-8"))
    asr = json.loads(args.asr.read_text(encoding="utf-8"))
    captions = sorted(
        [clip for track in project["timeline"]["subtitleTracks"] for clip in track["clips"]],
        key=lambda row: float(row["start"]),
    )
    actual, actual_times = timed_asr_characters(asr["segments"])

    rows = []
    for caption in captions:
        text = chinese(caption["text"])
        caption_start = float(caption["start"])
        caption_end = caption_start + float(caption["duration"])
        local_indices = [
            index for index, (start, end) in enumerate(actual_times)
            if (start + end) / 2 >= caption_start - 3.0 and (start + end) / 2 <= caption_end + 3.0
        ]
        local_actual = "".join(actual[index] for index in local_indices)
        matched_local_indices = []
        for block in SequenceMatcher(None, text, local_actual).get_matching_blocks():
            matched_local_indices.extend(range(block.b, block.b + block.size))
        indices = [local_indices[index] for index in matched_local_indices]
        recall = len(indices) / max(1, len(text))
        if indices:
            asr_start = actual_times[min(indices)][0]
            asr_end = actual_times[max(indices)][1]
            overlap = max(0.0, min(caption_end, asr_end) - max(caption_start, asr_start))
            asr_span = max(0.01, asr_end - asr_start)
            overlap_ratio = overlap / asr_span
            start_delta = caption_start - asr_start
            end_delta = caption_end - asr_end
        else:
            asr_start = asr_end = overlap_ratio = start_delta = end_delta = None
        failures = []
        if recall < 0.35:
            failures.append("LEXICAL_RECALL_BELOW_0P35")
        if overlap_ratio is not None and overlap_ratio < 0.5:
            failures.append("ASR_SPEECH_OVERLAP_BELOW_0P50")
        if start_delta is not None and abs(start_delta) > 1.25:
            failures.append("CAPTION_START_DELTA_ABOVE_1P25S")
        if end_delta is not None and abs(end_delta) > 1.25:
            failures.append("CAPTION_END_DELTA_ABOVE_1P25S")
        rows.append(
            {
                "dialogue_id": caption["dialogue_id"],
                "text": caption["text"],
                "caption_start": round(caption_start, 3),
                "caption_end": round(caption_end, 3),
                "asr_start": round(asr_start, 3) if asr_start is not None else None,
                "asr_end": round(asr_end, 3) if asr_end is not None else None,
                "lexical_recall": round(recall, 3),
                "asr_speech_overlap_ratio": round(overlap_ratio, 3) if overlap_ratio is not None else None,
                "caption_start_minus_asr_start_seconds": round(start_delta, 3) if start_delta is not None else None,
                "caption_end_minus_asr_end_seconds": round(end_delta, 3) if end_delta is not None else None,
                "status": "PASS" if not failures else "FAIL",
                "failures": failures,
            }
        )
    failed = [row for row in rows if row["status"] == "FAIL"]
    report = {
        "schema": "qingshan.e37.fullcut_subtitle_native_asr_timing.v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS" if not failed else "FAIL",
        "video": str(args.video),
        "video_sha256": sha256(args.video),
        "project": str(args.project),
        "project_sha256": sha256(args.project),
        "asr_report": str(args.asr),
        "asr_report_sha256": sha256(args.asr),
        "caption_count": len(rows),
        "passed_count": len(rows) - len(failed),
        "failed_count": len(failed),
        "failed_dialogue_ids": [row["dialogue_id"] for row in failed],
        "thresholds": {
            "local_asr_search_padding_seconds": 3.0,
            "minimum_lexical_recall": 0.35,
            "minimum_asr_speech_overlap_ratio": 0.5,
            "maximum_absolute_start_delta_seconds": 1.25,
            "maximum_absolute_end_delta_seconds": 1.25,
        },
        "rows": rows,
        "limitations": [
            "ASR segment timestamps are distributed uniformly across Chinese characters within each segment.",
            "This diagnostic cannot replace direct lip-sync, breath, expression or uninterrupted playback review.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "failed_dialogue_ids": report["failed_dialogue_ids"]}))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
