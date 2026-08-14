#!/usr/bin/env python3
"""Derive repeatable audience-gate evidence from an AgentCut project."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def build(project_path: Path) -> dict:
    project = json.loads(project_path.read_text(encoding="utf-8"))
    clips = [
        clip
        for track in project["timeline"]["videoTracks"]
        for clip in track.get("clips", [])
    ]
    total = sum(float(clip["duration"]) for clip in clips)
    if total <= 0:
        raise ValueError("video timeline must have positive duration")

    source_seconds: dict[str, float] = defaultdict(float)
    beat_rows: dict[str, dict] = {}
    for clip in clips:
        source_group = Path(clip["source"]).stem
        duration = float(clip["duration"])
        source_seconds[source_group] += duration
        beat_id = clip.get("metadata", {}).get("beat_id") or "UNASSIGNED"
        row = beat_rows.setdefault(
            beat_id,
            {"beat_id": beat_id, "start": float(clip["start"]), "end": 0.0, "clip_count": 0, "sources": []},
        )
        row["start"] = min(row["start"], float(clip["start"]))
        row["end"] = max(row["end"], float(clip["start"]) + duration)
        row["clip_count"] += 1
        if source_group not in row["sources"]:
            row["sources"].append(source_group)

    return {
        "schema": "qingshan.agentcut_audience_evidence.v1",
        "project": str(project_path.resolve()),
        "timeline_duration_seconds": total,
        "semantic_group_basis": "agentcut_source_identity",
        "semantic_group_pct": {
            key: round(seconds / total * 100.0, 6)
            for key, seconds in sorted(source_seconds.items(), key=lambda item: (-item[1], item[0]))
        },
        "scene_rotation_table": sorted(beat_rows.values(), key=lambda row: row["start"]),
        "shots": [
            {
                "shot_id": clip["id"],
                "scene_id": clip.get("metadata", {}).get("beat_id") or "UNASSIGNED",
                "start": float(clip["start"]),
                "end": float(clip["start"]) + float(clip["duration"]),
            }
            for clip in clips
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    evidence = build(args.project.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out.resolve()), "groups": len(evidence["semantic_group_pct"]), "beats": len(evidence["scene_rotation_table"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
