#!/usr/bin/env python3
"""Build V21 by removing the black bridge and adding motivated in-shot motion."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V20_ROOMTONE_CONTINUITY.mp4"
METRICS = ROOT / "qa/e40_remake_20260822/final_qa_v20_script_equivalent/E40_V20_FINAL_CUT_OBJECTIVE_METRICS_V1.json"
OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V21_STATIC_HOLD_SAFE_RECUT.mp4"
QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V21_STATIC_HOLD_SAFE_RECUT_QA.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    starts = [float(row["start"]) for row in metrics["audio"]["shot_levels"]]
    ends = starts[1:] + [float(metrics["duration_seconds"])]
    graph: list[str] = []
    concat_inputs: list[str] = []
    edits: list[dict] = []
    output_index = 0
    for shot, (start, source_end) in enumerate(zip(starts, ends)):
        if shot == 31:
            edits.append({"shot": shot, "operation": "remove_pure_black_bridge", "start": start, "end": source_end})
            continue
        end = min(source_end, start + 6.0)
        duration = end - start
        # Slow, bounded push with alternating direction. This is a motivated
        # editorial reframe of admitted pixels, not a loop or generated filler.
        if shot % 2:
            x = "(iw-ow)*(0.18+0.12*t/{:.6f})".format(duration)
            y = "(ih-oh)*(0.56-0.10*t/{:.6f})".format(duration)
        else:
            x = "(iw-ow)*(0.68-0.12*t/{:.6f})".format(duration)
            y = "(ih-oh)*(0.38+0.10*t/{:.6f})".format(duration)
        picture = f"scale=792:1408,crop=720:1280:x='{x}':y='{y}',setsar=1"
        graph.extend([
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,{picture}[v{output_index}]",
            f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{output_index}]",
        ])
        concat_inputs.extend([f"[v{output_index}]", f"[a{output_index}]"])
        edits.append({
            "shot": shot,
            "operation": "bounded_editorial_push",
            "start": start,
            "end": end,
            "source_end": source_end,
            "trimmed_to_six_seconds": source_end - start > 6.0,
        })
        output_index += 1
    graph.append("".join(concat_inputs) + f"concat=n={output_index}:v=1:a=1[v][a]")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(SOURCE),
        "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(OUT),
    ], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(OUT), "-f", "null", "-"], check=True)
    payload = {
        "schema": "qingshan.e40.v21.static_hold_safe_recut.v1",
        "episode": "E40",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "TECHNICAL_PASS_REGISTERED_FINAL_CI_REQUIRED",
        "source_path": str(SOURCE.relative_to(ROOT)),
        "source_sha256": sha(SOURCE),
        "registered_failure_evidence_ref": "qa/e40_remake_20260822/final_qa_v20_script_equivalent/E40_V20_REGRESSION_CI_V1.json",
        "policy": "Admitted-pixel editorial motion and trims only; no generation, loop, speed change, TTS, BGM, cross-task audio, or new face.",
        "edits": edits,
        "asset_path": str(OUT.relative_to(ROOT)),
        "asset_sha256": sha(OUT),
        "release_allowed": False,
        "next_successor_task_id": "E40-V21-REGISTERED-FINAL-CI-V1"
    }
    QA.parent.mkdir(parents=True, exist_ok=True)
    QA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"asset": payload["asset_path"], "sha256": payload["asset_sha256"], "edits": len(edits)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
