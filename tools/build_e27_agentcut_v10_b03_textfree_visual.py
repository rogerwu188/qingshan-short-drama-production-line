#!/usr/bin/env python3
"""Advance E27 B03 P2's text-free reaction cut to remove the final book label."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e27_agentcut_project_v9_b03_textfree_visual_20260720.json"
OUT = ROOT / "configs/e27_agentcut_project_v10_b03_textfree_visual_20260720.json"
PRIMARY = ROOT / "working_assets/e27_standard_storyboard_v4_sheetbound_20260719/candidates/E27_E27-B03-P2-STANDARD-STORYBOARD-V1-R1B-FAILED-ONLY-R2B-FAILED-ONLY-OCR-SAFE-R3B_5c0d7085-8b8b-4da6-b865-da8e81c78c53.mp4"
REACTION = ROOT / "working_assets/e27_standard_storyboard_v1_20260719/candidates/E27_E27-B03-P2-STANDARD-STORYBOARD-V1_4b9d525c-dab1-4499-978a-d379250d296d.mp4"
REPAIRED = ROOT / "working_assets/e27_b03_p2_textfree_visual_v2_20260720/E27_B03_P2_TEXTFREE_VISUAL_V2.mp4"


def main() -> None:
    for source in (BASE, PRIMARY, REACTION):
        if not source.exists():
            raise SystemExit(f"missing source: {source}")
    REPAIRED.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(PRIMARY), "-i", str(REACTION),
        "-filter_complex",
        (
            "[0:v]trim=start=0:end=4.5,setpts=PTS-STARTPTS[v0];"
            "[1:v]trim=start=0:end=7.5,setpts=PTS-STARTPTS[v1];"
            "[v0][v1]concat=n=2:v=1:a=0,format=yuv420p[v]"
        ),
        "-map", "[v]", "-an", "-r", "24", "-c:v", "libx264", "-crf", "16",
        "-preset", "medium", "-movflags", "+faststart", str(REPAIRED),
    ], check=True)
    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V10_B03_TEXTFREE_VISUAL_NOT_FINAL",
        "source_project": str(BASE),
        "rollback_from": str(BASE.relative_to(ROOT)),
        "change_scope": "Advance B03 P2 visual coverage switch by one second after V9 evidence found a residual observer-readable book label at 65 seconds; preserve dialogue audio and runtime.",
    })
    project["output"]["path"] = str(
        ROOT / "exports/e27/agentcut_v10_b03_textfree_visual_20260720/E27_AGENTCUT_V10_B03_TEXTFREE_VISUAL_NOT_FINAL.mp4"
    )
    changed = 0
    for clip in project["timeline"]["videoTracks"][0]["clips"]:
        if clip.get("id") != "E27-B03-P2-VIDEO":
            continue
        clip["source"] = str(REPAIRED)
        clip.setdefault("metadata", {})["text_removal_repair"] = {
            "kind": "TEXT_FREE_COVERAGE_REPLACEMENT_V2",
            "primary_seconds": [0.0, 4.5],
            "reaction_seconds": [0.0, 7.5],
            "residual_v9_failure_time_seconds": 65.0,
            "audio_source_preserved": True,
        }
        changed += 1
    if changed != 1:
        raise SystemExit(f"expected one B03 P2 video clip, changed {changed}")
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
