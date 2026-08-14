#!/usr/bin/env python3
"""Pad E27 B03 P2 by 0.25s to remove the V12 five-frame black tail."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e27_agentcut_project_v12_b03_textfree_motion_interpolated_20260720.json"
OUT = ROOT / "configs/e27_agentcut_project_v13_b03_black_tail_fix_20260720.json"
SOURCE = ROOT / "working_assets/e27_b03_p2_textfree_visual_v4_20260720/E27_B03_P2_TEXTFREE_VISUAL_V4.mp4"
REPAIRED = ROOT / "working_assets/e27_b03_p2_textfree_visual_v5_20260720/E27_B03_P2_TEXTFREE_VISUAL_V5.mp4"


def main() -> None:
    for source in (BASE, SOURCE):
        if not source.exists():
            raise SystemExit(f"missing source: {source}")
    REPAIRED.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(SOURCE),
        "-vf", "tpad=stop_mode=clone:stop_duration=0.25,trim=duration=12,setpts=PTS-STARTPTS",
        "-an", "-r", "24", "-c:v", "libx264", "-crf", "16", "-preset", "medium",
        "-movflags", "+faststart", str(REPAIRED),
    ], check=True)

    project = json.loads(BASE.read_text(encoding="utf-8"))
    project["metadata"].update({
        "status": "AGENTCUT_V13_B03_BLACK_TAIL_FIX_NOT_FINAL",
        "source_project": str(BASE),
        "rollback_from": str(BASE.relative_to(ROOT)),
        "change_scope": (
            "Pad B03 P2's final text-free reaction frame by 0.25 seconds to replace "
            "V12's 71.792-72.000 pure-black tail; preserve audio, runtime and all other clips."
        ),
    })
    project["output"]["path"] = str(
        ROOT / "exports/e27/agentcut_v13_b03_black_tail_fix_20260720/E27_AGENTCUT_V13_B03_BLACK_TAIL_FIX_NOT_FINAL.mp4"
    )
    changed = 0
    for clip in project["timeline"]["videoTracks"][0]["clips"]:
        if clip.get("id") != "E27-B03-P2-VIDEO":
            continue
        clip["source"] = str(REPAIRED)
        repair = clip.setdefault("metadata", {}).setdefault("text_removal_repair", {})
        repair.update({
            "kind": "VERIFIED_TEXT_FREE_INTERVAL_REPLACEMENT_V5_BLACK_TAIL_FIXED",
            "tail_padding_seconds": 0.25,
            "v12_failure": "unintended_pure_black_frames:5 at 71.792-72.000",
            "audio_source_preserved": True,
        })
        changed += 1
    if changed != 1:
        raise SystemExit(f"expected one B03 P2 video clip, changed {changed}")
    OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
