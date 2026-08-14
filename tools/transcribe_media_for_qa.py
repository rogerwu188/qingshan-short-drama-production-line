#!/usr/bin/env python3
"""Transcribe one media file and exit so model memory is returned to the OS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        args.media, language="zh", vad_filter=True, beam_size=5
    )
    payload = {
        "duration": round(info.duration, 4),
        "segments": [
            {
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "text": segment.text.strip(),
            }
            for segment in segments
        ],
    }
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
