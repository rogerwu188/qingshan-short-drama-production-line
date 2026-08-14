#!/usr/bin/env python3
"""Derive E16 A-source windows from observed speech boundaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edl", required=True)
    parser.add_argument("--asr", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pad", type=float, default=0.10)
    args = parser.parse_args()

    edl = json.loads(Path(args.edl).read_text(encoding="utf-8"))
    asr_rows = json.loads(Path(args.asr).read_text(encoding="utf-8"))["rows"]
    asr_by_id = {row["dialogue_id"]: row for row in asr_rows}
    segments = []
    for segment in edl["segments"]:
        row = asr_by_id.get(segment["dialogue_id"])
        speech = (row or {}).get("segments") or []
        if not speech:
            raise SystemExit(f"Missing source ASR speech boundary: {segment['dialogue_id']}")
        speech_start = min(float(item["start"]) for item in speech)
        speech_end = max(float(item["end"]) for item in speech)
        a_in = max(0.0, speech_start - args.pad)
        a_out = speech_end + args.pad
        updated = dict(segment)
        updated["a_in"] = round(a_in, 3)
        updated["a_out"] = round(a_out, 3)
        updated["target_duration"] = round(a_out - a_in, 3)
        updated["source_window_policy"] = "SOURCE_ASR_SPEECH_BOUNDS_PLUS_PAD"
        updated["source_speech_start"] = round(speech_start, 3)
        updated["source_speech_end"] = round(speech_end, 3)
        segments.append(updated)

    output = dict(edl)
    output["schema"] = "qingshan.e16.ordered_edit_decision_list.speech_windows.v1"
    output["status"] = "READY_FOR_SPEECH_BOUNDARY_REBUILD"
    output["rules"] = dict(edl.get("rules", {}))
    output["rules"]["audio_window"] = "source ASR speech bounds plus 0.10s head/tail pad"
    output["segments"] = segments
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "segments": len(segments), "runtime_without_bridges": round(sum(item["target_duration"] for item in segments), 3)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
