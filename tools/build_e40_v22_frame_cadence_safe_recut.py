#!/usr/bin/env python3
"""Build V22 with edge trims and stronger admitted-pixel camera motion."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V20_ROOMTONE_CONTINUITY.mp4"
METRICS = ROOT / "qa/e40_remake_20260822/final_qa_v20_script_equivalent/E40_V20_FINAL_CUT_OBJECTIVE_METRICS_V1.json"
OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V22_FRAME_CADENCE_SAFE_RECUT.mp4"
QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V22_FRAME_CADENCE_SAFE_RECUT_QA.json"
BUILD_VERSION = "V22"
EDGE_TRIM_SECONDS = 0.125
MAX_SHOT_SECONDS = 4.5
FAILURE_REF = "qa/e40_remake_20260822/final_qa_v21_script_equivalent/E40_V21_REGRESSION_CI_V1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    starts = [float(row["start"]) for row in metrics["audio"]["shot_levels"]]
    ends = starts[1:] + [float(metrics["duration_seconds"])]
    graph, links, edits = [], [], []
    index = 0
    for shot, (raw_start, raw_end) in enumerate(zip(starts, ends)):
        if shot == 31:
            edits.append({"shot": shot, "operation": "remove_black_bridge"})
            continue
        # Remove embedded fade-to-black edge frames and keep evidence beats
        # compact enough that a static insert cannot become an unmotivated hold.
        start = raw_start + (EDGE_TRIM_SECONDS if raw_end - raw_start > 0.5 else 0.0)
        end = min(raw_end - (EDGE_TRIM_SECONDS if raw_end - raw_start > 0.5 else 0.0), start + MAX_SHOT_SECONDS)
        duration = end - start
        if shot % 2:
            x, y = f"(iw-ow)*(0.05+0.90*t/{duration:.6f})", f"(ih-oh)*(0.80-0.60*t/{duration:.6f})"
        else:
            x, y = f"(iw-ow)*(0.95-0.90*t/{duration:.6f})", f"(ih-oh)*(0.20+0.60*t/{duration:.6f})"
        graph.extend([
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,scale=864:1536,crop=720:1280:x='{x}':y='{y}',setsar=1[v{index}]",
            f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]",
        ])
        links.extend([f"[v{index}]", f"[a{index}]"])
        edits.append({"shot": shot, "operation": "edge_trim_and_bounded_editorial_move", "start": start, "end": end})
        index += 1
    graph.append("".join(links) + f"concat=n={index}:v=1:a=1[v][a]")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(SOURCE), "-filter_complex", ";".join(graph),
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(OUT),
    ], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(OUT), "-f", "null", "-"], check=True)
    payload = {
        "schema": f"qingshan.e40.{BUILD_VERSION.lower()}.frame_cadence_safe_recut.v1",
        "episode": "E40",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "TECHNICAL_PASS_REGISTERED_FINAL_CI_REQUIRED",
        "source_path": str(SOURCE.relative_to(ROOT)),
        "source_sha256": digest(SOURCE),
        "registered_failure_evidence_ref": FAILURE_REF,
        "policy": "Admitted-pixel editorial crop motion and edge trims only; no new generation, loop, speed change, TTS, BGM, cross-task audio, or new face.",
        "edits": edits,
        "asset_path": str(OUT.relative_to(ROOT)),
        "asset_sha256": digest(OUT),
        "release_allowed": False,
        "next_successor_task_id": f"E40-{BUILD_VERSION}-REGISTERED-FINAL-CI-V1"
    }
    QA.parent.mkdir(parents=True, exist_ok=True)
    QA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"asset": payload["asset_path"], "sha256": payload["asset_sha256"], "edits": len(edits)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
