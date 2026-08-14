#!/usr/bin/env python3
"""Render a full-speed V15/V18C comparison reel for the eight fastest windows."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = Path(
    "/Users/rogerwu/Library/Python/3.9/lib/python/site-packages/"
    "imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
)
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
SOURCE = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v15/E36_ACCEPTED_ONLY_AGENTCUT_V15_PACED_ROOMTONE_REPAIR_FINAL.mp4"
CANDIDATE = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v18_zero_credit_dynamic_reframe_probe/E36_ACCEPTED_ONLY_AGENTCUT_V18C_TWO_PART_DYNAMIC_REFRAME_EXACT_V15_AUDIO_PROBE.mp4"
WINDOWS_QA = ROOT / "qa/e36_agentcut_20260730/E36_V18C_HIGH_MOTION_BURST_REVIEW_V1.json"
OUT_DIR = ROOT / "qa/e36_agentcut_20260730/v18c_high_motion_realtime_comparison_reel_v3"
OUTPUT = OUT_DIR / "E36_V18C_EIGHT_HIGH_MOTION_WINDOWS_V15_V18C_REALTIME_COMPARISON_REEL_V3.mp4"
RENDER_LOG = OUT_DIR / "E36_V18C_EIGHT_HIGH_MOTION_WINDOWS_V15_V18C_REALTIME_COMPARISON_REEL_V3_render.log"
DECODE_LOG = OUT_DIR / "E36_V18C_EIGHT_HIGH_MOTION_WINDOWS_V15_V18C_REALTIME_COMPARISON_REEL_V3_decode.log"
PROBE_JSON = OUT_DIR / "E36_V18C_EIGHT_HIGH_MOTION_WINDOWS_V15_V18C_REALTIME_COMPARISON_REEL_V3_media_probe.json"
CONTACT_SHEET = OUT_DIR / "E36_V18C_EIGHT_HIGH_MOTION_WINDOWS_V15_V18C_REALTIME_COMPARISON_REEL_V3_contact_sheet.jpg"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    review = json.loads(WINDOWS_QA.read_text(encoding="utf-8"))
    windows = []
    filters = []
    concat_inputs = []
    for index, sheet in enumerate(review["sheets"], start=1):
        center = float(sheet["center_seconds"])
        start = center - 2.0
        end = center + 2.0
        windows.append(
            {
                "index": index,
                "start_seconds": start,
                "end_seconds": end,
                "center_seconds": center,
                "estimated_speed_px_per_second": sheet["estimated_speed_px_per_second"],
            }
        )
        filters.extend(
            [
                f"[0:v]trim=start={start}:end={end},settb=AVTB,setpts=PTS-STARTPTS,fps=24,tpad=stop_mode=clone:stop_duration=0.2,trim=end_frame=96,setpts=N/(24*TB),scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2:black[s{index}]",
                f"[1:v]trim=start={start}:end={end},settb=AVTB,setpts=PTS-STARTPTS,fps=24,tpad=stop_mode=clone:stop_duration=0.2,trim=end_frame=96,setpts=N/(24*TB),scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2:black[c{index}]",
                f"[s{index}][c{index}]hstack=inputs=2,drawbox=x=0:y=0:w=720:h=58:color=black@0.72:t=fill,drawtext=fontfile={FONT}:text='V15 CANONICAL':x=12:y=10:fontsize=20:fontcolor=white,drawtext=fontfile={FONT}:text='V18C REVERSIBLE':x=372:y=10:fontsize=20:fontcolor=white,drawtext=fontfile={FONT}:text='WINDOW {index}/8  SOURCE {start:.1f}-{end:.1f}s':x=12:y=35:fontsize=15:fontcolor=yellow[v{index}]",
                f"[1:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,aresample=48000:async=0:first_pts=0,apad,atrim=duration=4,asetpts=PTS-STARTPTS[a{index}]",
            ]
        )
        concat_inputs.append(f"[v{index}][a{index}]")
    filters.append("".join(concat_inputs) + f"concat=n={len(windows)}:v=1:a=1[outv][outa]")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        str(FFMPEG),
        "-y",
        "-i",
        str(SOURCE),
        "-i",
        str(CANDIDATE),
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[outv]",
        "-map",
        "[outa]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-fps_mode",
        "passthrough",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(OUTPUT),
    ]
    with RENDER_LOG.open("wb") as handle:
        subprocess.run(command, cwd=ROOT, check=True, stdout=handle, stderr=subprocess.STDOUT)

    probe_result = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_entries",
            "stream=index,codec_type,width,height,r_frame_rate,avg_frame_rate,nb_frames,duration",
            "-of",
            "json",
            str(OUTPUT),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe = json.loads(probe_result.stdout)
    video_stream = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    if not (
        video_stream["width"] == 720
        and video_stream["height"] == 640
        and video_stream["r_frame_rate"] == "24/1"
        and int(video_stream["nb_frames"]) == 768
        and float(probe["format"]["duration"]) == 32.0
    ):
        raise RuntimeError(f"unexpected comparison reel media probe: {probe}")
    PROBE_JSON.write_text(json.dumps(probe, indent=2) + "\n", encoding="utf-8")
    with DECODE_LOG.open("wb") as handle:
        subprocess.run([str(FFMPEG), "-v", "error", "-i", str(OUTPUT), "-f", "null", "-"], check=True, stderr=handle)

    capture = cv2.VideoCapture(str(OUTPUT))
    frames = []
    for second in range(2, 32, 4):
        capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"cannot sample comparison reel at {second}s")
        frames.append(cv2.resize(frame, (360, 320), interpolation=cv2.INTER_AREA))
    capture.release()
    contact_sheet = cv2.vconcat([cv2.hconcat(frames[:4]), cv2.hconcat(frames[4:])])
    if not cv2.imwrite(str(CONTACT_SHEET), contact_sheet, [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise RuntimeError(f"cannot write {CONTACT_SHEET}")

    manifest = {
        "schema": "qingshan.e36.v18c_high_motion_realtime_comparison_reel_manifest.v3",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": sha256(SOURCE),
        "candidate": str(CANDIDATE.relative_to(ROOT)),
        "candidate_sha256": sha256(CANDIDATE),
        "window_authority": str(WINDOWS_QA.relative_to(ROOT)),
        "window_authority_sha256": sha256(WINDOWS_QA),
        "windows": windows,
        "layout": "left V15 canonical, right V18C reversible candidate; full-speed four-second windows",
        "audio": "V18C source-window audio trimmed at original speed and re-encoded only for the review reel",
        "output": str(OUTPUT.relative_to(ROOT)),
        "output_sha256": sha256(OUTPUT),
        "render_log": str(RENDER_LOG.relative_to(ROOT)),
        "render_log_sha256": sha256(RENDER_LOG),
        "media_probe": str(PROBE_JSON.relative_to(ROOT)),
        "media_probe_sha256": sha256(PROBE_JSON),
        "decode_log": str(DECODE_LOG.relative_to(ROOT)),
        "decode_log_sha256": sha256(DECODE_LOG),
        "contact_sheet": str(CONTACT_SHEET.relative_to(ROOT)),
        "contact_sheet_sha256": sha256(CONTACT_SHEET),
        "v1_fail_preserved": {
            "path": "qa/e36_agentcut_20260730/v18c_high_motion_realtime_comparison_reel_v1/E36_V18C_EIGHT_HIGH_MOTION_WINDOWS_V15_V18C_REALTIME_COMPARISON_REEL_V1.mp4",
            "reason": "variable-frame-rate hstack produced 1296 frames at 40.4845539 fps and non-monotonic decode timestamps",
            "promotion": "FAIL_PRESERVED_DO_NOT_USE",
        },
        "v2_fail_preserved": {
            "path": "qa/e36_agentcut_20260730/v18c_high_motion_realtime_comparison_reel_v2/E36_V18C_EIGHT_HIGH_MOTION_WINDOWS_V15_V18C_REALTIME_COMPARISON_REEL_V2.mp4",
            "reason": "CFR output inserted six duplicate frames at segment boundaries; unsuitable for comfort adjudication despite exact nominal duration",
            "promotion": "FAIL_PRESERVED_DO_NOT_USE_FOR_COMFORT_ADJUDICATION",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "promotion": "NOT_GRANTED_REVIEW_MEDIA_ONLY",
    }
    manifest_path = OUT_DIR / "E36_V18C_EIGHT_HIGH_MOTION_WINDOWS_REALTIME_COMPARISON_REEL_MANIFEST_V3.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)


if __name__ == "__main__":
    main()
