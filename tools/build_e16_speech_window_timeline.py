#!/usr/bin/env python3
"""Create the ordered scene timeline used by E16 final-MP4 brightness QA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edl", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    edl = json.loads(Path(args.edl).read_text(encoding="utf-8"))
    rows = []
    clock = 0.0
    for index, item in enumerate(edl["segments"], 1):
        duration = float(item["target_duration"])
        rows.append({
            "shot_id": item["dialogue_id"],
            "scene_id": item.get("scene_id", "SCENE-E16-医馆正堂-雨前夜" if index <= 57 else "SCENE-E16-医馆后院-尸体旁"),
            "start": round(clock, 3),
            "end": round(clock + duration, 3),
        })
        clock += duration
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema": "qingshan.e16.speech_window_final_timeline.v1", "shots": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "shots": len(rows), "duration": round(clock, 3)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
