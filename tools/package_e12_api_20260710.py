#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
RUN_DIR = BASE / "working_assets/e12_api_20260710"
CONFIG = BASE / "configs/e12_continuity_config_20shots_20260710.json"
OUT_DIR = BASE / "exports/e12/final_package_20260710"
QA_DIR = BASE / "qa/e12_final_package_20260710"
SEG_DIR = OUT_DIR / "segments"
SUBTITLE_TEXT_DIR = OUT_DIR / "subtitle_texts_clean_20260710"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"

RAW = OUT_DIR / "qingshan_E12_raw_normalized_20260710.mp4"
TAILED = OUT_DIR / "qingshan_E12_tailed_nalu_20260710.mp4"
FINAL = OUT_DIR / "qingshan_E12_final_subtitled_nalu_20260710.mp4"
SOURCE_MANIFEST = OUT_DIR / "e12_final_source_manifest_20260710.json"
LOUDNESS_REPORT = QA_DIR / "qingshan_E12_final_loudness_20260710.txt"
CONTACT = QA_DIR / "qingshan_E12_final_subtitled_contact_20260710.jpg"
MIDPOINT_CONTACT = QA_DIR / "qingshan_E12_final_all_shots_midpoint_20260710.jpg"

TAIL_DURATION = 3.0


def run(args: list[str], *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str] | None:
    if capture:
        return subprocess.run(args, check=check, text=True, capture_output=True)
    subprocess.run(args, check=check)
    return None


def duration(path: Path) -> float:
    proc = run([str(FFMPEG), "-hide_banner", "-i", str(path)], capture=True, check=False)
    assert proc is not None
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not match:
        raise SystemExit(f"Cannot read duration: {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def normalize(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    run([
        str(FFMPEG), "-y", "-i", str(src),
        "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,setsar=1",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-af", "aresample=async=1:first_pts=0",
        "-movflags", "+faststart", str(dst),
    ])


def concat(paths: list[Path], out: Path) -> None:
    list_file = out.with_suffix(".txt")
    list_file.write_text("".join(f"file '{path}'\n" for path in paths), encoding="utf-8")
    run([str(FFMPEG), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", "-movflags", "+faststart", str(out)])


def make_tail_card(dst: Path) -> None:
    if not LOGO.exists():
        raise SystemExit(f"Missing required logo: {LOGO}")
    filter_complex = (
        "[0:v]"
        "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
        "text='青山':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=430,"
        "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
        "text='第13集继续':fontcolor=white:fontsize=38:x=(w-text_w)/2:y=520,"
        "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Light.ttc:"
        "text='NALU MOTION':fontcolor=white@0.72:fontsize=24:x=(w-text_w)/2:y=820"
        "[card];[2:v]scale=250:-1[logo];[card][logo]overlay=(W-w)/2:600:format=auto[v]"
    )
    run([
        str(FFMPEG), "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=720x1280:r=30:d={TAIL_DURATION}",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-loop", "1", "-t", str(TAIL_DURATION), "-i", str(LOGO),
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "1:a", "-t", str(TAIL_DURATION),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", str(dst),
    ])


def subtitles_from_config() -> dict[int, str]:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    subtitles: dict[int, str] = {}
    for shot in data["shots"]:
        text = (shot.get("dialogue") or "").strip()
        text = re.sub(r"^[^：:]{1,8}[：:]", "", text).strip()
        subtitles[int(shot["id"])] = text
    return subtitles


def write_subtitle_textfiles(subtitles: dict[int, str]) -> None:
    SUBTITLE_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    for old in SUBTITLE_TEXT_DIR.glob("*.txt"):
        old.unlink()
    for idx, text in subtitles.items():
        if not text:
            continue
        for line_no, line in enumerate(text.split("\\N"), 1):
            (SUBTITLE_TEXT_DIR / f"shot_{idx:02d}_line_{line_no:02d}.txt").write_text(line.strip(), encoding="utf-8")


def burn_subtitles(shot_durations: list[float]) -> None:
    subtitles = subtitles_from_config()
    write_subtitle_textfiles(subtitles)
    filters: list[str] = []
    cursor = 0.0
    for idx, shot_duration in enumerate(shot_durations, 1):
        text = subtitles.get(idx, "")
        if not text:
            cursor += shot_duration
            continue
        start = cursor + 0.22
        end = cursor + max(0.72, shot_duration - 0.20)
        lines = text.split("\\N")
        top_y = 1102 - ((len(lines) - 1) * 42)
        for line_no, _line in enumerate(lines, 1):
            textfile = SUBTITLE_TEXT_DIR / f"shot_{idx:02d}_line_{line_no:02d}.txt"
            y = top_y + ((line_no - 1) * 52)
            filters.append(
                "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
                f"textfile={textfile}:fontcolor=white:fontsize=34:"
                "bordercolor=black@0.92:borderw=3:shadowcolor=black@0.65:shadowx=1:shadowy=1:"
                f"x=(w-text_w)/2:y={y}:enable='between(t,{start:.2f},{end:.2f})'"
            )
        cursor += shot_duration
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "warning", "-y", "-i", str(TAILED),
        "-vf", ",".join(filters),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(FINAL),
    ])


def extract_contact(video: Path, out: Path, times: list[float], frame_dir_name: str, tile: str) -> None:
    frame_dir = QA_DIR / frame_dir_name
    frame_dir.mkdir(parents=True, exist_ok=True)
    for old in frame_dir.glob("*.jpg"):
        old.unlink()
    for idx, timestamp in enumerate(times, 1):
        frame = frame_dir / f"frame_{idx:02d}_{int(timestamp):03d}s.jpg"
        run([str(FFMPEG), "-y", "-ss", f"{timestamp:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(frame)])
    run([
        str(FFMPEG), "-y", "-framerate", "1", "-pattern_type", "glob", "-i", str(frame_dir / "frame_*.jpg"),
        "-vf", f"scale=180:-1,tile={tile}:padding=8:margin=8:color=white",
        "-frames:v", "1", "-q:v", "2", str(out),
    ])


def write_loudness_report() -> None:
    proc = run([str(FFMPEG), "-hide_banner", "-i", str(FINAL), "-af", "volumedetect", "-f", "null", "-"], capture=True, check=False)
    assert proc is not None
    LOUDNESS_REPORT.write_text(proc.stderr, encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    SEG_DIR.mkdir(parents=True, exist_ok=True)

    segments: list[Path] = []
    shot_durations: list[float] = []
    manifest = []
    for shot in range(1, 21):
        src = RUN_DIR / f"videos/shot_{shot:02d}/result_01.mp4"
        if not src.exists():
            raise SystemExit(f"Missing E12 source clip: {src}")
        dst = SEG_DIR / f"seg_{shot:03d}_shot_{shot:02d}.mp4"
        normalize(src, dst)
        shot_durations.append(duration(dst))
        segments.append(dst)
        manifest.append({"shot": f"{shot:02d}", "source": "api", "path": str(src), "normalized": str(dst)})

    tail = SEG_DIR / "seg_999_tail.mp4"
    make_tail_card(tail)
    concat(segments, RAW)
    concat([*segments, tail], TAILED)
    burn_subtitles(shot_durations)
    write_loudness_report()

    total = sum(shot_durations) + TAIL_DURATION
    SOURCE_MANIFEST.write_text(json.dumps({
        "episode": "E12",
        "title": "灯下女客",
        "final": str(FINAL),
        "raw": str(RAW),
        "tailed": str(TAILED),
        "rule": "Clean dialogue subtitles only; speaker prefixes stripped. Wuyun does not speak in shot 16 until a permitted remote voice asset exists.",
        "shots": manifest,
        "shot_durations": shot_durations,
        "duration_seconds": total,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    contact_times = [2, 6, 12, 20, 30, 40, 50, 60, 72, 84, 96, 108, 119, 126, 133]
    extract_contact(FINAL, CONTACT, [t for t in contact_times if t < total - 1], "final_subtitle_frames", "4x4")
    cursor = 0.0
    midpoint_times = []
    for shot_duration in shot_durations:
        midpoint_times.append(cursor + shot_duration / 2)
        cursor += shot_duration
    extract_contact(FINAL, MIDPOINT_CONTACT, midpoint_times, "final_shot_midpoint_frames", "5x4")

    print(FINAL)
    print(CONTACT)
    print(MIDPOINT_CONTACT)
    print(LOUDNESS_REPORT)
    print(f"duration_seconds={total:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
