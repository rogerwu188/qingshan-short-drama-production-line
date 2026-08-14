#!/usr/bin/env python3
"""Convert one AgentCut video track into final-timeline shot audit rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_timeline(project: dict, track_id: str) -> dict:
    tracks = project.get("timeline", {}).get("videoTracks", [])
    track = next((item for item in tracks if item.get("id") == track_id), None)
    if track is None:
        raise ValueError(f"Missing AgentCut video track: {track_id}")

    shots = []
    for index, clip in enumerate(track.get("clips", []), start=1):
        start = float(clip["start"])
        duration = float(clip["duration"])
        metadata = clip.get("metadata") or {}
        scene_id = str(metadata.get("scene_id") or metadata.get("beat_id") or "UNASSIGNED")
        shots.append({
            "shot_id": str(clip.get("id") or f"{track_id}-{index:03d}"),
            "scene_id": scene_id,
            "start": start,
            "end": start + duration,
            "source": clip.get("source"),
            "dialogue_id": metadata.get("dialogue_id"),
        })

    shots.sort(key=lambda row: row["start"])
    return {
        "schema": "qingshan.agentcut_shot_timeline.v1",
        "source_track_id": track_id,
        "shots": shots,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--track-id", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    project_path = Path(args.project).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    try:
        payload = build_timeline(project, args.track_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    payload["source_project"] = str(project_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out_path), "shot_count": len(payload["shots"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
