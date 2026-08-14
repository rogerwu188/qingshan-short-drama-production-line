#!/usr/bin/env python3
"""Render V18C-to-V19 mapped full-speed reels for inherited motion hotspots."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = Path(imageio_ffmpeg.get_ffmpeg_exe())
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
BASE = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v18_zero_credit_dynamic_reframe_probe/E36_ACCEPTED_ONLY_AGENTCUT_V18C_TWO_PART_DYNAMIC_REFRAME_EXACT_V15_AUDIO_PROBE.mp4"
V19 = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v19_v18c_plus_line10/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10.mp4"
AUTHORITY = ROOT / "qa/e36_agentcut_20260730/E36_V18C_HIGH_MOTION_BURST_REVIEW_V1.json"
OUT = ROOT / "qa/e36_agentcut_20260730/v19_mapped_high_motion_realtime_reel_v1"
REEL = OUT / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_REALTIME_REEL_V1.mp4"
CONTACT = OUT / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_CONTACT_V1.jpg"
PROBE = OUT / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_PROBE_V1.json"
RENDER_LOG = OUT / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_RENDER_V1.log"
DECODE_LOG = OUT / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_DECODE_V1.log"
MANIFEST = OUT / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_MANIFEST_V1.json"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
INSERT_AT = 70.928060
INSERT_DURATION = 6.082993


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    authority = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    windows = []
    filters = []
    concat_inputs = []
    for index, row in enumerate(authority["sheets"], start=1):
        base_center = float(row["center_seconds"])
        v19_center = base_center if base_center < INSERT_AT else base_center + INSERT_DURATION
        bs, be = base_center - 2.0, base_center + 2.0
        vs, ve = v19_center - 2.0, v19_center + 2.0
        windows.append({
            "index": index,
            "base_seconds": [bs, be],
            "v19_seconds": [vs, ve],
            "base_center_seconds": base_center,
            "v19_center_seconds": v19_center,
            "mapping": "UNCHANGED_PRE_INSERT" if base_center < INSERT_AT else "SHIFTED_PLUS_6P082993_POST_INSERT",
            "estimated_speed_px_per_second": row["estimated_speed_px_per_second"],
        })
        filters.extend([
            f"[0:v]trim=start={bs}:end={be},settb=AVTB,setpts=PTS-STARTPTS,fps=24,tpad=stop_mode=clone:stop_duration=0.2,trim=end_frame=96,setpts=N/(24*TB),scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2:black[b{index}]",
            f"[1:v]trim=start={vs}:end={ve},settb=AVTB,setpts=PTS-STARTPTS,fps=24,tpad=stop_mode=clone:stop_duration=0.2,trim=end_frame=96,setpts=N/(24*TB),scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2:black[v{index}]",
            f"[b{index}][v{index}]hstack=inputs=2,drawbox=x=0:y=0:w=720:h=58:color=black@0.72:t=fill,drawtext=fontfile={FONT}:text='V18C BASE':x=12:y=10:fontsize=20:fontcolor=white,drawtext=fontfile={FONT}:text='V19 MAPPED':x=372:y=10:fontsize=20:fontcolor=white,drawtext=fontfile={FONT}:text='HOTSPOT {index}/8  BASE {base_center:.3f}s  V19 {v19_center:.3f}s':x=12:y=35:fontsize=15:fontcolor=yellow[o{index}]",
            f"[1:a]atrim=start={vs}:end={ve},asetpts=PTS-STARTPTS,aresample=48000:async=0:first_pts=0,apad,atrim=duration=4,asetpts=PTS-STARTPTS[a{index}]",
        ])
        concat_inputs.append(f"[o{index}][a{index}]")
    filters.append("".join(concat_inputs) + "concat=n=8:v=1:a=1[outv][outa]")
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [str(FFMPEG), "-y", "-i", str(BASE), "-i", str(V19), "-filter_complex", ";".join(filters), "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(REEL)]
    with RENDER_LOG.open("wb") as log:
        subprocess.run(cmd, cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
    probe = json.loads(subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-show_entries", "stream=index,codec_type,width,height,r_frame_rate,nb_frames,duration", "-of", "json", str(REEL)], check=True, capture_output=True, text=True).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    if video["width"] != 720 or video["height"] != 640 or video["r_frame_rate"] != "24/1" or int(video["nb_frames"]) != 768 or float(probe["format"]["duration"]) != 32.0:
        raise RuntimeError(f"unexpected probe {probe}")
    PROBE.write_text(json.dumps(probe, indent=2) + "\n", encoding="utf-8")
    with DECODE_LOG.open("wb") as log:
        subprocess.run([str(FFMPEG), "-v", "error", "-i", str(REEL), "-f", "null", "-"], check=True, stderr=log)
    cap = cv2.VideoCapture(str(REEL))
    frames = []
    for second in range(2, 32, 4):
        cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"cannot sample {second}")
        frames.append(cv2.resize(frame, (360, 320), interpolation=cv2.INTER_AREA))
    cap.release()
    sheet = cv2.vconcat([cv2.hconcat(frames[:4]), cv2.hconcat(frames[4:])])
    if not cv2.imwrite(str(CONTACT), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise RuntimeError("cannot write contact")
    manifest = {
        "schema": "e36_v19_mapped_high_motion_realtime_reel_v1",
        "base": {"path": str(BASE.relative_to(ROOT)), "sha256": sha256(BASE)},
        "candidate": {"path": str(V19.relative_to(ROOT)), "sha256": sha256(V19), "status": "REVERSIBLE_NOT_PROMOTED"},
        "window_authority": {"path": str(AUTHORITY.relative_to(ROOT)), "sha256": sha256(AUTHORITY)},
        "mapping": {"insert_at_seconds": INSERT_AT, "insert_duration_seconds": INSERT_DURATION},
        "windows": windows,
        "review_reel": {"path": str(REEL.relative_to(ROOT)), "sha256": sha256(REEL), "duration_seconds": 32.0, "fps": 24, "frames": 768},
        "contact_sheet": {"path": str(CONTACT.relative_to(ROOT)), "sha256": sha256(CONTACT)},
        "media_probe": {"path": str(PROBE.relative_to(ROOT)), "sha256": sha256(PROBE)},
        "decode_log": {"path": str(DECODE_LOG.relative_to(ROOT)), "sha256": sha256(DECODE_LOG)},
        "render_log": {"path": str(RENDER_LOG.relative_to(ROOT)), "sha256": sha256(RENDER_LOG)},
        "purpose": "Full-frame-rate mapped review of all eight inherited V18C high-motion hotspots in V19; review media only and not a full-runtime promotion clearance.",
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(MANIFEST.relative_to(ROOT)), "sha256": sha256(MANIFEST), "reel_sha256": sha256(REEL), "contact_sha256": sha256(CONTACT)}))


if __name__ == "__main__":
    main()
