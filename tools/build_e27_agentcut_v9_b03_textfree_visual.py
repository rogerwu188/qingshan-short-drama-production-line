#!/usr/bin/env python3
"""Replace E27 B03 P2's readable generated book labels with text-free coverage."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e27_agentcut_project_v8_b04_luma_ramp_20260720.json"
OUT = ROOT / "configs/e27_agentcut_project_v9_b03_textfree_visual_20260720.json"
PRIMARY = ROOT / "working_assets/e27_standard_storyboard_v4_sheetbound_20260719/candidates/E27_E27-B03-P2-STANDARD-STORYBOARD-V1-R1B-FAILED-ONLY-R2B-FAILED-ONLY-OCR-SAFE-R3B_5c0d7085-8b8b-4da6-b865-da8e81c78c53.mp4"
REACTION = ROOT / "working_assets/e27_standard_storyboard_v1_20260719/candidates/E27_E27-B03-P2-STANDARD-STORYBOARD-V1_4b9d525c-dab1-4499-978a-d379250d296d.mp4"
REPAIRED = ROOT / "working_assets/e27_b03_p2_textfree_visual_v1_20260720/E27_B03_P2_TEXTFREE_VISUAL_V1.mp4"


def build_repaired_visual() -> None:
    REPAIRED.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-i", str(PRIMARY), "-i", str(REACTION),
        "-filter_complex",
        (
            "[0:v]trim=start=0:end=5.5,setpts=PTS-STARTPTS[v0];"
            "[1:v]trim=start=0:end=6.5,setpts=PTS-STARTPTS[v1];"
            "[v0][v1]concat=n=2:v=1:a=0,format=yuv420p[v]"
        ),
        "-map", "[v]", "-an", "-r", "24", "-c:v", "libx264", "-crf", "16",
        "-preset", "medium", "-movflags", "+faststart", str(REPAIRED),
    ]
    subprocess.run(command, check=True)


def main() -> None:
    for source in (PRIMARY, REACTION, BASE):
        if not source.exists():
            raise SystemExit(f"missing source: {source}")
    build_repaired_visual()
    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V9_B03_TEXTFREE_VISUAL_NOT_FINAL",
        "source_project": str(BASE),
        "rollback_from": str(BASE.relative_to(ROOT)),
        "change_scope": "Replace only B03 P2 picture tail containing readable generated book labels; preserve original dialogue audio, 12-second duration, order, and all admitted sibling sources.",
    })
    project["output"]["path"] = str(
        ROOT / "exports/e27/agentcut_v9_b03_textfree_visual_20260720/E27_AGENTCUT_V9_B03_TEXTFREE_VISUAL_NOT_FINAL.mp4"
    )
    changed = 0
    for clip in project["timeline"]["videoTracks"][0]["clips"]:
        if clip.get("id") != "E27-B03-P2-VIDEO":
            continue
        clip["source"] = str(REPAIRED)
        clip.setdefault("metadata", {}).update({
            "visual_replacement_only": True,
            "audio_source_preserved": True,
            "text_removal_repair": {
                "kind": "TEXT_FREE_COVERAGE_REPLACEMENT",
                "primary_seconds": [0.0, 5.5],
                "reaction_seconds": [0.0, 6.5],
                "reason": "Remove observer-readable generated book labels without changing dialogue, runtime, scene, or story order.",
            },
        })
        changed += 1
    if changed != 1:
        raise SystemExit(f"expected one B03 P2 video clip, changed {changed}")
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
