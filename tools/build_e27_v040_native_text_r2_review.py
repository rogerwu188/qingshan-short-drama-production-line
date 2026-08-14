#!/usr/bin/env python3
"""Build exact-SHA semantic review evidence for E27 N08/N19 native-text R2."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
RECEIPT = ROOT / "workflow/tasks/E27_WRITER_AGENT_V040_VIDEO_NATIVE_TEXT_R2_RECEIPT_20260720.json"
OUT = ROOT / "qa/e27_writer_agent_v040_video_native_text_r2_ai_review_20260720"
FOCUS = {
    "E27-N08": [
        "Chen Ji remains the same black-clad man and only tightens his left wrist cuff once",
        "The register fragment remains tucked at the waist and is never removed, handed over or opened",
        "Jiaotu remains a woman with the locked rabbit-ear silhouette motif and Baili remains in the established alley background",
        "No readable or pseudo-readable text, subtitle, watermark or logo appears",
        "Hands, wrists, faces, costumes and body count remain anatomically stable",
    ],
    "E27-N19": [
        "Chen Ji catches the rubbing and places one blank paper tag on the same document apparition chest",
        "The paper tag stays blank with no glyphs, numbers, seals, borders or pseudo-text",
        "The same archive corridor, night-interior lighting, identities, costumes and spectral apparition remain stable",
        "No extra tag, extra person, duplicate body or extra limb appears",
        "No subtitle, watermark or logo appears",
    ],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    if receipt.get("status") != "BATCH_COMPLETE":
        raise SystemExit("R2 batch is not complete")
    items = []
    inventory = []
    frame_root = OUT / "frames"
    frame_root.mkdir(parents=True, exist_ok=True)
    for task in receipt["tasks"]:
        shot_id = task["shot_id"]
        video = Path(task["output_path"])
        digest = sha256(video)
        if task.get("state") != "qa_pass" or digest != task.get("sha256"):
            raise SystemExit(f"{shot_id} is not exact-SHA qa_pass")
        duration = float(
            subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)],
                text=True,
            ).strip()
        )
        frames = []
        shot_frames = frame_root / shot_id
        shot_frames.mkdir(parents=True, exist_ok=True)
        for index, ratio in enumerate((0.15, 0.50, 0.85), 1):
            frame = shot_frames / f"frame_{index}.png"
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{duration * ratio:.3f}", "-i", str(video),
                    "-frames:v", "1", "-vf", "scale=360:-2", str(frame),
                ],
                check=True,
            )
            frames.append(frame)
        sheet = OUT / f"{shot_id}_R2_15_50_85.png"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(frames[0]), "-i", str(frames[1]), "-i", str(frames[2]),
                "-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3[out]", "-map", "[out]", str(sheet),
            ],
            check=True,
        )
        items.append(
            {
                "path": str(sheet),
                "scope": "shot",
                "kind": "image",
                "importance": "critical",
                "pass_score": 4.5,
                "clip_id": f"{shot_id}::V040-NATIVE-TEXT-R2",
                "metadata": {
                    "episode": "E27",
                    "shot_id": shot_id,
                    "candidate_video_path": str(video),
                    "candidate_video_sha256": digest,
                    "candidate_sheet_sha256": sha256(sheet),
                    "frame_sample_ratios": [0.15, 0.50, 0.85],
                    "review_focus": FOCUS[shot_id],
                },
                "required_capabilities": ["image_analysis", "ocr"],
                "run_regression_ci": True,
                "use_existing_tools": True,
            }
        )
        inventory.append(
            {
                "shot_id": shot_id,
                "path": str(video),
                "sha256": digest,
                "sheet": str(sheet),
                "sheet_sha256": sha256(sheet),
                "objective_qa": task.get("qa"),
                "credit_attempts": task.get("credit_attempts"),
            }
        )
    request = OUT / "E27_N08_N19_NATIVE_TEXT_R2_AI_REVIEW_REQUEST.json"
    request.write_text(json.dumps({"items": items, "workers": 2}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inventory_path = OUT / "E27_N08_N19_NATIVE_TEXT_R2_INVENTORY.json"
    inventory_path.write_text(json.dumps({"items": inventory}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "request": str(request), "inventory": str(inventory_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
