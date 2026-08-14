#!/usr/bin/env python3
"""Build V20D by splicing the temporally smoothed registered patch into V18C."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import imageio_ffmpeg


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = Path(imageio_ffmpeg.get_ffmpeg_exe())
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
V18C = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v18_zero_credit_dynamic_reframe_probe/E36_ACCEPTED_ONLY_AGENTCUT_V18C_TWO_PART_DYNAMIC_REFRAME_EXACT_V15_AUDIO_PROBE.mp4"
PATCH = ROOT / "qa/e36_agentcut_20260730/v18c_v18e_temporally_smoothed_registration_preview_v4/E36_V18C_V18E_TEMPORALLY_SMOOTHED_REGISTERED_160_168S_PREVIEW_V4.mp4"
PATCH_QA = ROOT / "qa/e36_agentcut_20260730/E36_V18C_V18E_TEMPORALLY_SMOOTHED_BOUNDARY_REGISTRATION_QA_V4.json"
LINE10 = ROOT / "working_assets/e36_autonomous_recovery_20260731/cap_close_changed_wave3_u09_line10/E36_E36-U09-CANONICAL-L10-CHANGED-W3_7a93209a-dab2-45ae-9a58-9990d6f93323.mp4"
OUT_DIR = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v20d_temporally_smoothed_registered_hybrid"
OUT = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V20D_TEMPORALLY_SMOOTHED_REGISTERED_HYBRID.mp4"
TEMP_OUT = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V20D_TEMPORALLY_SMOOTHED_REGISTERED_HYBRID.rendering.mp4"
PROBE = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V20D_probe.json"
RENDER_LOG = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V20D_render.log"
DECODE_LOG = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V20D_decode.log"
MANIFEST = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V20D_TEMPORALLY_SMOOTHED_REGISTERED_HYBRID_MANIFEST_V1.json"
INSERT = 70.928060
PATCH_START, PATCH_END = 160.0, 168.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def run(args: list[str], log: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True)
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    return result


def duration(path: Path) -> float:
    return float(run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)]).stdout.strip())


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if TEMP_OUT.exists():
        TEMP_OUT.unlink()
    patch_qa = json.loads(PATCH_QA.read_text(encoding="utf-8"))
    if patch_qa["gate_results"]["direct_visual"] != "PASS_NO_VISIBLE_DOUBLE_EXPOSURE_IN_18_BOUNDARY_SAMPLES":
        raise RuntimeError("registered patch direct visual gate is not cleared")
    graph = (
        f"[0:v]trim=0:{PATCH_START:.6f},setpts=PTS-STARTPTS[basepre];"
        "[1:v]setpts=PTS-STARTPTS[patch];"
        f"[0:v]trim=start={PATCH_END:.6f},setpts=PTS-STARTPTS[basepost];"
        "[basepre][patch][basepost]concat=n=3:v=1:a=0[hybrid];"
        "[hybrid]split=2[h0][h1];"
        f"[h0]trim=0:{INSERT:.6f},setpts=PTS-STARTPTS[v0];"
        f"[0:a]atrim=0:{INSERT:.6f},asetpts=PTS-STARTPTS,aresample=48000[a0];"
        "[2:v]setpts=PTS-STARTPTS[v1];[2:a]asetpts=PTS-STARTPTS,aresample=48000[a1];"
        f"[h1]trim=start={INSERT:.6f},setpts=PTS-STARTPTS[v2];"
        f"[0:a]atrim=start={INSERT:.6f},asetpts=PTS-STARTPTS,aresample=48000[a2];"
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[outv][outa]"
    )
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "info", "-y", "-i", str(V18C), "-i", str(PATCH), "-i", str(LINE10),
        "-filter_complex", graph, "-map", "[outv]", "-map", "[outa]", "-c:v", "h264_videotoolbox", "-b:v", "8M",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(TEMP_OUT),
    ], RENDER_LOG)
    decode = run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-i", str(TEMP_OUT), "-f", "null", "-"])
    DECODE_LOG.write_text(decode.stdout + decode.stderr, encoding="utf-8")
    if DECODE_LOG.stat().st_size:
        raise RuntimeError("decode emitted errors; refusing atomic promotion")
    TEMP_OUT.replace(OUT)
    probe = run([str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(OUT)])
    PROBE.write_text(probe.stdout, encoding="utf-8")
    manifest = {
        "schema": "qingshan.e36.accepted_only_agentcut.v20d_temporally_smoothed_registered_hybrid.manifest.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": "CL2X-919",
        "source_mailbox_sha256": "398c4b57c386ad46b05a46030b6b2e4a875a59c2449f5bf6192edbba6c472193",
        "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
        "manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
        "base_v18c": {"path": rel(V18C), "sha256": sha256(V18C)},
        "registered_patch": {"path": rel(PATCH), "sha256": sha256(PATCH), "qa_path": rel(PATCH_QA), "qa_sha256": sha256(PATCH_QA)},
        "targeted_replacement": {"base_seconds": [PATCH_START, PATCH_END], "smooth_core_seconds": [162.0, 166.0], "method": "TEMPORALLY_SMOOTHED_PER_FRAME_ECC_STAGGERED_REGISTERED_PATCH_SPLICE"},
        "inserted_line10": {"path": rel(LINE10), "sha256": sha256(LINE10), "at_seconds": INSERT, "duration_seconds": duration(LINE10), "status": "PASS_ADMITTED"},
        "output": {"path": rel(OUT), "sha256": sha256(OUT), "duration_seconds": duration(OUT), "status": "REVERSIBLE_V20D_OBJECTIVE_QA_PENDING"},
        "probe": {"path": rel(PROBE), "sha256": sha256(PROBE)},
        "render_log": {"path": rel(RENDER_LOG), "sha256": sha256(RENDER_LOG)},
        "decode_log": {"path": rel(DECODE_LOG), "sha256": sha256(DECODE_LOG), "errors": 0},
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "promotion": "NOT_GRANTED",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": rel(OUT), "sha256": sha256(OUT), "duration": duration(OUT), "manifest": rel(MANIFEST), "manifest_sha256": sha256(MANIFEST)}))


if __name__ == "__main__":
    main()
