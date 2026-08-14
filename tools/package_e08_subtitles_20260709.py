#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
OUT_DIR = BASE / "exports/e08/api_fallback_20260709"
QA_DIR = BASE / "qa/e08_api_fallback_package_20260709"

INPUT = OUT_DIR / "qingshan_E08_api_fallback_titled_nalu_20260709.mp4"
ASS = OUT_DIR / "qingshan_E08_api_fallback_dialogue_subtitles_20260709.ass"
OUTPUT = OUT_DIR / "qingshan_E08_api_fallback_titled_subtitled_nalu_20260709.mp4"
CONTACT = QA_DIR / "qingshan_E08_api_fallback_subtitled_contact_20260709.jpg"
ROOT_CAUSE = QA_DIR / "e08_subtitle_inconsistency_root_cause_20260709.md"


SHOT_DURATIONS = [6, 6, 6, 6] + [7] * 19
TITLE_OFFSET = 4.0

SUBTITLES = {
    1: "姚太医：腿别软。你昨夜从密谍司手里活回来\\N不是让你今早死在后院",
    2: "瘦高师兄：新来的，起！\\N姚老头的早课，晚一步就挨竹条",
    3: "魁梧师兄：你脸怎么比死人还白？\\N陈迹：没睡醒",
    4: "姚太医：一炷香，站不住的人，今天没饭",
    5: "姚太医：你叫什么？\\N陈迹：陈迹\\N姚太医：从今天起，你先学站",
    6: "陈迹：站错了会怎样？",
    7: "姚太医：站错了，药再贵也救不回来",
    8: "陈迹：不冷了？",
    9: "姚太医：谁教过你这个桩？\\N陈迹：没人",
    10: "瘦高师兄：第一次站就过了？\\N他昨晚到底干嘛去了？",
    11: "姚太医：再站半炷香。\\N站完，跟我去柜上算账",
    12: "姚太医：昨夜救你，药钱、车钱、门钱，都记账",
    13: "陈迹：我没有钱\\N姚太医：所以你留下干活",
    14: "陈迹：我在这里，原来也欠债？",
    15: "姚太医：你欠的不是钱。你欠的是一条命",
    16: "瘦高师兄：别问了。医馆里，\\N没人敢问姚老头从哪捡人",
    17: "魁梧师兄：问多了，活儿就多",
    18: "陈迹：又有人跟着我",
    19: "暗桩：人还活着",
    20: "暗桩：报给云羊",
    21: "姚太医：看见了？\\N陈迹：看见了",
    22: "陈迹：再站半炷香",
    23: "姚太医：你这身寒，不像病，\\N像有人故意种进去的",
}


def ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h = cs // 360000
    cs %= 360000
    m = cs // 6000
    cs %= 6000
    s = cs // 100
    cs %= 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass() -> None:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 720",
        "PlayResY: 1280",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,PingFang SC,35,&H00FFFFFF,&H000000FF,&HCC000000,&H77000000,0,0,0,0,100,100,0,0,1,2.4,0.5,2,42,42,112,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    cursor = TITLE_OFFSET
    for idx, duration in enumerate(SHOT_DURATIONS, 1):
        text = SUBTITLES.get(idx)
        start = cursor + 0.28
        end = cursor + duration - 0.28
        if text:
            lines.append(
                f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}"
            )
        cursor += duration

    ASS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def burn_subtitles() -> None:
    filter_arg = f"subtitles={ASS}:fontsdir=/System/Library/Fonts"
    run([
        str(FFMPEG), "-y", "-i", str(INPUT),
        "-vf", filter_arg,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(OUTPUT),
    ])


def extract_contact() -> None:
    frame_dir = QA_DIR / "subtitle_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for old in frame_dir.glob("*.jpg"):
        old.unlink()
    times = [5, 10, 17, 27, 41, 55, 69, 84, 98, 112, 126, 146]
    for idx, t in enumerate(times, 1):
        frame = frame_dir / f"sub_frame_{idx:02d}_{t:03d}s.jpg"
        run([
            str(FFMPEG), "-y", "-ss", str(t), "-i", str(OUTPUT),
            "-frames:v", "1", "-q:v", "2", str(frame),
        ])
    run([
        str(FFMPEG), "-y", "-framerate", "1", "-pattern_type", "glob",
        "-i", str(frame_dir / "sub_frame_*.jpg"),
        "-vf", "scale=180:-1,tile=4x3:padding=8:margin=8:color=white",
        "-frames:v", "1", "-q:v", "2", str(CONTACT),
    ])


def main() -> int:
    raise SystemExit(
        "Blocked: source clips contain inconsistent baked model subtitles. "
        f"Read {ROOT_CAUSE} and regenerate contaminated shots before burning a global subtitle layer."
    )
    if not INPUT.exists():
        raise SystemExit(f"Missing input video: {INPUT}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    write_ass()
    burn_subtitles()
    extract_contact()
    print(OUTPUT)
    print(ASS)
    print(CONTACT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
