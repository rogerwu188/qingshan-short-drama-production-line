#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import os
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
REBUILD_CLEAN = os.environ.get("E08_REBUILD_CLEAN") == "1"
RUN_DIR = BASE / "working_assets/e08_api_fallback_20260709"
REPAIR_DIR = BASE / "working_assets/e08_subtitle_repair_20260709"
OUT_DIR = BASE / "exports/e08/api_fallback_20260709"
QA_DIR = BASE / "qa/e08_api_fallback_package_20260709"
SEG_DIR = OUT_DIR / "clean_subtitled_segments"

RAW_CLEAN = OUT_DIR / "qingshan_E08_api_fallback_raw_clean_nobakedsubs_20260709.mp4"
TITLED_CLEAN = OUT_DIR / "qingshan_E08_api_fallback_titled_clean_nobakedsubs_20260709.mp4"
ASS = OUT_DIR / "qingshan_E08_dialogue_controlled_subtitles_20260709.ass"
FINAL = OUT_DIR / "qingshan_E08_final_titled_subtitled_nalu_20260709.mp4"
CONTACT = QA_DIR / "qingshan_E08_final_subtitled_contact_20260709.jpg"
SUBTITLE_TEXT_DIR = OUT_DIR / "qingshan_E08_dialogue_controlled_subtitle_texts_20260709"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"

REPLACEMENTS = {
    7: REPAIR_DIR / "videos/shot_07/result_01.mp4",
    9: REPAIR_DIR / "videos/shot_09/result_01.mp4",
    10: REPAIR_DIR / "videos/shot_10/result_01.mp4",
    14: REPAIR_DIR / "videos/shot_14_clean_timestretch/result_01.mp4",
    20: REPAIR_DIR / "videos/shot_20/result_01.mp4",
    22: REPAIR_DIR / "videos/shot_22/result_01.mp4",
}

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


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


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
        "Style: Default,STHeiti,35,&H00FFFFFF,&H000000FF,&HCC000000,&H77000000,0,0,0,0,100,100,0,0,1,2.4,0.5,2,42,42,112,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    cursor = TITLE_OFFSET
    for idx, duration in enumerate(SHOT_DURATIONS, 1):
        start = cursor + 0.28
        end = cursor + duration - 0.28
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{SUBTITLES[idx]}")
        cursor += duration
    ASS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_subtitle_textfiles() -> None:
    SUBTITLE_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    for old in SUBTITLE_TEXT_DIR.glob("*.txt"):
        old.unlink()
    for idx, text in SUBTITLES.items():
        for line_no, line in enumerate(text.split("\\N"), 1):
            (SUBTITLE_TEXT_DIR / f"shot_{idx:02d}_line_{line_no:02d}.txt").write_text(
                line,
                encoding="utf-8",
            )


def normalize(src: Path, dst: Path) -> None:
    if not src.exists():
        raise SystemExit(f"Missing source: {src}")
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
        "-f", "lavfi", "-i", f"color=c=black:s=720x1280:r=30:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-loop", "1", "-t", str(duration), "-i", str(LOGO),
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "1:a", "-t", str(duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", str(dst),
    ])


def concat(paths: list[Path], out: Path) -> None:
    list_file = out.with_suffix(".txt")
    list_file.write_text("".join(f"file '{p}'\n" for p in paths), encoding="utf-8")
    run([str(FFMPEG), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", "-movflags", "+faststart", str(out)])


def burn_subtitles() -> None:
    filters = []
    cursor = TITLE_OFFSET
    for idx, duration in enumerate(SHOT_DURATIONS, 1):
        start = cursor + 0.28
        end = cursor + duration - 0.28
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
        cursor += duration
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "warning", "-y", "-i", str(TITLED_CLEAN),
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", str(FINAL),
    ])


def extract_contact() -> None:
    frame_dir = QA_DIR / "final_subtitle_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for old in frame_dir.glob("*.jpg"):
        old.unlink()
    times = [5, 10, 17, 27, 41, 55, 69, 84, 98, 112, 126, 146]
    for idx, t in enumerate(times, 1):
        frame = frame_dir / f"frame_{idx:02d}_{t:03d}s.jpg"
        run([str(FFMPEG), "-y", "-ss", str(t), "-i", str(FINAL), "-frames:v", "1", "-q:v", "2", str(frame)])
    run([
        str(FFMPEG), "-y", "-framerate", "1", "-pattern_type", "glob", "-i", str(frame_dir / "frame_*.jpg"),
        "-vf", "scale=180:-1,tile=4x3:padding=8:margin=8:color=white",
        "-frames:v", "1", "-q:v", "2", str(CONTACT),
    ])


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    SEG_DIR.mkdir(parents=True, exist_ok=True)
    write_ass()
    write_subtitle_textfiles()

    title = SEG_DIR / "seg_000_title.mp4"
    tail = SEG_DIR / "seg_999_tail.mp4"
    if REBUILD_CLEAN or not TITLED_CLEAN.exists() or not RAW_CLEAN.exists():
        make_card(title, "青山", "第8集：站桩救命")
        make_card(tail, "NALU MOTION", "下一集继续", duration=4)

        segments = [title]
        for i in range(1, 24):
            src = REPLACEMENTS.get(i) or RUN_DIR / f"videos/shot_{i:02d}/result_01.mp4"
            dst = SEG_DIR / f"seg_{i:03d}_shot_{i:02d}.mp4"
            normalize(src, dst)
            segments.append(dst)
        segments.append(tail)

        concat(segments[1:-1], RAW_CLEAN)
        concat(segments, TITLED_CLEAN)
    burn_subtitles()
    extract_contact()
    print(FINAL)
    print(ASS)
    print(CONTACT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
