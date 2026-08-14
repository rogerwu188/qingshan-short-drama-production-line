#!/usr/bin/env python3
"""Build 14 exact-SHA review sheets for E27 visual-fix R1 videos."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
RECEIPT = ROOT / "workflow/tasks/E27_WRITER_AGENT_V040_VIDEO_VISUALFIX_R1_RECEIPT_20260720.json"
COMPILED = Path("/Users/rogerwu/Documents/Codex/2026-07-20/qingshan-professional-writer-agent/outputs/qingshan-writer-agent/examples/e27.agent-native.compiled.json")
OUT = ROOT / "qa/e27_writer_agent_v040_video_visualfix_r1_ai_review_20260720"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe_duration(path: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)
    ], text=True).strip())


def make_sheet(shot_id: str, video: Path) -> Path:
    frames_dir = OUT / "frames" / shot_id
    sheets_dir = OUT / "sheets"
    frames_dir.mkdir(parents=True, exist_ok=True)
    sheets_dir.mkdir(parents=True, exist_ok=True)
    total = probe_duration(video)
    frames = []
    for index, ratio in enumerate((0.15, 0.50, 0.85), 1):
        frame = frames_dir / f"frame_{index}.png"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{total * ratio:.3f}",
            "-i", str(video), "-frames:v", "1", "-vf", "scale=360:-2", str(frame)
        ], check=True)
        frames.append(frame)
    sheet = sheets_dir / f"{shot_id}_R1_15_50_85.png"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(frames[0]), "-i", str(frames[1]), "-i", str(frames[2]),
        "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3[out]", "-map", "[out]", str(sheet)
    ], check=True)
    return sheet


def main() -> int:
    receipt = load(RECEIPT)
    shots = {row["shot_id"]: row for row in load(COMPILED)["shot_contracts"]}
    items = []
    selection = []
    for task in sorted(receipt["tasks"], key=lambda row: shots[row["shot_id"]]["global_order"]):
        shot = shots[task["shot_id"]]
        video = Path(task["output_path"])
        digest = sha256(video)
        if digest != task["sha256"]:
            raise SystemExit(f"candidate SHA drift: {task['shot_id']}")
        sheet = make_sheet(task["shot_id"], video)
        sheet_digest = sha256(sheet)
        selection.append({
            "shot_id": task["shot_id"],
            "path": str(video),
            "sha256": digest,
            "task_id": task.get("task_id"),
            "objective_qa_state": task.get("state"),
            "objective_qa": task.get("qa"),
            "visual_sheet": str(sheet),
            "visual_sheet_sha256": sheet_digest,
        })
        items.append({
            "path": str(sheet),
            "scope": "shot",
            "kind": "image",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": task["shot_id"],
            "metadata": {
                "episode": "E27",
                "scene_id": shot["scene_id"],
                "candidate_video_path": str(video),
                "candidate_video_sha256": digest,
                "candidate_sheet_sha256": sheet_digest,
                "frame_sample_ratios": [0.15, 0.50, 0.85],
                "repair_checks": task.get("repair_checks", []),
                "review_focus": [
                    f"Across all three chronological frames, the event remains exactly: {shot['action']}",
                    f"The visible result remains exactly: {shot['visual']}",
                    f"Scene authority and shot scale stay {shot['scene_id']} / {shot['shot_scale']}",
                    "the targeted repair checks are visibly corrected without changing story facts",
                    "canonical identity, gender, costume, anatomy, cast count and prop ownership stay stable",
                    "Jiaotu remains female with female face and rabbit-ear silhouette motif in spirit form",
                    "no readable or pseudo-readable text, subtitle, watermark, logo, duplicated person or malformed limb",
                ],
            },
            "required_capabilities": ["image_analysis", "ocr"],
            "run_regression_ci": True,
            "use_existing_tools": True,
        })
    if len(items) != 14:
        raise SystemExit(f"expected 14 R1 items, got {len(items)}")
    OUT.mkdir(parents=True, exist_ok=True)
    request = OUT / "E27_VISUALFIX_R1_14_VIDEO_SHEET_AI_REVIEW_REQUEST.json"
    request.write_text(json.dumps({"items": items, "workers": 4}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "E27_VISUALFIX_R1_14_VIDEO_SELECTION.json").write_text(
        json.dumps({"schema": "qingshan.e27.video_visualfix_r1.selection.v1", "episode": "E27", "items": selection}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "count": len(items), "request": str(request), "request_sha256": sha256(request)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
