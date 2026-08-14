#!/usr/bin/env python3
"""Export a timeline-ordered shot manifest from an AgentCut project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    project = json.loads(args.project.read_text(encoding="utf-8"))
    track = project["timeline"]["videoTracks"][0]
    shots = []
    for clip in sorted(track["clips"], key=lambda row: float(row["start"])):
        start = float(clip["start"])
        metadata = clip.get("metadata") or {}
        shots.append({
            "shot_id": clip["id"],
            "scene_id": metadata.get("beat_id") or metadata.get("scene_id"),
            "start": start,
            "end": start + float(clip["duration"]),
            "source": clip["source"],
            "dialogue_id": metadata.get("dialogue_id"),
        })
    payload = {
        "schema": "qingshan.agentcut_shot_timeline.v1",
        "source_track_id": track["id"],
        "shots": shots,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
