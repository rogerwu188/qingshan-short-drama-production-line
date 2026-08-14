#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
RUN_DIR = BASE / "working_assets/e08_api_fallback_20260709"
OUT_DIR = BASE / "exports/e08/api_fallback_20260709"
QA_DIR = BASE / "qa/e08_api_fallback_package_20260709"
SEG_DIR = OUT_DIR / "normalized_segments"
FINAL = OUT_DIR / "qingshan_E08_api_fallback_titled_nalu_20260709.mp4"
RAW = OUT_DIR / "qingshan_E08_api_fallback_raw_concat_20260709.mp4"


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def normalize(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    run([
        str(FFMPEG), "-y", "-i", str(src),
        "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,setsar=1",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-af", "aresample=async=1:first_pts=0",
        "-movflags", "+faststart",
        str(dst),
    ])


def make_card(dst: Path, title: str, subtitle: str, duration: int = 4) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
        f"text='{title}':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=430,"
        "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
        f"text='{subtitle}':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=520,"
        "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Light.ttc:"
        "text='NALU MOTION':fontcolor=white@0.72:fontsize=24:x=(w-text_w)/2:y=820"
    )
    run([
        str(FFMPEG), "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=720x1280:r=30:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", vf,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", str(dst),
    ])


def concat(paths: list[Path], out: Path) -> None:
    list_file = out.with_suffix(".txt")
    list_file.write_text("".join(f"file '{p}'\n" for p in paths), encoding="utf-8")
    run([
        str(FFMPEG), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", "-movflags", "+faststart", str(out),
    ])


def extract_contact(video: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame_dir = out.parent / "timeline_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for old in frame_dir.glob("*.jpg"):
        old.unlink()
    times = [2, 7, 14, 25, 40, 58, 76, 94, 112, 130, 148, 164]
    frames = []
    for idx, t in enumerate(times, 1):
        frame = frame_dir / f"frame_{idx:02d}_{t:03d}s.jpg"
        run([str(FFMPEG), "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1", "-q:v", "2", str(frame)])
        frames.append(frame)
    run([
        str(FFMPEG), "-y", "-framerate", "1", "-pattern_type", "glob", "-i", str(frame_dir / "frame_*.jpg"),
        "-vf", "scale=180:-1,tile=4x3:padding=8:margin=8:color=white",
        "-q:v", "2", str(out),
    ])


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    SEG_DIR.mkdir(parents=True, exist_ok=True)

    title = SEG_DIR / "seg_000_title.mp4"
    tail = SEG_DIR / "seg_999_tail.mp4"
    make_card(title, "青山", "第8集：站桩救命")
    make_card(tail, "NALU MOTION", "下一集继续", duration=4)

    segments = [title]
    for i in range(1, 24):
        src = RUN_DIR / f"videos/shot_{i:02d}/result_01.mp4"
        if not src.exists():
            raise SystemExit(f"Missing shot {i:02d}: {src}")
        dst = SEG_DIR / f"seg_{i:03d}_shot_{i:02d}.mp4"
        normalize(src, dst)
        segments.append(dst)
    segments.append(tail)

    concat(segments[1:-1], RAW)
    concat(segments, FINAL)
    extract_contact(FINAL, QA_DIR / "qingshan_E08_api_fallback_timeline_contact_20260709.jpg")
    print(FINAL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
