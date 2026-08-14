#!/usr/bin/env python3
"""Derive E34 caption windows from the already-reviewed native-source ASR."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASR = ROOT / "qa/e34_v2_streaming_video_compile_20260723/E34_NATIVE_DIALOGUE_SOURCE_ASR_V2.json"
ADJUDICATION = ROOT / "qa/e34_v2_streaming_video_compile_20260723/E34_U15_DIA021_ASR_HOMOPHONE_ADJUDICATION_V2.json"
OUT = ROOT / "qa/e34_v2_release_20260723/E34_NATIVE_CAPTION_VERIFIED_OVERRIDES_V1.json"


def chinese(value: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", value or ""))


def best_segment_partition(lines: list[dict], segments: list[dict]) -> list[tuple[int, int]]:
    """Partition M>=N contiguous ASR segments into N best matching groups."""
    n, m = len(lines), len(segments)
    scores: dict[tuple[int, int], tuple[float, list[tuple[int, int]]]] = {(0, 0): (0.0, [])}
    for line_index in range(n):
        next_scores = {}
        for (used_lines, start), (score, groups) in scores.items():
            if used_lines != line_index:
                continue
            remaining_lines = n - line_index - 1
            max_end = m - remaining_lines
            for end in range(start + 1, max_end + 1):
                expected = chinese(lines[line_index]["spoken_text"])
                actual = chinese("".join(row["text"] for row in segments[start:end]))
                similarity = SequenceMatcher(None, expected, actual).ratio()
                key = (line_index + 1, end)
                candidate = (score + similarity, groups + [(start, end)])
                if key not in next_scores or candidate[0] > next_scores[key][0]:
                    next_scores[key] = candidate
        scores = next_scores
    return scores[(n, m)][1]


def proportional_ranges(lines: list[dict], start: float, end: float) -> list[tuple[float, float]]:
    weights = [max(1, len(chinese(row["spoken_text"]))) for row in lines]
    cursor = start
    ranges = []
    for index, weight in enumerate(weights):
        line_end = end if index == len(weights) - 1 else cursor + (end - start) * weight / sum(weights)
        ranges.append((cursor, line_end))
        cursor = line_end
    return ranges


def main() -> int:
    report = json.loads(ASR.read_text(encoding="utf-8"))
    adjudication = json.loads(ADJUDICATION.read_text(encoding="utf-8"))
    if report.get("dialogue_line_count") != 43 or report.get("dialogue_line_pass_count") != 42:
        raise SystemExit("E34 source ASR report is not the reviewed 42/43 artifact")
    if adjudication.get("status") != "PASS_MACHINE_HOMOPHONE_ADJUDICATION":
        raise SystemExit("E34 U15 second-pass adjudication is not PASS")
    items = []
    for unit in report["results"]:
        lines, segments = unit["dialogue"], unit["segments"]
        if len(segments) >= len(lines):
            groups = best_segment_partition(lines, segments)
            ranges = [(float(segments[start]["start"]), float(segments[end - 1]["end"])) for start, end in groups]
            methods = ["CONTIGUOUS_ASR_SEGMENT_PARTITION"] * len(lines)
        else:
            ranges = proportional_ranges(lines, float(segments[0]["start"]), float(segments[-1]["end"]))
            methods = ["OBSERVED_ASR_SPEECH_RANGE_PROPORTIONAL_SPLIT"] * len(lines)
        for line, (start, end), method in zip(lines, ranges, methods):
            if end <= start:
                raise SystemExit(f"Invalid caption range: {line['dia_id']}")
            evidence = {
                "source_report": str(ASR.relative_to(ROOT)),
                "source_report_unit_status": unit["status"],
                "method": method,
                "unit_asr_transcript": unit["transcript"],
                "original_line_recall": line["recall_score"],
            }
            if line["dia_id"] == "E34-DIA-021":
                evidence["homophone_adjudication"] = str(ADJUDICATION.relative_to(ROOT))
            items.append({
                "dialogue_id": line["dia_id"], "source_id": unit["unit_id"],
                "source_start": round(max(0.0, start - 0.06), 3),
                "source_end": round(end + 0.10, 3),
                "lexical_recall": 1.0 if line["dia_id"] == "E34-DIA-021" else line["recall_score"],
                "asr_transcript": unit["transcript"], "evidence": evidence,
            })
    if len(items) != 43 or len({row["dialogue_id"] for row in items}) != 43:
        raise SystemExit("E34 verified caption override coverage is not exactly 43/43")
    payload = {
        "schema": "qingshan.native_caption_verified_overrides.v1", "episode": "E34",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_43_OF_43", "policy":
        "Use the already-reviewed native-source ASR speech windows. Never time final subtitles from reference TTS duration.",
        "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "count": len(items), "out": str(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
