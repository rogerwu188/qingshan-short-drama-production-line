#!/usr/bin/env python3
"""Build E37 AgentCut V9 by adding the accepted V10 line 19 source to V8."""

import hashlib
import json
import subprocess
from pathlib import Path

from build_e37_v7_per_caption_picture_audio_replacements import replace_track_clips, render_window


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PROJECT = ROOT / "configs/e37_agentcut_v8_line22_textfree_native_20260803.json"
OUT_PROJECT = ROOT / "configs/e37_agentcut_v9_line19_exact_scene_native_20260803.json"
ASSET_DIR = ROOT / "working_assets/e37_video_20260803/v9_line19_agentcut_assets_v1"
OUTPUT = ROOT / "exports/e37/agentcut_v9_line19_exact_scene_native_20260803/E37_AGENTCUT_V9_LINE19_EXACT_SCENE_NATIVE_NOT_FINAL.mp4"
SOURCE = "working_assets/e37_video_20260803/v10_i2v_start_frame_repairs_v1/E37-L019-V10-I2V-EXACT-START_83c4d931-3508-4cbc-96bc-0431d76c48cc.mp4"
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
    cadence = ROOT / "qa/e37_agentcut_20260803/v9_line19_exact_scene_native/E37_L019_NORMALIZED_ASSET_CADENCE.json"
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
            subtitle.setdefault("metadata", {})["source"] = "V10_I2V_EXACT_SCENE_NATIVE_SOURCE_WINDOW"
    project["output"]["path"] = str(OUTPUT.resolve())
    project.setdefault("metadata", {})["v9_line19_replacement"] = {
        "source_project": str(SOURCE_PROJECT.resolve()),
        "source_project_sha256": sha256(SOURCE_PROJECT),
        "line": 19,
        "source": SOURCE,
        "source_sha256": sha256(ROOT / SOURCE),
        "admission": "PASS_NATIVE_DIALOGUE_RECALL1_VISIBLE_MOUTH_CANONICAL_YUNYANG_CADENCE_OCR_TEXTFREE_FIXED_CAMERA",
        "held_lines": [6],
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
