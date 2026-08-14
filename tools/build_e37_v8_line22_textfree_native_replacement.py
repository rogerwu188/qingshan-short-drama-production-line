#!/usr/bin/env python3
"""Build E37 V8 by adding the text-free, canonical Yunyang line 22 source."""

import hashlib
import json
import subprocess
from pathlib import Path

from build_e37_v7_per_caption_picture_audio_replacements import (
    replace_track_clips,
    render_window,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PROJECT = ROOT / "configs/e37_agentcut_v7_per_caption_visible_speaker_20260803.json"
OUT_PROJECT = ROOT / "configs/e37_agentcut_v8_line22_textfree_native_20260803.json"
ASSET_DIR = ROOT / "working_assets/e37_video_20260803/v8_per_caption_agentcut_assets_v1"
OUTPUT = ROOT / "exports/e37/agentcut_v8_line22_textfree_native_20260803/E37_AGENTCUT_V8_LINE22_TEXTFREE_NATIVE_NOT_FINAL.mp4"
SOURCE = "working_assets/e37_video_20260803/v8_dialogue_identity_repairs_v1/zero_credit_salvage/E37-L022-V8-CROP-A-360x640-TOP.mp4"

SPEC = {
    "segment": "U07-S4",
    "start": 121.60,
    "end": 126.01,
    "source": SOURCE,
    "trim_start": 1.30,
    "trim_end": 5.78,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    project = json.loads(SOURCE_PROJECT.read_text(encoding="utf-8"))
    replacement = render_window(22, SPEC, ASSET_DIR)
    cadence = ROOT / "qa/e37_agentcut_20260803/v8_line22_textfree_native/E37_L022_NORMALIZED_ASSET_CADENCE.json"
    cadence.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "python3", "tools/frame_cadence_audit.py", "--video", str(replacement),
        "--out", str(cadence), "--audit-scope", "VIDEO_ONLY_DIAGNOSTIC",
    ], cwd=ROOT, check=True)
    rendered = {22: (SPEC, replacement, cadence)}
    project["timeline"]["videoTracks"][0]["clips"] = replace_track_clips(
        project["timeline"]["videoTracks"][0]["clips"], rendered, "video"
    )
    project["timeline"]["audioTracks"][0]["clips"] = replace_track_clips(
        project["timeline"]["audioTracks"][0]["clips"], rendered, "audio"
    )
    for subtitle in project["timeline"]["subtitleTracks"][0]["clips"]:
        if subtitle.get("metadata", {}).get("line_id") == 22:
            subtitle["start"] = SPEC["start"]
            subtitle["duration"] = round(SPEC["end"] - SPEC["start"], 6)
            subtitle.setdefault("metadata", {})["source"] = "V8_TEXTFREE_NATIVE_YUNYANG_SOURCE_WINDOW"
    project["output"]["path"] = str(OUTPUT.resolve())
    project.setdefault("metadata", {})["v8_line22_replacement"] = {
        "source_project": str(SOURCE_PROJECT.resolve()),
        "source_project_sha256": sha256(SOURCE_PROJECT),
        "line": 22,
        "source": SOURCE,
        "source_sha256": sha256(ROOT / SOURCE),
        "admission": "PASS_NATIVE_DIALOGUE_RECALL1_VISIBLE_MOUTH_CANONICAL_YUNYANG_CADENCE_OCR_TEXTFREE_ZERO_CREDIT_CROP",
        "held_lines": [6, 19],
        "release_status": "NOT_FINAL_REQUIRES_FULL_QA",
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "project": str(OUT_PROJECT.relative_to(ROOT)),
        "project_sha256": sha256(OUT_PROJECT),
        "asset": str(replacement.relative_to(ROOT)),
        "asset_sha256": sha256(replacement),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
