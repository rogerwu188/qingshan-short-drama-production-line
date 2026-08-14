#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
OUT_DIR = BASE / "exports/e14/final_package_20260711"
QA_DIR = BASE / "qa/e14_final_package_20260711"
SEG_DIR = OUT_DIR / "segments"
SUBTITLE_TEXT_DIR = OUT_DIR / "subtitle_texts_clean_20260711"
PROP_TEXT_DIR = OUT_DIR / "prop_texts_clean_20260711"
LOGO = BASE / "libraries/brand/nalu_motion_cat_logo_v1.png"
AMBIENCE = BASE / "libraries/audio/sound_refs/e09_multimodal_20260709/AMB-taiping-clinic-dawn-night-ref.wav"

RAW = OUT_DIR / "qingshan_E14_raw_normalized_20260711.mp4"
TAILED = OUT_DIR / "qingshan_E14_tailed_nalu_20260711.mp4"
FINAL = OUT_DIR / "qingshan_E14_final_subtitled_nalu_20260711.mp4"
SOURCE_MANIFEST = OUT_DIR / "e14_final_source_manifest_20260711.json"
LOUDNESS_REPORT = QA_DIR / "qingshan_E14_final_loudness_20260711.txt"
CONTACT = QA_DIR / "qingshan_E14_final_subtitled_contact_20260711.jpg"
MIDPOINT_CONTACT = QA_DIR / "qingshan_E14_final_all_shots_midpoint_20260711.jpg"

TAIL_DURATION = 3.0
SOURCE_BY_SHOT = {
    1: "working_assets/e14_api_20260711/videos/shot_01/result_01.mp4",
    2: "working_assets/e14_api_20260711/videos/shot_02/result_01.mp4",
    3: "working_assets/e14_api_20260711/videos/shot_03/result_01.mp4",
    4: "working_assets/e14_api_20260711/videos/shot_04/result_01.mp4",
    5: "working_assets/e14_api_20260711/videos/shot_05/result_01.mp4",
    6: "working_assets/e14_api_20260711/videos/shot_06/result_01.mp4",
    7: "working_assets/e14_api_20260711/videos/shot_07/result_01.mp4",
    8: "working_assets/e14_api_20260711/videos/shot_08/result_01.mp4",
    9: "working_assets/e14_api_20260711/videos/shot_09/result_01.mp4",
    10: "working_assets/e14_api_20260711/videos/shot_10/result_01.mp4",
    11: "working_assets/e14_api_20260711/videos/shot_11/result_01.mp4",
    12: "working_assets/e14_api_20260711/videos/shot_12/result_01.mp4",
    13: "working_assets/e14_api_20260711/videos/shot_13/result_01.mp4",
    14: "working_assets/e14_api_20260711/videos/shot_14/result_01.mp4",
    15: "working_assets/e14_api_20260711/videos/shot_15/result_01.mp4",
    16: "working_assets/e14_api_20260711/videos/shot_16_repair_v2/result_01.mp4",
    17: "working_assets/e14_api_20260711/videos/shot_17/result_01.mp4",
    18: "working_assets/e14_api_20260711/videos/shot_18/result_01.mp4",
    19: "working_assets/e14_api_20260711/videos/shot_19/result_01.mp4",
    20: "working_assets/e14_api_20260711/videos/shot_20/result_01.mp4",
}
AMBIENCE_BED_SHOTS = {1, 3, 5, 7, 10, 13, 16, 17, 18}

SUBTITLES = {
    2: "这不是催命，是催我们出门。",
    4: "纸纹一样，灯是县衙后门的。",
    6: "不追灯了，等他自己回头。",
    8: "火漆裂口在内侧，命令是从县衙里伪造的。",
    9: "你现在冲出去，医馆就是替罪的门。",
    11: "再跟一步，你们医馆先封。",
    12: "你怕的不是我，是送你来的人。",
    14: "路线给你，别说是我。",
    15: "三更后门，不是巡夜，是运尸。",
    19: "他们把尸体送进来了。",
    20: "你现在救的不是师父，是你自己的命。",
}

PROP_TEXTS = {
    1: [{"text": "今夜收医馆", "x": 280, "y": 610, "size": 28, "start_pad": 0.2, "end_pad": 0.2}],
    3: [{"text": "今夜收医馆", "x": 300, "y": 650, "size": 24, "start_pad": 0.1, "end_pad": 0.1}],
    5: [{"text": "今夜收医馆", "x": 260, "y": 630, "size": 24, "start_pad": 0.1, "end_pad": 0.1}],
    13: [{"text": "止血散", "x": 300, "y": 690, "size": 30, "start_pad": 0.1, "end_pad": 0.1}],
    14: [{"text": "后门三更", "x": 300, "y": 690, "size": 30, "start_pad": 0.1, "end_pad": 0.1}],
    18: [{"text": "今夜收医馆", "x": 292, "y": 760, "size": 24, "start_pad": 0.1, "end_pad": 0.1}],
}


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


def normalize(src: Path, dst: Path, *, add_ambience: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,setsar=1"
    base_args = [
        str(FFMPEG), "-y", "-i", str(src),
    ]
    if add_ambience:
        if not AMBIENCE.exists():
            raise SystemExit(f"Missing ambience bed: {AMBIENCE}")
        clip_duration = duration(src)
        filter_complex = (
            f"[0:v]{vf}[vout];"
            f"[1:a]atrim=0:{clip_duration:.3f},asetpts=PTS-STARTPTS,volume=0.16[amb];"
            "[0:a]volume=1.0[srca];"
            "[srca][amb]amix=inputs=2:duration=first:dropout_transition=0,"
            "loudnorm=I=-24:TP=-3:LRA=14[aout]"
        )
        run([
            *base_args, "-stream_loop", "-1", "-i", str(AMBIENCE),
            "-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(dst),
        ])
        return
    run([
        *base_args,
        "-vf", vf,
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
        "text='第15集继续':fontcolor=white:fontsize=38:x=(w-text_w)/2:y=520,"
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
    return SUBTITLES


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
    write_prop_textfiles()
    filters: list[str] = []
    cursor = 0.0
    for idx, shot_duration in enumerate(shot_durations, 1):
        for prop_no, prop in enumerate(PROP_TEXTS.get(idx, []), 1):
            textfile = PROP_TEXT_DIR / f"shot_{idx:02d}_prop_{prop_no:02d}.txt"
            start = cursor + prop.get("start_pad", 0.1)
            end = cursor + max(0.5, shot_duration - prop.get("end_pad", 0.1))
            filters.append(
                "drawtext=fontfile=/System/Library/Fonts/STHeiti\\ Medium.ttc:"
                f"textfile={textfile}:fontcolor=#1b1208@0.86:fontsize={prop['size']}:"
                "bordercolor=#f4ead0@0.16:borderw=1:"
                f"x={prop['x']}:y={prop['y']}:enable='between(t,{start:.2f},{end:.2f})'"
            )
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
        "-vf", ",".join(filters) if filters else "null",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-r", "30", "-fps_mode", "cfr",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(FINAL),
    ])


def write_prop_textfiles() -> None:
    PROP_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    for old in PROP_TEXT_DIR.glob("*.txt"):
        old.unlink()
    for shot, props in PROP_TEXTS.items():
        for prop_no, prop in enumerate(props, 1):
            (PROP_TEXT_DIR / f"shot_{shot:02d}_prop_{prop_no:02d}.txt").write_text(prop["text"], encoding="utf-8")


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
        src = BASE / SOURCE_BY_SHOT[shot]
        if not src.exists():
            raise SystemExit(f"Missing E14 source clip: {src}")
        dst = SEG_DIR / f"seg_{shot:03d}_shot_{shot:02d}.mp4"
        add_ambience = shot in AMBIENCE_BED_SHOTS
        normalize(src, dst, add_ambience=add_ambience)
        normalized_duration = duration(dst)
        shot_durations.append(normalized_duration)
        segments.append(dst)
        manifest.append({
            "shot": f"{shot:02d}",
            "source": "api",
            "path": str(src),
            "normalized": str(dst),
            "duration": normalized_duration,
            "added_ambience_bed": add_ambience,
        })

    tail = SEG_DIR / "seg_999_tail.mp4"
    make_tail_card(tail)
    concat(segments, RAW)
    concat([*segments, tail], TAILED)
    burn_subtitles(shot_durations)
    write_loudness_report()

    total = sum(shot_durations) + TAIL_DURATION
    SOURCE_MANIFEST.write_text(json.dumps({
        "episode": "E14",
        "title": "县衙后门",
        "final": str(FINAL),
        "raw": str(RAW),
        "tailed": str(TAILED),
        "rule": "Clean dialogue subtitles only; speaker prefixes stripped. Dialogue shots keep native multimodal voice assets; plot-critical blank props receive local Chinese text overlays before QA.",
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
