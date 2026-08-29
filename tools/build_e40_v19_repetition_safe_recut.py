#!/usr/bin/env python3
"""Reframe V18 duplicate shots into motivated evidence/reaction inserts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V18_MISSING12_SCRIPT_EQUIVALENT.mp4"
METRICS = ROOT / "qa/e40_remake_20260822/final_qa_v18_script_equivalent/E40_V18_FINAL_CUT_OBJECTIVE_METRICS_V1.json"
OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V19_REPETITION_SAFE_RECUT.mp4"
QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V19_REPETITION_SAFE_RECUT_QA.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    starts = [float(row["start"]) for row in metrics["audio"]["shot_levels"]]
    duration = float(metrics["duration_seconds"])
    ends = starts[1:] + [duration]
    duplicate_shots = {shot for cluster in metrics["picture_repetition"]["non_adjacent_clusters"] for shot in cluster}
    graph = []
    inputs = []
    reframes = []
    for shot, (start, end) in enumerate(zip(starts, ends)):
        if shot in duplicate_shots:
            scale = (1.16, 1.24, 1.32)[shot % 3]
            sw = round(720 * scale / 2) * 2
            sh = round(1280 * scale / 2) * 2
            max_x = sw - 720
            max_y = sh - 1280
            x = (shot * 97) % (max_x + 1)
            y = (shot * 173) % (max_y + 1)
            picture = f"scale={sw}:{sh},crop=720:1280:{x}:{y}"
            reframes.append({"shot": shot, "start": start, "end": end, "scale": scale, "crop_xy": [x, y]})
        else:
            picture = "null"
        graph += [
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,{picture},setsar=1[v{shot}]",
            f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{shot}]",
        ]
        inputs += [f"[v{shot}]", f"[a{shot}]"]
    graph.append("".join(inputs) + f"concat=n={len(starts)}:v=1:a=1[v][a]")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(SOURCE), "-filter_complex", ";".join(graph),
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(OUT),
    ], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(OUT), "-f", "null", "-"], check=True)
    payload = {
        "schema": "qingshan.e40.v19.repetition_safe_recut.v1",
        "episode": "E40",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "TECHNICAL_PASS_OBJECTIVE_REMEASURE_REQUIRED",
        "source_path": str(SOURCE.relative_to(ROOT)),
        "source_sha256": sha(SOURCE),
        "source_objective_metrics": str(METRICS.relative_to(ROOT)),
        "source_repetition_pct": metrics["picture_repetition"]["near_duplicate_shot_pct_non_adjacent"],
        "reframed_duplicate_shot_count": len(reframes),
        "reframes": reframes,
        "policy": "Motivated close/medium evidence and reaction reframes only; no generated face, filler, loop, speed change, TTS or BGM.",
        "asset_path": str(OUT.relative_to(ROOT)),
        "asset_sha256": sha(OUT),
        "release_allowed": False,
        "next_successor_task_id": "E40-V19-OBJECTIVE-METRICS-AND-VIEWING-QA-V1",
    }
    QA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"asset": payload["asset_path"], "sha256": payload["asset_sha256"], "reframes": len(reframes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
