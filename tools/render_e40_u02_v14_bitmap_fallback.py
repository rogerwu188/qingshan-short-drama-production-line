#!/usr/bin/env python3
"""Render E40 U02 after AgentCut drawtext capability failure.

The AgentCut project is already strict-media validated. This deterministic
fallback keeps its exact picture/audio timing and replaces drawtext with the
pre-QA'd transparent bitmap subtitle layers.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808"
PICTURE = BASE / "u02_v10_rigid_prop_curtain_tail_v1/E40_U02_V10_RIGID_PROP_CURTAIN_TAIL_CANDIDATE_V1.mp4"
AUDIO_DIR = ROOT / "working_assets/e40_production_20260814/u02_v13_kokoro_pace_repair_audio_candidates_v1"
AUDIO1 = AUDIO_DIR / "E40-DIA-001_zf_001_normalized48k.wav"
AUDIO2 = AUDIO_DIR / "E40-DIA-002_zf_001_normalized48k.wav"
BITMAP_DIR = BASE / "u02_v11_subtitle_bitmap_oracles_v1"
PNG1 = BITMAP_DIR / "E40-DIA-001_SUBTITLE_LAYER_V1.png"
PNG2 = BITMAP_DIR / "E40-DIA-002_SUBTITLE_LAYER_V1.png"
OUT_DIR = BASE / "u02_v14_agentcut_rights_cleared_assembly_v1"
OUTPUT = OUT_DIR / "E40_U02_V14_AGENTCUT_RIGHTS_CLEARED_ASSEMBLY_NOT_FINAL.mp4"
RECEIPT = ROOT / "workflow/tasks/E40_U02_V14_AGENTCUT_BITMAP_FALLBACK_RENDER_20260814.json"
CAPABILITY = ROOT / "qa/e40_production_20260814/u02_v14_agentcut_rights_cleared_assembly_v1/E40_U02_V14_AGENTCUT_DRAWTEXT_CAPABILITY_FAILURE_V1.json"
EXPECTED = {
    PICTURE: "f8df85a129bd7891127b709e5cb2d215e55eb0c7e09d07ccfcc426119dd8795f",
    PNG1: "5b01e746b81f76151b65b08c595ee2010b0691eb058cc00bc83575116920197a",
    PNG2: "4403c37e6e2df897c12ddfad9e712a9b87cad76ef626c31c3356235b1221603d",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> int:
    for path, expected in EXPECTED.items():
        if sha256(path) != expected:
            raise SystemExit(f"FAIL_CLOSED_PIN_MISMATCH:{path}")
    qa = json.loads((ROOT / "qa/e40_production_20260814/u02_v13_kokoro_pace_repair_audio_candidates_v1/E40_U02_V13_KOKORO_PACE_REPAIR_MACHINE_QA_V1.json").read_text(encoding="utf-8"))
    selected = {item["line_id"]: item for item in qa["candidates"] if item["voice"] == qa["selected_voice"]}
    if qa.get("status") != "PASS_SELECTED_RIGHTS_CLEARED_VOICE" or sha256(AUDIO1) != selected["E40-DIA-001"]["normalized_sha256"] or sha256(AUDIO2) != selected["E40-DIA-002"]["normalized_sha256"]:
        raise SystemExit("FAIL_CLOSED_AUDIO_QA_BINDING")

    atomic_json(CAPABILITY, {
        "schema": "qingshan.e40.u02.agentcut_drawtext_capability_failure.v1",
        "status": "CAPABILITY_FAIL_CONTENT_NOT_FAILED_SAFE_BITMAP_FALLBACK_AUTHORIZED",
        "agentcut_validation": "PASS_STRICT_MEDIA_ZERO_ISSUES",
        "render_error": "FFmpeg premaster render failed: No such filter: drawtext",
        "content_failure": False,
        "fallback": "PINNED_PRE_QA_BITMAP_SUBTITLE_OVERLAY_WITH_IDENTICAL_AUDIO_TIMING",
        "provider_post_count": 0,
        "credits": 0,
    })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    filter_graph = (
        "[0:v][3:v]overlay=0:0:enable='between(t,0.08,1.705)'[v1];"
        "[v1][4:v]overlay=0:0:enable='between(t,1.825,3.9)'[vout];"
        "[1:a]adelay=80:all=1[a1];[2:a]adelay=1825:all=1[a2];"
        "[a1][a2]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.89[aout]"
    )
    command = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(PICTURE), "-i", str(AUDIO1), "-i", str(AUDIO2),
        "-loop", "1", "-framerate", "24", "-i", str(PNG1),
        "-loop", "1", "-framerate", "24", "-i", str(PNG2),
        "-filter_complex", filter_graph,
        "-map", "[vout]", "-map", "[aout]", "-t", "4.0",
        "-r", "24", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "15",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(OUTPUT),
    ]
    subprocess.run(command, check=True)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,codec_type,width,height,sample_rate,channels", "-of", "json", str(OUTPUT)],
        capture_output=True, text=True, check=True,
    )
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u02.v14.agentcut_bitmap_fallback_render.v1",
        "status": "PASS_RENDERED_UNIT_QA_PENDING",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "output": str(OUTPUT.relative_to(ROOT)), "output_sha256": sha256(OUTPUT),
        "probe": json.loads(probe.stdout),
        "capability_failure": str(CAPABILITY.relative_to(ROOT)), "capability_failure_sha256": sha256(CAPABILITY),
        "audio_timing": [{"line_id": "E40-DIA-001", "start": 0.08, "duration": 1.625}, {"line_id": "E40-DIA-002", "start": 1.825, "duration": 2.075}],
        "subtitle_bitmaps": [{"line_id": "E40-DIA-001", "sha256": sha256(PNG1)}, {"line_id": "E40-DIA-002", "sha256": sha256(PNG2)}],
        "provider_post_count": 0, "credits": 0,
    })
    print(json.dumps({"status": "PASS_RENDERED_UNIT_QA_PENDING", "output": str(OUTPUT), "sha256": sha256(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
