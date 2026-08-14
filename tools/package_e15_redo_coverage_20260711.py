#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
CONFIG = BASE / "configs/e15_continuity_config_20shots_20260711.json"
OUT_DIR = BASE / "exports/e15/final_package_redo_coverage_20260711"
QA_DIR = BASE / "qa/e15_final_package_redo_coverage_20260711"
SEG_DIR = OUT_DIR / "segments"
SUBTITLE_TEXT_DIR = OUT_DIR / "subtitle_texts_clean_coverage_20260711"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"
FINAL = OUT_DIR / "qingshan_E15_redo_coverage_final_subtitled_nalu_20260711.mp4"
TAILED = OUT_DIR / "qingshan_E15_redo_coverage_tailed_nalu_20260711.mp4"
RAW = OUT_DIR / "qingshan_E15_redo_coverage_raw_20260711.mp4"
SOURCE_MANIFEST = OUT_DIR / "e15_redo_coverage_source_manifest_20260711.json"
CONTACT = QA_DIR / "qingshan_E15_redo_coverage_contact_20260711.jpg"
MIDPOINT_CONTACT = QA_DIR / "qingshan_E15_redo_coverage_midpoints_20260711.jpg"
LOUDNESS_REPORT = QA_DIR / "qingshan_E15_redo_coverage_loudness_20260711.txt"

TAIL_DURATION = 3.0
REGULAR_SEGMENT_DURATION = 2.3
MICRO_SEGMENT_DURATION = 0.8
FLASH_DURATION = 0.2

SOURCES = {
    "01": "working_assets/e15_api_20260711/videos/shot_01/result_01.mp4",
    "02": "working_assets/e15_api_20260711/videos/shot_02/result_01.mp4",
    "03": "working_assets/e15_api_20260711/videos/shot_03/result_01.mp4",
    "04R": "working_assets/e15_redo_20260711/videos/shot_04R/result_01.mp4",
    "05R": "working_assets/e15_redo_20260711/videos/shot_05R/result_01.mp4",
    "06R": "working_assets/e15_redo_20260711/videos/shot_06R/result_01.mp4",
    "07": "working_assets/e15_api_20260711/videos/shot_07/result_01.mp4",
    "08R": "working_assets/e15_redo_20260711/videos/shot_08R/result_01.mp4",
    "09": "working_assets/e15_api_20260711/videos/shot_09/result_01.mp4",
    "10": "working_assets/e15_api_20260711/videos/shot_10/result_01.mp4",
    "11": "working_assets/e15_api_20260711/videos/shot_11_repair01/result_01.mp4",
    "12": "working_assets/e15_api_20260711/videos/shot_12/result_01.mp4",
    "13R": "working_assets/e15_redo_20260711/videos/shot_13R/result_01.mp4",
    "14R": "working_assets/e15_redo_20260711/videos/shot_14R/result_01.mp4",
    "15R": "working_assets/e15_redo_20260711/videos/shot_15R/result_01.mp4",
    "16": "working_assets/e15_api_20260711/videos/shot_16/result_01.mp4",
    "17": "working_assets/e15_api_20260711/videos/shot_17/result_01.mp4",
    "18R": "working_assets/e15_redo_20260711/videos/shot_18R/result_01.mp4",
    "19": "working_assets/e15_api_20260711/videos/shot_19/result_01.mp4",
    "20R": "working_assets/e15_redo_20260711/videos/shot_20R/result_01.mp4",
    "24C": "working_assets/e15_redo_coverage_20260711/videos/shot_24C/result_01.mp4",
    "25C": "working_assets/e15_redo_coverage_20260711/videos/shot_25C/result_01.mp4",
    "26C": "working_assets/e15_redo_coverage_20260711/videos/shot_26C/result_01.mp4",
    "27C": "working_assets/e15_redo_coverage_20260711/videos/shot_27C/result_01.mp4",
    "28C": "working_assets/e15_redo_coverage_20260711/videos/shot_28C/result_01.mp4",
    "29C": "working_assets/e15_redo_coverage_20260711/videos/shot_29C/result_01.mp4",
    "30C": "working_assets/e15_redo_coverage_20260711/videos/shot_30C/result_01.mp4",
    "31C": "working_assets/e15_redo_coverage_20260711/videos/shot_31C/result_01.mp4",
    "32C": "working_assets/e15_redo_coverage_20260711/videos/shot_32C/result_01.mp4",
    "33C": "working_assets/e15_redo_coverage_20260711/videos/shot_33C/result_01.mp4",
    "34C": "working_assets/e15_redo_coverage_20260711/videos/shot_34C/result_01.mp4",
    "35C": "working_assets/e15_redo_coverage_20260711/videos/shot_35C/result_01.mp4",
    "36C": "working_assets/e15_redo_coverage_20260711/videos/shot_36C/result_01.mp4",
    "37C": "working_assets/e15_redo_coverage_20260711/videos/shot_37C/result_01.mp4",
    "38C": "working_assets/e15_redo_coverage_20260711/videos/shot_38C/result_01.mp4",
    "39C": "working_assets/e15_redo_coverage_20260711/videos/shot_39C/result_01.mp4",
    "40C": "working_assets/e15_redo_coverage_20260711/videos/shot_40C/result_01.mp4",
    "41C": "working_assets/e15_redo_coverage_20260711/videos/shot_41C/result_01.mp4",
}

# 72 short edit beats: original story order with A/B, reaction and evidence inserts.
SEQUENCE = [
    "01", "21H", "02", "22H", "03", "35C!", "24C", "04R", "FLASH!", "25C", "26C", "27C", "28C", "05R",
    "29C", "06R", "30C", "31C", "27C!", "07", "32C", "08R", "33C", "09", "10", "11", "30C",
    "12", "31C", "13R", "FLASH!", "34C", "25C!", "25C", "14R", "26C", "27C", "36C", "15R", "35C", "37C",
    "16", "35C", "18R", "36C", "34C!", "19", "37C", "20R", "38C", "39C", "40C", "FLASH!", "41C", "01",
    "02", "03", "04R", "24C", "30C!", "05R", "25C", "FLASH!", "06R", "27C", "08R", "28C", "11", "33C",
    "13R", "34C", "14R", "26C", "35C!", "15R", "35C", "19", "37C", "20R", "38C", "39C", "41C",
    "40C!", "35C!",
]

# Map missing planned inserts to reusable already-generated story equivalents.
ALIASES = {
    "21H": "02",
    "22H": "01",
}


def run(args: list[str], *, capture: bool = False, check: bool = True):
    if capture:
        return subprocess.run(args, text=True, capture_output=True, check=check)
    subprocess.run(args, check=check)


def duration(path: Path) -> float:
    proc = run([str(FFMPEG), "-hide_banner", "-i", str(path)], capture=True, check=False)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not match:
        raise SystemExit(f"Cannot read duration: {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def subtitles_from_config() -> dict[str, str]:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    subtitles: dict[str, str] = {}
    for shot_id, spec in data["shot_expectations"].items():
        text = (spec.get("dialogue") or "").strip()
        text = re.sub(r"^[^：:]{1,8}[：:]", "", text).strip()
        if text:
            subtitles[str(int(shot_id)).zfill(2)] = text.replace("\\N", " ")
    return subtitles


def normalize_slice(src: Path, dst: Path, *, start: float, length: float) -> None:
    vf = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,setsar=1"
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "warning", "-y",
        "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}",
        "-vf", vf,
        "-af", "aresample=async=1:first_pts=0,loudnorm=I=-22:TP=-3:LRA=14",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(dst),
    ])


def concat(paths: list[Path], out: Path) -> None:
    list_file = out.with_suffix(".txt")
    list_file.write_text("".join(f"file '{p}'\n" for p in paths), encoding="utf-8")
    run([str(FFMPEG), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", "-movflags", "+faststart", str(out)])


def make_tail_card(dst: Path) -> None:
    filter_complex = (
        "[0:v]drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
        "text='青山':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=430,"
        "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
        "text='第16集继续':fontcolor=white:fontsize=38:x=(w-text_w)/2:y=520"
        "[card];[2:v]scale=250:-1[logo];[card][logo]overlay=(W-w)/2:620:format=auto[v]"
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


def make_flash_card(dst: Path) -> None:
    run([
        str(FFMPEG), "-y",
        "-f", "lavfi", "-i", f"color=c=white:s=720x1280:r=30:d={FLASH_DURATION}",
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=48000:d={FLASH_DURATION}",
        "-vf", "fade=t=out:st=0.06:d=0.12",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", str(dst),
    ])


def burn_subtitles(segment_labels: list[str]) -> None:
    subs = subtitles_from_config()
    SUBTITLE_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    for old in SUBTITLE_TEXT_DIR.glob("*.txt"):
        old.unlink()
    filters: list[str] = []
    cursor = 0.0
    for idx, label in enumerate(segment_labels):
        if label == "FLASH!":
            duration_this = FLASH_DURATION
        else:
            duration_this = MICRO_SEGMENT_DURATION if label.endswith("!") else REGULAR_SEGMENT_DURATION
        key = ALIASES.get(label.rstrip("!"), label.rstrip("!"))
        if not key.isdigit():
            cursor += duration_this
            continue
        text = subs.get(key.zfill(2))
        if not text:
            cursor += duration_this
            continue
        text_file = SUBTITLE_TEXT_DIR / f"seg_{idx+1:03d}.txt"
        text_file.write_text(text, encoding="utf-8")
        start = cursor + 0.10
        end = cursor + duration_this - 0.10
        filters.append(
            "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
            f"textfile={text_file}:fontcolor=white:fontsize=32:"
            "bordercolor=black@0.92:borderw=3:shadowcolor=black@0.65:shadowx=1:shadowy=1:"
            f"x=(w-text_w)/2:y=1102:enable='between(t,{start:.2f},{end:.2f})'"
        )
        cursor += duration_this
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "warning", "-y", "-i", str(TAILED),
        "-vf", ",".join(filters) if filters else "null",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-r", "30", "-fps_mode", "cfr",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(FINAL),
    ])


def contact(video: Path, out: Path, *, count: int, tile: str) -> None:
    frames = QA_DIR / out.stem
    frames.mkdir(parents=True, exist_ok=True)
    for old in frames.glob("*.jpg"):
        old.unlink()
    total = duration(video)
    for idx in range(count):
        t = min(total - 0.5, 1 + idx * max(1.0, (total - 2) / count))
        jpg = frames / f"frame_{idx+1:03d}.jpg"
        run([str(FFMPEG), "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(jpg)])
    run([
        str(FFMPEG), "-y", "-framerate", "1", "-pattern_type", "glob", "-i", str(frames / "frame_*.jpg"),
        "-vf", f"scale=150:-1,tile={tile}:padding=6:margin=6:color=white",
        "-frames:v", "1", "-q:v", "2", str(out),
    ])


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    SEG_DIR.mkdir(parents=True, exist_ok=True)
    for old in SEG_DIR.glob("*.mp4"):
        old.unlink()

    segments: list[Path] = []
    manifest = []
    use_counts: dict[str, int] = {}
    resolved_labels: list[str] = []
    for idx, raw_label in enumerate(SEQUENCE, 1):
        clean_label = raw_label.rstrip("!")
        if clean_label == "FLASH":
            dst = SEG_DIR / f"seg_{idx:03d}_{raw_label}.mp4"
            make_flash_card(dst)
            segments.append(dst)
            resolved_labels.append(raw_label)
            manifest.append({
                "segment": idx,
                "label": raw_label,
                "resolved_label": "FLASH",
                "source": "generated_hit_flash",
                "start": 0.0,
                "duration": FLASH_DURATION,
                "micro_cut": True,
                "purpose": "hit-stop white flash to expose cut point and avoid hidden long static spans",
            })
            continue
        label = ALIASES.get(clean_label, clean_label)
        src = BASE / SOURCES[label]
        if not src.exists():
            raise SystemExit(f"Missing source {label}: {src}")
        use_counts[label] = use_counts.get(label, 0) + 1
        src_duration = duration(src)
        segment_duration = MICRO_SEGMENT_DURATION if raw_label.endswith("!") else REGULAR_SEGMENT_DURATION
        start = 0.0 if use_counts[label] % 2 else max(0.0, src_duration - segment_duration - 0.05)
        dst = SEG_DIR / f"seg_{idx:03d}_{raw_label}.mp4"
        normalize_slice(src, dst, start=start, length=segment_duration)
        segments.append(dst)
        resolved_labels.append(raw_label)
        manifest.append({
            "segment": idx,
            "label": raw_label,
            "resolved_label": label,
            "source": str(src),
            "start": start,
            "duration": segment_duration,
            "micro_cut": raw_label.endswith("!"),
        })

    tail = SEG_DIR / "seg_999_tail.mp4"
    make_tail_card(tail)
    concat(segments, RAW)
    concat([*segments, tail], TAILED)
    burn_subtitles(resolved_labels)
    proc = run([str(FFMPEG), "-hide_banner", "-i", str(FINAL), "-af", "volumedetect", "-f", "null", "-"], capture=True, check=False)
    LOUDNESS_REPORT.write_text(proc.stderr, encoding="utf-8")
    contact(FINAL, CONTACT, count=30, tile="5x6")
    contact(FINAL, MIDPOINT_CONTACT, count=72, tile="8x9")
    SOURCE_MANIFEST.write_text(json.dumps({
        "episode": "E15",
        "final": str(FINAL),
        "rule": "Coverage recut: 72 short edit beats, no frozen extension, no central big text. Upload only after hit-baseline CI PASS.",
        "regular_segment_duration": REGULAR_SEGMENT_DURATION,
        "micro_segment_duration": MICRO_SEGMENT_DURATION,
        "flash_duration": FLASH_DURATION,
        "tail_duration": TAIL_DURATION,
        "segments": manifest,
        "duration_seconds": duration(FINAL),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(FINAL)
    print(CONTACT)
    print(MIDPOINT_CONTACT)
    print(SOURCE_MANIFEST)
    print(f"duration_seconds={duration(FINAL):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
