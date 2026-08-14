#!/usr/bin/env python3
"""Build a midpoint identity overview for every admitted E34 v2 video unit."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "workflow/tasks/E34_VIDEO_STREAMING_PERFORMANCE_V2_RECEIPT_20260723.json"
SPLIT = ROOT / "workflow/tasks/E34_U17_SPLIT_REPAIR1_VIDEO_RECEIPT_20260723.json"
CONFIG = ROOT / "workflow/claude_writer_agent/production/e34_claude_writer_v2_400ff6d2_20260723/video_performance_v2/E34_VIDEO_STREAMING_PERFORMANCE_V2.json"
ADMISSION = ROOT / "qa/e34_v2_streaming_video_compile_20260723/E34_OCR_ONLY_CONDITIONAL_MACHINE_ADMISSIONS_V2.json"
OUT_DIR = ROOT / "qa/e34_v2_streaming_video_compile_20260723/identity_overview"
OUT = OUT_DIR / "E34_ALL_UNIT_MIDPOINT_IDENTITY_OVERVIEW.png"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
ORDER = [
    "E34-CW-U01", "E34-CW-U02", "E34-CW-U03", "E34-CW-U04", "E34-CW-U05",
    "E34-CW-U06", "E34-CW-U07", "E34-CW-U08", "E34-CW-U09", "E34-CW-U10",
    "E34-CW-U11", "E34-CW-U12", "E34-CW-U13", "E34-CW-U14", "E34-CW-U15",
    "E34-CW-U16", "E34-CW-U17A", "E34-CW-U17B", "E34-CW-U18", "E34-CW-U19",
    "E34-CW-U20", "E34-CW-U21",
]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def duration(path: Path) -> float:
    value = subprocess.check_output([
        str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)
    ], text=True).strip()
    return float(value)


def main() -> int:
    admitted = {row["unit_id"] for row in load(ADMISSION)["selections"]}
    sources: dict[str, Path] = {}
    reused = load(CONFIG)["reused_video_units"][0]
    sources["E34-CW-U01"] = ROOT / reused["output_path"]
    for receipt in (MAIN, SPLIT):
        for row in load(receipt)["tasks"]:
            if row.get("status") == "qa_pass" or row.get("unit_id") in admitted:
                sources[row["unit_id"]] = Path(row["output_path"])
    missing = [unit for unit in ORDER if unit not in sources or not sources[unit].is_file()]
    if missing:
        raise SystemExit(f"missing admitted sources: {missing}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for index, unit in enumerate(ORDER, 1):
        source = sources[unit]
        midpoint = max(0.1, duration(source) / 2)
        frame = OUT_DIR / f"frame_{index:02d}.png"
        subprocess.run([
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{midpoint:.3f}",
            "-i", str(source), "-frames:v", "1",
            "-vf", f"scale=180:-1,drawtext=fontfile=/System/Library/Fonts/STHeiti Medium.ttc:text='{unit.replace('E34-CW-', '')}':x=6:y=6:fontsize=20:fontcolor=white:borderw=2:bordercolor=black",
            str(frame),
        ], check=True)
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-framerate", "1",
        "-i", str(OUT_DIR / "frame_%02d.png"),
        "-vf", f"tile=5x5:nb_frames={len(ORDER)}:padding=4:margin=4:color=black", "-frames:v", "1", str(OUT),
    ], check=True)
    print(json.dumps({"status": "PASS", "unit_count": len(ORDER), "out": str(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
