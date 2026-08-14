#!/usr/bin/env python3
"""Reject NOT-FINAL subtitle placeholders before burn-in."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PLACEHOLDER_MARKERS = {
    "PLACEHOLDER_NOT_FINAL",
    "PLACEHOLDER_READY_NOT_FINAL_SUBTITLES",
    "PENDING_FINAL_DIALOGUE_TEXT_AND_AUDIO_TIMECODE",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def inspect(path: Path) -> dict:
    text = read_text(path)
    markers = sorted(marker for marker in PLACEHOLDER_MARKERS if marker in text)
    status = "BLOCKED_PLACEHOLDER_SUBTITLES" if markers else "PASS_NO_PLACEHOLDER_MARKERS"
    return {
        "schema": "qingshan.subtitle_burn_guard.v1",
        "subtitle_path": str(path),
        "status": status,
        "markers_found": markers,
        "policy": "Subtitle files containing placeholder markers must not be burned into a final package.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Guard subtitle burn-in against placeholder files.")
    parser.add_argument("--subtitle", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    subtitle = Path(args.subtitle).resolve()
    if not subtitle.exists():
        raise SystemExit(f"Missing subtitle file: {subtitle}")
    result = inspect(subtitle)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
