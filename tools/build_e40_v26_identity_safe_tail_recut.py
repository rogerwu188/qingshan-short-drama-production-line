#!/usr/bin/env python3
"""Remove the two identity-inconsistent standalone portraits from V25."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V25_BLACK_FRAME_SAFE_RECUT.mp4"
OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V26_IDENTITY_SAFE_TAIL_RECUT.mp4"
QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V26_IDENTITY_SAFE_TAIL_RECUT_QA.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    graph = (
        "[0:v]trim=start=0:end=62.80,setpts=PTS-STARTPTS[v0];"
        "[0:a]atrim=start=0:end=62.80,asetpts=PTS-STARTPTS[a0];"
        "[0:v]trim=start=65.20,setpts=PTS-STARTPTS[v1];"
        "[0:a]atrim=start=65.20,asetpts=PTS-STARTPTS[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
    )
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(SOURCE), "-filter_complex", graph,
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(OUT),
    ], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(OUT), "-f", "null", "-"], check=True)
    payload = {
        "schema": "qingshan.e40.v26.identity_safe_tail_recut.v1",
        "episode": "E40",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "TECHNICAL_PASS_IDENTITY_AND_FINAL_CI_REQUIRED",
        "source_sha256": sha(SOURCE),
        "removed_interval_seconds": [62.80, 65.20],
        "reason": "Remove standalone Yunfei and Chenji portraits that do not constitute native-registry identity continuity.",
        "asset_path": str(OUT.relative_to(ROOT)),
        "asset_sha256": sha(OUT),
        "release_allowed": False,
        "next_successor_task_id": "E40-V26-IDENTITY-AND-REGISTERED-FINAL-QA-V1"
    }
    QA.parent.mkdir(parents=True, exist_ok=True)
    QA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"asset": payload["asset_path"], "sha256": payload["asset_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
