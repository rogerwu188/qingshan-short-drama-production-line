#!/usr/bin/env python3
"""Insert accepted zero-credit U08 motion into reversible V20E AgentCut."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
BASE = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v20e_av_tail_aligned_hybrid/E36_ACCEPTED_ONLY_AGENTCUT_V20E_AV_TAIL_ALIGNED_HYBRID.mp4"
U08 = ROOT / "working_assets/e36_autonomous_recovery_20260731/u08_zero_credit_vfx_bridge_v6/E36_U08_ZERO_CREDIT_PAPER_CHAOS_TERMINAL_BRIDGE_V6.mp4"
SOURCE_MAP = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V11.json"
OUT_DIR = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v21_u08_motion_complete"
OUT = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V21_U08_MOTION_COMPLETE.mp4"
MANIFEST = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V21_U08_MOTION_COMPLETE_MANIFEST.json"
INSERT_SECONDS = 56.395067


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    source_map = json.loads(SOURCE_MAP.read_text(encoding="utf-8"))
    u08 = next(row for row in source_map["sources"] if row["source_id"] == "U08_ZERO_CREDIT_PAPER_CHAOS_TERMINAL_V6")
    if abs(float(u08["accepted_only_timeline_seconds"][0]) - INSERT_SECONDS) > 0.000001:
        raise RuntimeError("Source-map insertion point changed")
    graph = (
        f"[0:v]trim=0:{INSERT_SECONDS},setpts=PTS-STARTPTS[v0];"
        f"[0:a]atrim=0:{INSERT_SECONDS},asetpts=PTS-STARTPTS[a0];"
        "[1:v]trim=0:5,setpts=PTS-STARTPTS[v1];"
        "[1:a]atrim=0:5,asetpts=PTS-STARTPTS[a1];"
        f"[0:v]trim=start={INSERT_SECONDS},setpts=PTS-STARTPTS[v2];"
        f"[0:a]atrim=start={INSERT_SECONDS},asetpts=PTS-STARTPTS[a2];"
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]"
    )
    with tempfile.TemporaryDirectory(prefix="e36_v21_", dir=OUT_DIR) as temp_name:
        temp = Path(temp_name) / "candidate.mp4"
        subprocess.run([
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(BASE), "-i", str(U08), "-filter_complex", graph,
            "-map", "[v]", "-map", "[a]", "-r", "24", "-c:v", "libx264",
            "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(temp),
        ], check=True)
        os.replace(temp, OUT)
    manifest = {
        "schema": "qingshan.e36.accepted_only_agentcut_v21_u08_motion_complete.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": "CL2X-923",
        "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
        "base": str(BASE.relative_to(ROOT)),
        "base_sha256": sha256(BASE),
        "insert": str(U08.relative_to(ROOT)),
        "insert_sha256": sha256(U08),
        "insert_at_seconds": INSERT_SECONDS,
        "source_map": str(SOURCE_MAP.relative_to(ROOT)),
        "source_map_sha256": sha256(SOURCE_MAP),
        "candidate": str(OUT.relative_to(ROOT)),
        "candidate_sha256": sha256(OUT),
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "status": "REVERSIBLE_NOT_PROMOTED_REQUIRES_FULL_QA"
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate": str(OUT.relative_to(ROOT)), "sha256": sha256(OUT), "manifest": str(MANIFEST.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
