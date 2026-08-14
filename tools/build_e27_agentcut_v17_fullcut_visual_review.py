#!/usr/bin/env python3
"""Build the exact-SHA 24-shot visual review sheet for E27 V17."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
VIDEO = ROOT / "exports/e27/agentcut_v17_n01_baseline_repair_20260720/E27_AGENTCUT_V17_N01_BASELINE_REPAIR_NOT_FINAL.mp4"
TIMELINE = ROOT / "qa/e27_agentcut_v17_n01_baseline_repair_20260720/E27_V17_FINAL_TIMELINE_SHOTS.json"
OUT = ROOT / "qa/e27_agentcut_v17_n01_baseline_repair_visual_review_20260720"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    timeline = json.loads(TIMELINE.read_text(encoding="utf-8"))
    frames_dir = OUT / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, shot in enumerate(timeline["shots"], 1):
        midpoint = (float(shot["start"]) + float(shot["end"])) / 2.0
        frame = frames_dir / f"{index:02d}_{shot['shot_id']}.png"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{midpoint:.3f}", "-i", str(VIDEO),
                "-frames:v", "1", "-vf",
                "scale=180:320:force_original_aspect_ratio=decrease,pad=180:320:(ow-iw)/2:(oh-ih)/2:black",
                str(frame),
            ],
            check=True,
        )
        frames.append(frame)
    sheet = OUT / "E27_AGENTCUT_V17_24_SHOT_CONTACT_SHEET.png"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for frame in frames:
        command.extend(["-i", str(frame)])
    inputs = "".join(f"[{index}:v]" for index in range(len(frames)))
    layout = "0_0|180_0|360_0|540_0|0_320|180_320|360_320|540_320|0_640|180_640|360_640|540_640|0_960|180_960|360_960|540_960|0_1280|180_1280|360_1280|540_1280|0_1600|180_1600|360_1600|540_1600"
    command.extend(["-filter_complex", f"{inputs}xstack=inputs=24:layout={layout}[out]", "-map", "[out]", str(sheet)])
    subprocess.run(command, check=True)
    request = OUT / "E27_AGENTCUT_V17_24_SHOT_VISUAL_REVIEW_REQUEST.json"
    request.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "path": str(sheet),
                        "scope": "full_cut_visual_continuity",
                        "kind": "image",
                        "importance": "critical",
                        "pass_score": 4.5,
                        "clip_id": "E27-AGENTCUT-V17-24-SHOT-CONTACT-SHEET",
                        "metadata": {
                            "episode": "E27",
                            "candidate_video_path": str(VIDEO),
                            "candidate_video_sha256": sha256(VIDEO),
                            "timeline_path": str(TIMELINE),
                            "timeline_sha256": sha256(TIMELINE),
                            "sheet_sha256": sha256(sheet),
                            "supervisor_instruction": "CL2X-467",
                            "ordered_shot_ids": [row["shot_id"] for row in timeline["shots"]],
                            "review_focus": [
                                "ordinary human viewing experience across the ordered 24-shot contact sheet",
                                "stable recurring character identities, costumes and female Jiaotu rabbit-ear silhouette motif",
                                "scene geography, locked time of day and motivated practical lighting",
                                "wide-medium-close visual rhythm and story-serving scale",
                                "N01 has natural native-speed motion and preserves the clinic daytime scene",
                                "N03 and N04 action inserts remain readable in ordered context",
                                "no readable or pseudo-readable text on books, papers, tags, seals or props",
                                "N08 contains only wrist tying and N19 uses one blank paper tag",
                                "no duplicated bodies, malformed anatomy, black frames or obvious frozen filler",
                            ],
                        },
                        "required_capabilities": ["image_analysis", "ocr"],
                        "run_regression_ci": True,
                        "use_existing_tools": True,
                    }
                ],
                "workers": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    inventory = OUT / "E27_AGENTCUT_V17_24_SHOT_VISUAL_REVIEW_INVENTORY.json"
    inventory.write_text(
        json.dumps(
            {
                "video": str(VIDEO),
                "video_sha256": sha256(VIDEO),
                "timeline": str(TIMELINE),
                "timeline_sha256": sha256(TIMELINE),
                "sheet": str(sheet),
                "sheet_sha256": sha256(sheet),
                "shot_count": len(frames),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "request": str(request), "sheet": str(sheet), "sheet_sha256": sha256(sheet)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
