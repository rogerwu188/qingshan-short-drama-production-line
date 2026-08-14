#!/usr/bin/env python3
"""Build exact-SHA semantic review evidence for the E27 N17 R2 candidate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
RECEIPT = ROOT / "workflow/tasks/E27_WRITER_AGENT_V040_VIDEO_N17_VISUALFIX_R2_RECEIPT_20260720.json"
OUT = ROOT / "qa/e27_writer_agent_v040_video_n17_visualfix_r2_ai_review_20260720"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    task = receipt["tasks"][0]
    if task.get("state") not in {"qa_pass", "qa_failed_terminal"} or not task.get("output_path"):
        raise SystemExit("N17 R2 has not produced a reviewable candidate")
    video = Path(task["output_path"])
    digest = sha256(video)
    if digest != task.get("sha256"):
        raise SystemExit("N17 R2 candidate SHA drift")
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(video),
    ], text=True).strip())
    frames = []
    frame_dir = OUT / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for index, ratio in enumerate((0.15, 0.50, 0.85), 1):
        frame = frame_dir / f"frame_{index}.png"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{duration * ratio:.3f}", "-i", str(video),
            "-frames:v", "1", "-vf", "scale=360:-2", str(frame),
        ], check=True)
        frames.append(frame)
    sheet = OUT / "E27-N17_R2_15_50_85.png"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(frames[0]), "-i", str(frames[1]), "-i", str(frames[2]),
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3[out]",
        "-map", "[out]", str(sheet),
    ], check=True)
    request = OUT / "E27_N17_R2_AI_REVIEW_REQUEST.json"
    request.write_text(json.dumps({
        "items": [{
            "path": str(sheet),
            "scope": "shot",
            "kind": "image",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": "E27-N17::V040-R2",
            "metadata": {
                "episode": "E27",
                "scene_id": "E27-NATIVE-S05-CORRIDOR-NIGHT",
                "candidate_video_path": str(video),
                "candidate_video_sha256": digest,
                "candidate_sheet_sha256": sha256(sheet),
                "frame_sample_ratios": [0.15, 0.50, 0.85],
                "review_focus": [
                    "Exactly two people remain visible throughout: one guard on the left and Chen Ji on the right",
                    "The same single rubbing remains taut between them as Chen Ji braces his shoulder against the guard armor",
                    "No person enters, exits, duplicates, reflects, or appears in the background",
                    "The same archive corridor, night lighting, faces, costume, anatomy and prop ownership remain stable",
                    "No readable or pseudo-readable text, subtitle, watermark or logo",
                ],
            },
            "required_capabilities": ["image_analysis", "ocr"],
            "run_regression_ci": True,
            "use_existing_tools": True,
        }],
        "workers": 1,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inventory = OUT / "E27_N17_R2_INVENTORY.json"
    inventory.write_text(json.dumps({
        "shot_id": "E27-N17",
        "path": str(video),
        "sha256": digest,
        "sheet": str(sheet),
        "sheet_sha256": sha256(sheet),
        "objective_qa": task.get("qa"),
        "credit_attempts": task.get("credit_attempts"),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "request": str(request), "inventory": str(inventory)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
