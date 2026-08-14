#!/usr/bin/env python3
"""Reconcile intended AgentCut clip boundaries with detected visual cuts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--regression", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--tolerance", type=float, default=0.10)
    return parser.parse_args()


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    args = parse_args()
    project = load_json(args.project)
    regression = load_json(args.regression)
    clips = project["timeline"]["videoTracks"][0]["clips"]
    detected = [float(value) for value in regression["asl"]["cut_times"]]

    boundaries = []
    for clip in clips[1:]:
        intended = float(clip["start"])
        nearest = min(detected, key=lambda value: abs(value - intended), default=None)
        delta = abs(nearest - intended) if nearest is not None else None
        metadata = clip.get("metadata", {})
        boundaries.append(
            {
                "right_clip_id": clip["id"],
                "dialogue_id": metadata.get("dialogue_id"),
                "beat_id": metadata.get("beat_id"),
                "speaker": metadata.get("speaker"),
                "intended_seconds": round(intended, 6),
                "nearest_detected_seconds": round(nearest, 6) if nearest is not None else None,
                "delta_seconds": round(delta, 6) if delta is not None else None,
                "visual_cut_detected": delta is not None and delta <= args.tolerance,
                "source": clip["source"],
            }
        )

    missing = [item for item in boundaries if not item["visual_cut_detected"]]
    report = {
        "schema": "qingshan.agentcut.visual-boundary-reconciliation.v1",
        "status": "PASS" if not missing else "FAIL_MISSING_VISUAL_BOUNDARIES",
        "project": str(args.project.resolve()),
        "regression": str(args.regression.resolve()),
        "tolerance_seconds": args.tolerance,
        "intended_boundary_count": len(boundaries),
        "detected_cut_count": len(detected),
        "matched_boundary_count": len(boundaries) - len(missing),
        "missing_boundary_count": len(missing),
        "missing_dialogue_ids": [item["dialogue_id"] for item in missing],
        "boundaries": boundaries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({key: report[key] for key in (
        "status", "intended_boundary_count", "detected_cut_count",
        "matched_boundary_count", "missing_boundary_count", "missing_dialogue_ids"
    )}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
