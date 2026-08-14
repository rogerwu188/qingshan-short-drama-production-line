#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from run_regression_ci import default_ffmpeg


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_source(repo: Path, row: dict) -> Path:
    path = (repo / str(row["path"])).resolve()
    if not path.is_file():
        raise SystemExit(f"Missing source: {path}")
    expected = str(row.get("sha256", "")).strip()
    if expected and sha256(path) != expected:
        raise SystemExit(f"Source hash mismatch: {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render an ordered local timeline trial without retime, loop or freeze.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ffmpeg", default=default_ffmpeg())
    args = parser.parse_args()

    if not args.ffmpeg or not Path(args.ffmpeg).is_file():
        raise SystemExit("Missing ffmpeg.")
    repo = Path(__file__).resolve().parents[1]
    plan_path = Path(args.plan).expanduser().resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    videos = sorted(plan.get("video_segments") or [], key=lambda row: int(row["order"]))
    audios = sorted(plan.get("audio_segments") or [], key=lambda row: int(row["order"]))
    runtime = float(plan["target_runtime_sec"])
    fps = float(plan["output_fps"])
    if not videos or not audios:
        raise SystemExit("Plan must contain video_segments and audio_segments.")

    cursor = 0.0
    for row in videos:
        if abs(float(row["timeline_in_sec"]) - cursor) > 0.001:
            raise SystemExit(f"Non-contiguous picture timeline at order {row['order']}.")
        cursor += float(row["duration_sec"])
    if abs(cursor - runtime) > 0.001:
        raise SystemExit(f"Picture runtime {cursor:.3f} does not match target {runtime:.3f}.")

    video_paths = [resolve_source(repo, row) for row in videos]
    audio_paths = [resolve_source(repo, row) for row in audios]
    output = Path(args.out).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [str(Path(args.ffmpeg).resolve()), "-y"]
    for path in video_paths:
        cmd.extend(["-i", str(path)])
    for path in audio_paths:
        cmd.extend(["-i", str(path)])

    filters: list[str] = []
    video_labels: list[str] = []
    for index, row in enumerate(videos):
        start = float(row.get("source_in_sec", 0.0))
        duration = float(row["duration_sec"])
        label = f"v{index}"
        filters.append(
            f"[{index}:v]trim=start={start:.6f}:duration={duration:.6f},"
            f"setpts=PTS-STARTPTS,fps={fps:g},format=yuv420p[{label}]"
        )
        video_labels.append(f"[{label}]")
    filters.append("".join(video_labels) + f"concat=n={len(videos)}:v=1:a=0[vout]")

    audio_labels: list[str] = []
    audio_input_offset = len(videos)
    for index, row in enumerate(audios):
        duration = float(row["duration_sec"])
        delay_ms = round(float(row["timeline_in_sec"]) * 1000)
        label = f"a{index}"
        filters.append(
            f"[{audio_input_offset + index}:a]atrim=start=0:duration={duration:.6f},"
            f"asetpts=PTS-STARTPTS,adelay={delay_ms}|{delay_ms}[{label}]"
        )
        audio_labels.append(f"[{label}]")
    filters.append(
        "".join(audio_labels)
        + f"amix=inputs={len(audios)}:duration=longest:normalize=0,"
        + f"apad=pad_dur={runtime:.6f},atrim=start=0:duration={runtime:.6f}[aout]"
    )

    cmd.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output),
    ])
    subprocess.run(cmd, check=True)
    print(json.dumps({"status": "PASS", "out": str(output), "sha256": sha256(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
