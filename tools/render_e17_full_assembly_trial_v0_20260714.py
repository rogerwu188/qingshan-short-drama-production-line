#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
PLAN = Path(os.environ.get("E17_FULL_RENDER_PLAN", str(BASE / "configs/e17_full_render_plan_v0_20260714.json")))
OUT_DIR = Path(os.environ.get("E17_FULL_RENDER_OUT_DIR", str(BASE / "exports/e17/full_assembly_trial_v0_20260714")))
SEG_DIR = OUT_DIR / "segments"
QA_DIR = BASE / "qa/e17_full_assembly_trial_v0_20260714"
OUT = OUT_DIR / os.environ.get("E17_FULL_RENDER_OUT_NAME", "qingshan_E17_full_assembly_visual_trial_v0_20260714.mp4")
CONTACT = QA_DIR / os.environ.get("E17_FULL_RENDER_CONTACT_NAME", "qingshan_E17_full_assembly_visual_trial_v0_contact_20260714.jpg")
REPORT = OUT_DIR / os.environ.get("E17_FULL_RENDER_REPORT_NAME", "E17_FULL_ASSEMBLY_VISUAL_TRIAL_V0_RENDER_REPORT_20260714.json")
OUTPUT_FPS = float(os.environ.get("E17_FULL_RENDER_FPS", "24"))

SCALE_FILTER = (
    "scale=720:1280:force_original_aspect_ratio=decrease,"
    f"pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={OUTPUT_FPS:g},format=yuv420p"
)


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=BASE, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise SystemExit(
            "Command failed:\n"
            + " ".join(cmd)
            + "\nSTDOUT:\n"
            + proc.stdout[-2000:]
            + "\nSTDERR:\n"
            + proc.stderr[-4000:]
        )
    return proc


def duration(path: Path) -> float:
    proc = run([str(FFMPEG), "-hide_banner", "-i", str(path)], check=False)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not match:
        raise SystemExit(f"Cannot read duration: {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def render_segment(item: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if item["source_id"] == "NALU_tail":
        run(
            [
                str(FFMPEG),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s=720x1280:r={OUTPUT_FPS:g}:d={item['duration_sec']}",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=channel_layout=stereo:sample_rate=48000:d={item['duration_sec']}",
                "-vf",
                "drawtext=text='NALU':fontcolor=white:fontsize=54:x=(w-text_w)/2:y=(h-text_h)/2",
                "-shortest",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(out),
            ]
        )
        return
    src = Path(item["path"])
    if not src.exists():
        raise SystemExit(f"Missing source: {src}")
    start = float(item["in_sec"])
    dur = float(item["duration_sec"])
    video_filter = SCALE_FILTER
    crop_bottom_fraction = float(item.get("crop_bottom_fraction", 0) or 0)
    if crop_bottom_fraction:
        if not 0 < crop_bottom_fraction < 0.5:
            raise SystemExit(f"Invalid crop_bottom_fraction for {item['source_id']}: {crop_bottom_fraction}")
        video_filter = (
            f"crop=iw:ih*(1-{crop_bottom_fraction:.4f}):0:0,"
            "scale=720:1280:force_original_aspect_ratio=increase,"
            f"crop=720:1280,setsar=1,fps={OUTPUT_FPS:g},format=yuv420p"
        )
    mask_bottom_fraction = float(item.get("mask_bottom_fraction", 0) or 0)
    if mask_bottom_fraction:
        if not 0 < mask_bottom_fraction < 0.5:
            raise SystemExit(f"Invalid mask_bottom_fraction for {item['source_id']}: {mask_bottom_fraction}")
        video_filter = (
            f"{video_filter},"
            f"drawbox=x=0:y=ih*(1-{mask_bottom_fraction:.4f}):w=iw:h=ih*{mask_bottom_fraction:.4f}:color=black@1:t=fill"
        )
    eq_brightness = item.get("eq_brightness")
    if eq_brightness is not None:
        value = float(eq_brightness)
        if not -0.35 <= value <= 0.35:
            raise SystemExit(f"Invalid eq_brightness for {item['source_id']}: {value}")
        video_filter = f"{video_filter},eq=brightness={value:.4f}:contrast=1.0"
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(src),
            "-t",
            f"{dur:.3f}",
            "-filter_complex",
            f"[0:v]{video_filter}[v];anullsrc=channel_layout=stereo:sample_rate=48000:d={dur:.3f}[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(out),
        ]
    )


def build_contact(video: Path, total_duration: float) -> None:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    times = [max(0.5, total_duration * i / 12) for i in range(1, 12)]
    frames = []
    for idx, t in enumerate(times, 1):
        frame = QA_DIR / f"contact_frame_{idx:02d}_{t:.1f}s.jpg"
        run(
            [
                str(FFMPEG),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{t:.3f}",
                "-i",
                str(video),
                "-vf",
                "scale=240:426:force_original_aspect_ratio=decrease,pad=240:426:(ow-iw)/2:(oh-ih)/2:black",
                "-frames:v",
                "1",
                str(frame),
            ]
        )
        frames.append(frame)
    input_args = []
    for frame in frames:
        input_args.extend(["-i", str(frame)])
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *input_args,
            "-filter_complex",
            "tile=3x4:padding=8:margin=8",
            "-frames:v",
            "1",
            str(CONTACT),
        ]
    )


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SEG_DIR.mkdir(parents=True, exist_ok=True)
    built = []
    for item in plan["segments"]:
        segment = SEG_DIR / f"{item['idx']:03d}_{item['source_id'].replace('/', '_')}.mp4"
        render_segment(item, segment)
        actual = duration(segment)
        built.append({**item, "segment_path": str(segment), "actual_duration_sec": round(actual, 3)})

    concat_file = OUT_DIR / "concat.txt"
    concat_file.write_text("".join(f"file '{item['segment_path']}'\n" for item in built), encoding="utf-8")
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(OUT),
        ]
    )
    total = duration(OUT)
    build_contact(OUT, total)
    payload = {
        "episode": "E17",
        "status": "VISUAL_TRIAL_RENDER_COMPLETE",
        "not_release_candidate": True,
        "plan": str(PLAN),
        "output": str(OUT),
        "contact_sheet": str(CONTACT),
        "target_runtime_sec": plan.get("target_runtime_sec"),
        "actual_runtime_sec": round(total, 3),
        "output_fps": OUTPUT_FPS,
        "frame_cadence_rule": "Preserve the 24fps cadence of E17 source clips; do not convert to 30fps.",
        "segments": built,
        "next_qa": [
            "contact-sheet manual review",
            "bottom-band OCR full render",
            "SRC-004 zone OCR/mask review",
            "ASL/sentence-hold review",
            "motion review for reaction beds",
        ],
    }
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "duration": round(total, 3), "report": str(REPORT), "contact": str(CONTACT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
