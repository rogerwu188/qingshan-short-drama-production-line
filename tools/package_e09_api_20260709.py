#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
RUN_DIR = Path(os.environ.get("E09_RUN_DIR", BASE / "working_assets/e09_api_20260709"))
OUT_DIR = Path(os.environ.get("E09_OUT_DIR", BASE / "exports/e09/api_20260709"))
QA_DIR = Path(os.environ.get("E09_QA_DIR", BASE / "qa/e09_api_package_20260709"))
SEG_DIR = OUT_DIR / "segments"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"

RAW = OUT_DIR / "qingshan_E09_api_raw_concat_20260709.mp4"
TITLED = OUT_DIR / "qingshan_E09_api_titled_nalu_20260709.mp4"
FINAL = OUT_DIR / "qingshan_E09_final_titled_subtitled_nalu_20260709.mp4"
CONTACT = QA_DIR / "qingshan_E09_final_subtitled_contact_20260709.jpg"
MIDPOINT_CONTACT = QA_DIR / "qingshan_E09_final_all_shots_midpoint_20260709.jpg"
SUBTITLE_TEXT_DIR = OUT_DIR / "qingshan_E09_dialogue_controlled_subtitle_texts_20260709"

TITLE_DURATION = 4.0
TAIL_DURATION = 4.0
SUBTITLES = {
    1: "陈迹：手机没了……我真在这里",
    2: "陈迹：先活下去",
    3: "陈迹：你又跟来了？",
    4: "陈迹：喵喵？丧彪？",
    5: "陈迹：想要这个？",
    6: "陈迹：来，自己拿",
    7: "陈迹：这珠子在防你？",
    8: "陈迹：师父那边出事了",
    9: "佘登科：刘家死人了，密谍司干的",
    10: "陈迹：你也没地方去？",
    11: "陈迹：来一个包子",
    12: "陈迹：给你，吃完别再跟着我",
    13: "陈迹：按方抓药，诊脉等师父回来",
    14: "陈迹：又输了？",
    15: "陈迹：别动，我给你止血",
    16: "陈迹：疼也忍着点",
    17: "陈迹：我在这边，好像也没什么人能信",
    18: "陈迹：跟我走吧，聘礼就这颗珠子",
    19: "陈迹：你真听得懂？",
    20: "乌云：哪不正常？",
}


def run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str] | None:
    if capture:
        return subprocess.run(args, check=True, text=True, capture_output=True)
    subprocess.run(args, check=True)
    return None


def source_for(shot: int) -> Path:
    path = RUN_DIR / f"videos/shot_{shot:02d}/result_01.mp4"
    if not path.exists():
        raise SystemExit(f"Missing E09 source clip: {path}")
    return path


def duration(path: Path) -> float:
    proc = subprocess.run([str(FFMPEG), "-hide_banner", "-i", str(path)], text=True, capture_output=True)
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
        "-movflags", "+faststart",
        str(dst),
    ])


def make_card(dst: Path, title: str, subtitle: str, duration_seconds: float) -> None:
    if not LOGO.exists():
        raise SystemExit(f"Missing required Nalu Motion logo asset: {LOGO}")
    filter_complex = (
        "[0:v]"
        "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
        f"text='{title}':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=430,"
        "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
        f"text='{subtitle}':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=520,"
        "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Light.ttc:"
        "text='NALU MOTION':fontcolor=white@0.72:fontsize=24:x=(w-text_w)/2:y=820"
        "[card];"
        "[2:v]scale=250:-1[logo];"
        "[card][logo]overlay=(W-w)/2:600:format=auto[v]"
    )
    run([
        str(FFMPEG), "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=720x1280:r=30:d={duration_seconds}",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-loop", "1", "-t", str(duration_seconds), "-i", str(LOGO),
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "1:a", "-t", str(duration_seconds),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", str(dst),
    ])


def concat(paths: list[Path], out: Path) -> None:
    list_file = out.with_suffix(".txt")
    list_file.write_text("".join(f"file '{path}'\n" for path in paths), encoding="utf-8")
    run([str(FFMPEG), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", "-movflags", "+faststart", str(out)])


def write_subtitle_textfiles() -> None:
    SUBTITLE_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    for old in SUBTITLE_TEXT_DIR.glob("*.txt"):
        old.unlink()
    for idx, text in SUBTITLES.items():
        for line_no, line in enumerate(text.split("\\N"), 1):
            (SUBTITLE_TEXT_DIR / f"shot_{idx:02d}_line_{line_no:02d}.txt").write_text(line, encoding="utf-8")


def burn_subtitles(shot_durations: list[float]) -> None:
    write_subtitle_textfiles()
    filters = []
    cursor = TITLE_DURATION
    for idx, shot_duration in enumerate(shot_durations, 1):
        start = cursor + 0.24
        end = cursor + max(0.7, shot_duration - 0.24)
        lines = SUBTITLES[idx].split("\\N")
        top_y = 1104 - ((len(lines) - 1) * 40)
        for line_no, _line in enumerate(lines, 1):
            textfile = SUBTITLE_TEXT_DIR / f"shot_{idx:02d}_line_{line_no:02d}.txt"
            y = top_y + ((line_no - 1) * 52)
            filters.append(
                "drawtext="
                "fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
                f"textfile={textfile}:"
                "fontcolor=white:fontsize=34:"
                "bordercolor=black@0.92:borderw=3:"
                "shadowcolor=black@0.65:shadowx=1:shadowy=1:"
                "x=(w-text_w)/2:"
                f"y={y}:"
                f"enable='between(t,{start:.2f},{end:.2f})'"
            )
        cursor += shot_duration
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "warning", "-y", "-i", str(TITLED),
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", str(FINAL),
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


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    SEG_DIR.mkdir(parents=True, exist_ok=True)

    title = SEG_DIR / "seg_000_title.mp4"
    tail = SEG_DIR / "seg_999_tail.mp4"
    make_card(title, "青山", "第9集：聘猫入局", TITLE_DURATION)
    make_card(tail, "NALU MOTION", "下一集继续", TAIL_DURATION)

    segments = [title]
    shot_durations = []
    for shot in range(1, 21):
        dst = SEG_DIR / f"seg_{shot:03d}_shot_{shot:02d}.mp4"
        normalize(source_for(shot), dst)
        shot_durations.append(duration(dst))
        segments.append(dst)
    segments.append(tail)

    concat(segments[1:-1], RAW)
    concat(segments, TITLED)
    burn_subtitles(shot_durations)

    total = TITLE_DURATION + sum(shot_durations) + TAIL_DURATION
    contact_times = [2, 5, 10, 18, 27, 36, 45, 54, 63, 72, 81, 90]
    contact_times = [t for t in contact_times if t < total - 1]
    extract_contact(FINAL, CONTACT, contact_times, "final_subtitle_frames", "4x3")

    cursor = TITLE_DURATION
    midpoint_times = []
    for shot_duration in shot_durations:
        midpoint_times.append(cursor + shot_duration / 2)
        cursor += shot_duration
    extract_contact(FINAL, MIDPOINT_CONTACT, midpoint_times, "final_shot_midpoint_frames", "5x4")

    print(FINAL)
    print(CONTACT)
    print(MIDPOINT_CONTACT)
    print(f"duration_seconds={total:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
