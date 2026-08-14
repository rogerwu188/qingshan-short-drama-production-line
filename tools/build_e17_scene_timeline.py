#!/usr/bin/env python3
"""Attach real E17 state-bible scene IDs to the refined frame-exact shot plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SCENE_RANGES = [
    (0.0, 71.125, "SCENE-E17-太平医馆后院-水缸旁"),
    (71.125, 96.125, "ROOM-太平医馆正堂-A/rear-courtyard-threshold"),
    (96.125, 139.8333333333, "SCENE-E17-太平医馆后院-证物圈"),
    (139.8333333333, 162.25, "ALLEY-县衙后门-A"),
    (162.25, 165.25, "CARD-E17-NALU"),
]


def scene_at(start: float, end: float) -> str:
    midpoint = (start + end) / 2
    for lower, upper, scene_id in SCENE_RANGES:
        if lower <= midpoint < upper or (scene_id == "CARD-E17-NALU" and midpoint == upper):
            return scene_id
    raise ValueError(f"No scene ID for {start:.3f}-{end:.3f}")


def build(plan: dict) -> dict:
    fps = int(plan["fps"])
    frame_cursor = 0
    shots = []
    for index, row in enumerate(plan["segments"], start=1):
        frames = int(row["expected_frames"])
        start = frame_cursor / fps
        frame_cursor += frames
        end = frame_cursor / fps
        shots.append(
            {
                "shot_id": f"E17R-V2-SHOT-{index:03d}",
                "source_id": row["source_id"],
                "scene_id": scene_at(start, end),
                "start": start,
                "end": end,
                "expected_frames": frames,
            }
        )
    if frame_cursor != int(plan["expected_frames"]):
        raise ValueError("Scene timeline frame total differs from the render plan")
    return {
        "schema": "qingshan.final_timeline_scene_ids.v1",
        "episode": "E17",
        "status": "DIAGNOSTIC_SCENE_IDS_BOUND_FROM_STATE_BIBLE",
        "final_admission": False,
        "source_plan": "configs/e17_remake_pacing_finecut_plan_v2_20260716.json",
        "state_bible": "configs/e17_state_bible_20260714.json",
        "fps": fps,
        "expected_frames": frame_cursor,
        "expected_duration_seconds": frame_cursor / fps,
        "scene_ids": [row[2] for row in SCENE_RANGES],
        "shots": shots,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=ROOT / "configs/e17_remake_pacing_finecut_plan_v2_20260716.json")
    parser.add_argument("--out", type=Path, default=ROOT / "configs/e17_remake_pacing_refined_scene_timeline_v2_20260716.json")
    args = parser.parse_args()
    result = build(json.loads(args.plan.read_text(encoding="utf-8")))
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"shot_count": len(result["shots"]), "scene_count": len(result["scene_ids"]), "frames": result["expected_frames"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
