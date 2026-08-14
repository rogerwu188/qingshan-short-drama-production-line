#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from package_e08_subtitles_20260709 import SHOT_DURATIONS, SUBTITLES, ass_time


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
RUN_DIR = BASE / "working_assets/e08_api_fallback_20260709"
OFFICIAL_REPAIR_DIR = BASE / "working_assets/e08_subtitle_repair_20260709"
OUT_DIR = BASE / "exports/e08/api_fallback_subtitle_clean_20260709"
QA_DIR = BASE / "qa/e08_api_fallback_package_20260709"
SEG_DIR = OUT_DIR / "normalized_segments"

RAW = OUT_DIR / "qingshan_E08_api_fallback_subtitle_clean_raw_concat_20260709.mp4"
TITLED = OUT_DIR / "qingshan_E08_api_fallback_subtitle_clean_titled_nalu_20260709.mp4"
ASS = OUT_DIR / "qingshan_E08_api_fallback_subtitle_clean_dialogue_20260709.ass"
SUBTITLED = OUT_DIR / "qingshan_E08_api_fallback_subtitle_clean_titled_subtitled_nalu_20260709.mp4"
SOURCE_MANIFEST = QA_DIR / "e08_subtitle_clean_source_replacement_manifest_20260709.json"
TIMELINE_CONTACT = QA_DIR / "qingshan_E08_api_fallback_subtitle_clean_timeline_contact_20260709.jpg"
SUBTITLE_CONTACT = QA_DIR / "qingshan_E08_api_fallback_subtitle_clean_subtitled_contact_20260709.jpg"

TITLE_OFFSET = 4.0

REPLACEMENTS = {
    7: RUN_DIR / "videos/shot_07_subtitle_repair_20260709/result_01.mp4",
    9: RUN_DIR / "videos/shot_09_subtitle_repair_20260709/result_01.mp4",
    10: RUN_DIR / "videos/shot_10_subtitle_repair_20260709/result_01.mp4",
    14: RUN_DIR / "videos/shot_14_subtitle_repair_retry02_20260709/result_01.mp4",
    20: RUN_DIR / "videos/shot_20_subtitle_repair_retry02_20260709/result_01.mp4",
    22: RUN_DIR / "videos/shot_22_subtitle_repair_20260709/result_01.mp4",
}


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def mirror_retry02_into_official_dir() -> None:
    copies = {
        "shot_14_retry02": RUN_DIR / "videos/shot_14_subtitle_repair_retry02_20260709",
        "shot_20_retry02": RUN_DIR / "videos/shot_20_subtitle_repair_retry02_20260709",
    }
    for name, src_dir in copies.items():
        dst_dir = OFFICIAL_REPAIR_DIR / "videos" / name
        dst_dir.mkdir(parents=True, exist_ok=True)
        for filename in ("result_01.mp4", "submit_response.json", "last_query_response.json"):
            src = src_dir / filename
            if src.exists():
                shutil.copy2(src, dst_dir / filename)


def source_for_shot(shot: int) -> Path:
    return REPLACEMENTS.get(shot, RUN_DIR / f"videos/shot_{shot:02d}/result_01.mp4")


def normalize(src: Path, dst: Path) -> None:
    if not src.exists():
        raise SystemExit(f"Missing source clip: {src}")
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
        text = SUBTITLES.get(idx)
        start = cursor + 0.28
        end = cursor + duration - 0.28
        if text:
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}")
        cursor += duration

    ASS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def burn_subtitles() -> None:
    if SUBTITLED.exists():
        SUBTITLED.unlink()
    text_dir = OUT_DIR / "subtitle_textfiles"
    text_dir.mkdir(parents=True, exist_ok=True)
    for old in text_dir.glob("shot_*.txt"):
        old.unlink()

    filters = []
    cursor = TITLE_OFFSET
    font = "/System/Library/Fonts/STHeiti\\ Medium.ttc"
    for idx, duration in enumerate(SHOT_DURATIONS, 1):
        text = SUBTITLES.get(idx)
        start = cursor + 0.28
        end = cursor + duration - 0.28
        if text:
            textfile = text_dir / f"shot_{idx:02d}.txt"
            textfile.write_text(text.replace("\\N", "\n"), encoding="utf-8")
            filters.append(
                "drawtext="
                f"fontfile={font}:"
                f"textfile={textfile}:"
                "fontcolor=white:fontsize=35:"
                "borderw=3:bordercolor=black@0.82:"
                "line_spacing=8:"
                "x=(w-text_w)/2:y=h-176:"
                f"enable='between(t,{start:.2f},{end:.2f})'"
            )
        cursor += duration
    filter_arg = ",".join(filters)
    run([
        str(FFMPEG), "-y", "-i", str(TITLED),
        "-vf", filter_arg,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(SUBTITLED),
    ])


def extract_contact(video: Path, out: Path, times: list[int], frame_subdir: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    frame_dir = QA_DIR / frame_subdir
    frame_dir.mkdir(parents=True, exist_ok=True)
    for old in frame_dir.glob("*.jpg"):
        old.unlink()
    for idx, t in enumerate(times, 1):
        frame = frame_dir / f"frame_{idx:02d}_{t:03d}s.jpg"
        run([str(FFMPEG), "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1", "-q:v", "2", str(frame)])
    run([
        str(FFMPEG), "-y", "-framerate", "1", "-pattern_type", "glob",
        "-i", str(frame_dir / "frame_*.jpg"),
        "-vf", "scale=180:-1,tile=4x3:padding=8:margin=8:color=white",
        "-frames:v", "1", "-q:v", "2", str(out),
    ])


def write_source_manifest() -> None:
    rows = []
    for shot in range(1, 24):
        src = source_for_shot(shot)
        rows.append({
            "shot": shot,
            "source": str(src),
            "replacement": shot in REPLACEMENTS,
            "reason": "subtitle_pollution_repair" if shot in REPLACEMENTS else "existing_clean_source",
        })
    SOURCE_MANIFEST.write_text(json.dumps({
        "status": "SUBTITLE_CLEAN_SOURCE_SET_BUILT",
        "raw": str(RAW),
        "titled": str(TITLED),
        "subtitled": str(SUBTITLED),
        "replacements": sorted(REPLACEMENTS),
        "shots": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    SEG_DIR.mkdir(parents=True, exist_ok=True)
    mirror_retry02_into_official_dir()

    if not RAW.exists() or not TITLED.exists():
        title = SEG_DIR / "seg_000_title.mp4"
        tail = SEG_DIR / "seg_999_tail.mp4"
        make_card(title, "青山", "第8集：站桩救命")
        make_card(tail, "NALU MOTION", "下一集继续", duration=4)

        segments = [title]
        for shot in range(1, 24):
            dst = SEG_DIR / f"seg_{shot:03d}_shot_{shot:02d}.mp4"
            normalize(source_for_shot(shot), dst)
            segments.append(dst)
        segments.append(tail)

        concat(segments[1:-1], RAW)
        concat(segments, TITLED)
    write_ass()
    burn_subtitles()
    extract_contact(TITLED, TIMELINE_CONTACT, [2, 7, 14, 25, 40, 58, 76, 94, 112, 130, 148, 164], "subtitle_clean_timeline_frames")
    extract_contact(SUBTITLED, SUBTITLE_CONTACT, [5, 10, 17, 27, 41, 55, 69, 84, 98, 112, 126, 146], "subtitle_clean_subtitle_frames")
    write_source_manifest()
    print(SUBTITLED)
    print(SOURCE_MANIFEST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
