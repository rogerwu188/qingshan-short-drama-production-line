#!/usr/bin/env python3
"""Build a source-timeline VFR side-by-side reel for full V18C comfort review."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
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
OUT_DIR = ROOT / "qa/e36_agentcut_20260730/v18c_full_timeline_vfr_comparison_reel_v2"
OUTPUT = OUT_DIR / "E36_V18C_FULL_TIMELINE_V15_V18C_FRAME_INDEX_LOCKED_VFR_COMPARISON_REEL_V2.mp4"
RENDER_LOG = OUT_DIR / "E36_V18C_FULL_TIMELINE_V15_V18C_FRAME_INDEX_LOCKED_VFR_COMPARISON_REEL_V2_render.log"
DECODE_LOG = OUT_DIR / "E36_V18C_FULL_TIMELINE_V15_V18C_FRAME_INDEX_LOCKED_VFR_COMPARISON_REEL_V2_decode.log"
PROBE_JSON = OUT_DIR / "E36_V18C_FULL_TIMELINE_V15_V18C_FRAME_INDEX_LOCKED_VFR_COMPARISON_REEL_V2_media_probe.json"
CONTACT_SHEET = OUT_DIR / "E36_V18C_FULL_TIMELINE_V15_V18C_FRAME_INDEX_LOCKED_VFR_COMPARISON_REEL_V2_contact_sheet.jpg"
MANIFEST = OUT_DIR / "E36_V18C_FULL_TIMELINE_FRAME_INDEX_LOCKED_VFR_COMPARISON_REEL_MANIFEST_V2.json"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe(path: Path) -> dict:
    result = subprocess.run(
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
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def video_frame_pts(path: Path) -> list[float]:
    result = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [float(line.rstrip(",")) for line in result.stdout.splitlines() if line.strip()]


def candidate_timeline_expression(frame_pts: list[float]) -> tuple[str, list[dict]]:
    if len(frame_pts) != 6751:
        raise RuntimeError(f"unexpected candidate frame count: {len(frame_pts)}")
    gap_steps = []
    terms = ["N"]
    for index in range(1, len(frame_pts)):
        interval_frames = round((frame_pts[index] - frame_pts[index - 1]) * 24)
        if interval_frames not in (1, 2, 3):
            raise RuntimeError(f"non-grid candidate PTS interval at frame {index}: {frame_pts[index] - frame_pts[index - 1]}")
        extra = interval_frames - 1
        if extra:
            gap_steps.append({"frame_index": index, "extra_24fps_intervals": extra})
            terms.append(f"{extra}*gte(N\\,{index})")
    expression = f"({' + '.join(terms)})/(24*TB)+{frame_pts[0]:.6f}/TB"
    return expression, gap_steps


def audio_payload_sha256(path: Path) -> str:
    with tempfile.NamedTemporaryFile(suffix=".aac", dir=OUT_DIR) as handle:
        subprocess.run(
            [str(FFMPEG), "-v", "error", "-y", "-i", str(path), "-map", "0:a:0", "-c:a", "copy", "-f", "adts", handle.name],
            check=True,
        )
        handle.flush()
        return sha256(Path(handle.name))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    candidate_pts = video_frame_pts(CANDIDATE)
    setpts_expression, gap_steps = candidate_timeline_expression(candidate_pts)
    filter_graph = (
        f"[0:v]settb=AVTB,setpts='{setpts_expression}',scale=360:640:force_original_aspect_ratio=decrease,"
        f"pad=360:640:(ow-iw)/2:(oh-ih)/2:black[s];"
        f"[1:v]settb=AVTB,setpts='{setpts_expression}',scale=360:640:force_original_aspect_ratio=decrease,"
        f"pad=360:640:(ow-iw)/2:(oh-ih)/2:black[c];"
        f"[s][c]hstack=inputs=2,drawbox=x=0:y=0:w=720:h=34:color=black@0.70:t=fill,"
        f"drawtext=fontfile={FONT}:text='V15 CANONICAL':x=12:y=7:fontsize=18:fontcolor=white,"
        f"drawtext=fontfile={FONT}:text='V18C REVERSIBLE':x=372:y=7:fontsize=18:fontcolor=white[outv]"
    )
    command = [
        str(FFMPEG),
        "-y",
        "-i",
        str(SOURCE),
        "-i",
        str(CANDIDATE),
        "-filter_complex",
        filter_graph,
        "-map",
        "[outv]",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-pix_fmt",
        "yuv420p",
        "-fps_mode",
        "vfr",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(OUTPUT),
    ]
    with RENDER_LOG.open("wb") as handle:
        subprocess.run(command, cwd=ROOT, check=True, stdout=handle, stderr=subprocess.STDOUT)
    render_text = RENDER_LOG.read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?:dup|drop)=[1-9]", render_text, flags=re.IGNORECASE):
        raise RuntimeError("mux inserted or dropped frames in full-timeline comparison reel")

    probe = ffprobe(OUTPUT)
    video_stream = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    if not (
        video_stream["width"] == 720
        and video_stream["height"] == 640
        and int(video_stream["nb_frames"]) == 6751
        and abs(float(probe["format"]["duration"]) - 282.828) < 0.002
    ):
        raise RuntimeError(f"unexpected full-timeline comparison probe: {probe}")
    PROBE_JSON.write_text(json.dumps(probe, indent=2) + "\n", encoding="utf-8")

    with DECODE_LOG.open("wb") as handle:
        subprocess.run([str(FFMPEG), "-v", "error", "-i", str(OUTPUT), "-f", "null", "-"], check=True, stderr=handle)

    capture = cv2.VideoCapture(str(OUTPUT))
    frames = []
    sample_seconds = [6.0 + 12.0 * index for index in range(24)]
    for second in sample_seconds:
        capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"cannot sample full-timeline reel at {second}s")
        frames.append(cv2.resize(frame, (240, 213), interpolation=cv2.INTER_AREA))
    capture.release()
    rows = [cv2.hconcat(frames[index : index + 6]) for index in range(0, 24, 6)]
    if not cv2.imwrite(str(CONTACT_SHEET), cv2.vconcat(rows), [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise RuntimeError(f"cannot write {CONTACT_SHEET}")

    candidate_audio_sha = audio_payload_sha256(CANDIDATE)
    output_audio_sha = audio_payload_sha256(OUTPUT)
    if output_audio_sha != candidate_audio_sha:
        raise RuntimeError("comparison reel audio payload differs from V18C")

    manifest = {
        "schema": "qingshan.e36.v18c_full_timeline_vfr_comparison_reel_manifest.v2",
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": sha256(SOURCE),
        "candidate": str(CANDIDATE.relative_to(ROOT)),
        "candidate_sha256": sha256(CANDIDATE),
        "layout": "left V15 canonical, right V18C reversible candidate; both locked by frame index to the candidate VFR presentation timeline",
        "candidate_first_frame_pts_seconds": candidate_pts[0],
        "candidate_last_frame_pts_seconds": candidate_pts[-1],
        "candidate_vfr_gap_steps": gap_steps,
        "candidate_vfr_gap_step_count": len(gap_steps),
        "audio": "V18C AAC stream copied without re-encoding",
        "candidate_audio_payload_sha256": candidate_audio_sha,
        "output_audio_payload_sha256": output_audio_sha,
        "audio_payload_exact": True,
        "output": str(OUTPUT.relative_to(ROOT)),
        "output_sha256": sha256(OUTPUT),
        "media_probe": str(PROBE_JSON.relative_to(ROOT)),
        "media_probe_sha256": sha256(PROBE_JSON),
        "render_log": str(RENDER_LOG.relative_to(ROOT)),
        "render_log_sha256": sha256(RENDER_LOG),
        "decode_log": str(DECODE_LOG.relative_to(ROOT)),
        "decode_log_sha256": sha256(DECODE_LOG),
        "contact_sheet": str(CONTACT_SHEET.relative_to(ROOT)),
        "contact_sheet_sha256": sha256(CONTACT_SHEET),
        "v1_fail_preserved": {
            "path": "qa/e36_agentcut_20260730/v18c_full_timeline_vfr_comparison_reel_v1/E36_V18C_FULL_TIMELINE_V15_V18C_SOURCE_VFR_COMPARISON_REEL_V1.mp4",
            "reason": "framesync merged unequal source and candidate PTS grids, producing 13309 frames instead of6751",
            "promotion": "FAIL_PRESERVED_DO_NOT_USE",
        },
        "sample_seconds": sample_seconds,
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "promotion": "NOT_GRANTED_REVIEW_MEDIA_ONLY",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(MANIFEST)


if __name__ == "__main__":
    main()
