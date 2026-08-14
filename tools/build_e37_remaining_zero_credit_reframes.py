#!/usr/bin/env python3
"""Create fixed-composition zero-credit reframes without synthetic camera sway."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "working_assets/e37_video_20260803/remaining_u03_u07_pfm_v2_overhead_reveal_v4"
QA = ROOT / "qa/e37_video_20260803/remaining_u03_u07_pfm_v2_overhead_reveal_v4"
RECEIPT = ROOT / "workflow/tasks/E37_REMAINING_U03_U07_PFM_V2_OVERHEAD_REVEAL_PENDING9_SUBMIT_V4_20260803.json"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
SPEAKER_LOCK = {"U03-S4", "U07-S1", "U07-S2", "U07-S4"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    rows = []
    for task in receipt["tasks"]:
        segment = task["segment_id"]
        source = ROOT / task["output_path"]
        duration = float(task["output_duration_seconds"])
        output = WORK / f"E37_{segment.replace('-', '_')}_ZERO_CREDIT_FIXED_COMPOSITION_V4.mp4"
        if segment in SPEAKER_LOCK:
            video_filter = (
                "scale=1200:2133:flags=lanczos,"
                "crop=720:1280:x=390:y=560"
            )
            scope = "SPEAKER_LOCKED_FIXED_COMPOSITION_V4"
        else:
            video_filter = (
                "scale=1000:1778:flags=lanczos,"
                "crop=720:1280:x=140:y=249"
            )
            scope = "WIDE_CAUSAL_FIXED_COMPOSITION_V4"
        subprocess.run(
            [
                str(FFMPEG), "-y", "-loglevel", "error", "-i", str(source),
                "-vf", video_filter, "-c:v", "libx264", "-preset", "medium",
                "-crf", "16", "-c:a", "copy", "-movflags", "+faststart", str(output),
            ],
            check=True,
        )
        rows.append({
            "segment_id": segment,
            "scope": scope,
            "source": rel(source),
            "source_sha256": sha256(source),
            "output": rel(output),
            "output_sha256": sha256(output),
            "credits": {"pay": 0, "refund": 0, "net": 0},
            "audio": "STREAM_COPY_FROM_PROVIDER_NATIVE_AUDIO",
            "camera_policy": "FIXED_CROP_NO_TIME_EXPRESSION_NO_OSCILLATION",
        })
        print(json.dumps({"segment": segment, "scope": scope, "output_sha256": rows[-1]["output_sha256"]}, ensure_ascii=False), flush=True)

    report = {
        "schema": "qingshan.e37.remaining_zero_credit_reframes.v4",
        "episode": "E37",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_9_OF_9_ZERO_CREDIT_FIXED_COMPOSITION_V4_BUILT_PENDING_QA",
        "rows": rows,
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    out = QA / "E37_REMAINING_9_ZERO_CREDIT_FIXED_COMPOSITION_BUILD_V4.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": rel(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
