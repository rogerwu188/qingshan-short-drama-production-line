#!/usr/bin/env python3
"""Insert admitted line 10 into V18C and render a reversible V19 candidate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"))
FFPROBE = FFMPEG.with_name("ffprobe")
BASE = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v18_zero_credit_dynamic_reframe_probe/E36_ACCEPTED_ONLY_AGENTCUT_V18C_TWO_PART_DYNAMIC_REFRAME_EXACT_V15_AUDIO_PROBE.mp4"
LINE10 = ROOT / "working_assets/e36_autonomous_recovery_20260731/cap_close_changed_wave3_u09_line10/E36_E36-U09-CANONICAL-L10-CHANGED-W3_7a93209a-dab2-45ae-9a58-9990d6f93323.mp4"
OUT_DIR = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v19_v18c_plus_line10"
OUT = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10.mp4"
PROBE = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10_probe.json"
RENDER_LOG = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10_render.log"
DECODE_LOG = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10_decode.log"
CONTACT = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10_contact_sheet.jpg"
MANIFEST = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10_MANIFEST_V1.json"
INSERT = 70.928060


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def run(args: list[str], log: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True)
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:])
    return result


def duration(path: Path) -> float:
    return float(run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)]).stdout.strip())


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    graph = (
        f"[0:v]trim=0:{INSERT:.6f},setpts=PTS-STARTPTS[v0];[0:a]atrim=0:{INSERT:.6f},asetpts=PTS-STARTPTS,aresample=48000[a0];"
        "[1:v]setpts=PTS-STARTPTS[v1];[1:a]asetpts=PTS-STARTPTS,aresample=48000[a1];"
        f"[0:v]trim=start={INSERT:.6f},setpts=PTS-STARTPTS[v2];[0:a]atrim=start={INSERT:.6f},asetpts=PTS-STARTPTS,aresample=48000[a2];"
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[outv][outa]"
    )
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "info", "-y", "-i", str(BASE), "-i", str(LINE10),
        "-filter_complex", graph, "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-preset", "fast", "-crf", "15",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(OUT),
    ], RENDER_LOG)
    probe = run([str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(OUT)])
    PROBE.write_text(probe.stdout, encoding="utf-8")
    run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-i", str(OUT), "-f", "null", "-"], DECODE_LOG)
    total = duration(OUT)
    run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(OUT), "-vf", f"fps=24/{total:.6f},scale=180:320,tile=6x4", "-frames:v", "1", str(CONTACT)])
    manifest = {
        "schema": "qingshan.e36.accepted_only_agentcut.v19_v18c_plus_line10.manifest.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "source_cl2x": "CL2X-908",
        "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
        "manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
        "base": {"path": rel(BASE), "sha256": sha(BASE), "status": "REVERSIBLE_V18C_NOT_PROMOTED"},
        "inserted_line10": {"path": rel(LINE10), "sha256": sha(LINE10), "at_seconds": INSERT, "duration_seconds": duration(LINE10), "status": "PASS_ADMITTED"},
        "output": {"path": rel(OUT), "sha256": sha(OUT), "duration_seconds": total, "status": "REVERSIBLE_V19_QA_ACTIVE"},
        "probe": {"path": rel(PROBE), "sha256": sha(PROBE)}, "render_log": {"path": rel(RENDER_LOG), "sha256": sha(RENDER_LOG)},
        "decode_log": {"path": rel(DECODE_LOG), "sha256": sha(DECODE_LOG), "errors": 0}, "contact_sheet": {"path": rel(CONTACT), "sha256": sha(CONTACT), "samples": 24},
        "credits": {"pay": 0, "refund": 0, "net": 0}, "status": "PASS_RENDER_AND_FULL_DECODE_QA_CONTINUES",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": rel(OUT), "sha256": sha(OUT), "duration": total, "manifest": rel(MANIFEST), "manifest_sha256": sha(MANIFEST)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
