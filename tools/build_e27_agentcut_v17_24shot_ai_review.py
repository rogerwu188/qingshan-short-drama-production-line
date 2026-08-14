#!/usr/bin/env python3
"""Build one parallel full-resolution visual/OCR review item per E27 V17 shot."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
VIDEO = ROOT / "exports/e27/agentcut_v17_n01_baseline_repair_20260720/E27_AGENTCUT_V17_N01_BASELINE_REPAIR_NOT_FINAL.mp4"
TIMELINE = ROOT / "qa/e27_agentcut_v17_n01_baseline_repair_20260720/E27_V17_FINAL_TIMELINE_SHOTS.json"
OUT = ROOT / "qa/e27_agentcut_v17_24shot_ai_review_20260720"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    timeline = json.loads(TIMELINE.read_text(encoding="utf-8"))
    frames_dir = OUT / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    video_sha = sha256(VIDEO)
    items = []
    inventory = []
    for index, shot in enumerate(timeline["shots"], 1):
        midpoint = (float(shot["start"]) + float(shot["end"])) / 2.0
        frame = frames_dir / f"{index:02d}_{shot['shot_id']}_midpoint.png"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{midpoint:.3f}", "-i", str(VIDEO), "-frames:v", "1", str(frame),
            ],
            check=True,
        )
        frame_sha = sha256(frame)
        items.append(
            {
                "path": str(frame),
                "scope": "ordered_shot_midpoint",
                "kind": "image",
                "importance": "critical",
                "pass_score": 4.5,
                "clip_id": shot["shot_id"],
                "metadata": {
                    "episode": "E27",
                    "shot_id": shot["shot_id"],
                    "scene_id": shot["scene_id"],
                    "shot_start": shot["start"],
                    "shot_end": shot["end"],
                    "midpoint": midpoint,
                    "candidate_video_path": str(VIDEO),
                    "candidate_video_sha256": video_sha,
                    "frame_sha256": frame_sha,
                    "expected_dialogue_ids": shot.get("dialogue_ids", []),
                    "expected_text": shot.get("expected_text", ""),
                    "review_focus": [
                        "canonical identity and costume continuity for this exact ordered shot",
                        "scene location, time of day and story action match the locked timeline",
                        "action is immediately readable at normal viewing size",
                        "no readable or pseudo-readable text outside approved NALU MOTION outro",
                        "no duplicated bodies, malformed anatomy, black frame or frozen filler",
                    ],
                },
                "required_capabilities": ["image_analysis", "ocr"],
                "run_regression_ci": True,
                "use_existing_tools": True,
            }
        )
        inventory.append({"shot_id": shot["shot_id"], "frame": str(frame), "frame_sha256": frame_sha, "midpoint": midpoint})
    request = OUT / "E27_AGENTCUT_V17_24SHOT_AI_REVIEW_REQUEST.json"
    request.write_text(json.dumps({"items": items, "workers": 4}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inventory_path = OUT / "E27_AGENTCUT_V17_24SHOT_AI_REVIEW_INVENTORY.json"
    inventory_path.write_text(
        json.dumps(
            {
                "video": str(VIDEO),
                "video_sha256": video_sha,
                "timeline": str(TIMELINE),
                "timeline_sha256": sha256(TIMELINE),
                "items": inventory,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "request": str(request), "items": len(items), "video_sha256": video_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
