#!/usr/bin/env python3
"""Build E37 AgentCut V10 with a no-sway two-composition line 19 source."""

import hashlib
import json
import subprocess
from pathlib import Path

from build_e37_v7_per_caption_picture_audio_replacements import replace_track_clips, render_window


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PROJECT = ROOT / "configs/e37_agentcut_v8_line22_textfree_native_20260803.json"
OUT_PROJECT = ROOT / "configs/e37_agentcut_v10_line19_two_fixed_compositions_20260803.json"
ASSET_DIR = ROOT / "working_assets/e37_video_20260803/v10_line19_agentcut_assets_v1"
OUTPUT = ROOT / "exports/e37/agentcut_v10_line19_two_fixed_compositions_20260803/E37_AGENTCUT_V10_LINE19_TWO_FIXED_COMPOSITIONS_NOT_FINAL.mp4"
SOURCE = "working_assets/e37_video_20260803/v11_line19_two_fixed_compositions/E37-L019-V11-TWO-FIXED-COMPOSITIONS.mp4"
SPEC = {
    "segment": "U07-S2",
    "start": 108.76,
    "end": 114.38,
    "source": SOURCE,
    "trim_start": 0.0,
    "trim_end": 5.62,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    project = json.loads(SOURCE_PROJECT.read_text(encoding="utf-8"))
    replacement = render_window(19, SPEC, ASSET_DIR)
    cadence = ROOT / "qa/e37_agentcut_20260803/v10_line19_two_fixed_compositions/E37_L019_NORMALIZED_ASSET_CADENCE.json"
    cadence.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "python3", "tools/frame_cadence_audit.py", "--video", str(replacement),
        "--out", str(cadence), "--audit-scope", "VIDEO_ONLY_DIAGNOSTIC",
    ], cwd=ROOT, check=True)
    rendered = {19: (SPEC, replacement, cadence)}
    project["timeline"]["videoTracks"][0]["clips"] = replace_track_clips(
        project["timeline"]["videoTracks"][0]["clips"], rendered, "video"
    )
    project["timeline"]["audioTracks"][0]["clips"] = replace_track_clips(
        project["timeline"]["audioTracks"][0]["clips"], rendered, "audio"
    )
    for subtitle in project["timeline"]["subtitleTracks"][0]["clips"]:
        if subtitle.get("metadata", {}).get("line_id") == 19:
            subtitle["start"] = SPEC["start"]
            subtitle["duration"] = round(SPEC["end"] - SPEC["start"], 6)
            subtitle.setdefault("metadata", {})["source"] = "V11_TWO_FIXED_COMPOSITIONS_NATIVE_SOURCE_WINDOW"
    project["output"]["path"] = str(OUTPUT.resolve())
    project.setdefault("metadata", {})["v10_line19_replacement"] = {
        "source_project": str(SOURCE_PROJECT.resolve()),
        "source_project_sha256": sha256(SOURCE_PROJECT),
        "line": 19,
        "source": SOURCE,
        "source_sha256": sha256(ROOT / SOURCE),
        "admission": "PASS_NATIVE_DIALOGUE_IDENTITY_MOUTH_CADENCE_OCR_TWO_FIXED_COMPOSITIONS_NO_SWAY",
        "line6_source": "EXISTING_SHA_LOCKED_U02_S2_V4_FULL_SOURCE_RECALL1_DIRECT_VISIBLE_MOUTH",
        "release_status": "NOT_FINAL_REQUIRES_FULL_QA",
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "project": str(OUT_PROJECT.relative_to(ROOT)),
        "project_sha256": sha256(OUT_PROJECT),
        "asset": str(replacement.relative_to(ROOT)),
        "asset_sha256": sha256(replacement),
        "cadence": str(cadence.relative_to(ROOT)),
        "cadence_sha256": sha256(cadence),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
