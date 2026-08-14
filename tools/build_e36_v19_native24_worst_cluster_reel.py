#!/usr/bin/env python3
"""Build a full-speed V19 review reel for worst clusters found by native-rate QA."""

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
V19 = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v19_v18c_plus_line10/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10.mp4"
AUTHORITY = ROOT / "qa/e36_agentcut_20260730/E36_V18C_FULL_NATIVE24_PHASE_MOTION_DIAGNOSTIC_V1.json"
OUT = ROOT / "qa/e36_agentcut_20260730/v19_native24_worst_cluster_reel_v1"
REEL = OUT / "E36_V19_NATIVE24_WORST_CLUSTER_FULLSCREEN_REALTIME_REEL_V1.mp4"
CONTACT = OUT / "E36_V19_NATIVE24_WORST_CLUSTER_REPRESENTATIVE_CONTACT_V1.jpg"
PROBE = OUT / "E36_V19_NATIVE24_WORST_CLUSTER_PROBE_V1.json"
DECODE_LOG = OUT / "E36_V19_NATIVE24_WORST_CLUSTER_DECODE_V1.log"
RENDER_LOG = OUT / "E36_V19_NATIVE24_WORST_CLUSTER_RENDER_V1.log"
MANIFEST = OUT / "E36_V19_NATIVE24_WORST_CLUSTER_MANIFEST_V1.json"
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
    requested = [
        {"label": "p95_peak_98s", "base": [96.0, 100.0]},
        {"label": "largest_pair_136p542s", "base": [134.5, 138.5]},
        {"label": "sustained_cluster_162_167s", "base": [161.0, 168.0]},
    ]
    filters = []
    concat_inputs = []
    windows = []
    expected_frames = 0
    expected_duration = 0.0
    for index, row in enumerate(requested, start=1):
        bs, be = row["base"]
        vs = bs if bs < INSERT_AT else bs + INSERT_DURATION
        ve = be if be < INSERT_AT else be + INSERT_DURATION
        duration = be - bs
        frames = int(round(duration * 24))
        expected_frames += frames
        expected_duration += duration
        windows.append({
            "index": index,
            "label": row["label"],
            "base_seconds": [bs, be],
            "v19_seconds": [vs, ve],
            "mapping": "UNCHANGED_PRE_INSERT" if bs < INSERT_AT else "SHIFTED_PLUS_6P082993_POST_INSERT",
            "duration_seconds": duration,
            "frames": frames,
        })
        filters.extend([
            f"[0:v]trim=start={vs}:end={ve},settb=AVTB,setpts=PTS-STARTPTS,fps=24,tpad=stop_mode=clone:stop_duration=0.2,trim=end_frame={frames},setpts=N/(24*TB)[v{index}]",
            f"[0:a]atrim=start={vs}:end={ve},asetpts=PTS-STARTPTS,aresample=48000:async=0:first_pts=0,apad,atrim=duration={duration},asetpts=PTS-STARTPTS[a{index}]",
        ])
        concat_inputs.append(f"[v{index}][a{index}]")
    filters.append("".join(concat_inputs) + f"concat=n={len(windows)}:v=1:a=1[outv][outa]")

    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(FFMPEG), "-y", "-i", str(V19), "-filter_complex", ";".join(filters),
        "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-preset", "medium",
        "-crf", "18", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", "-c:a", "aac",
        "-b:a", "192k", "-movflags", "+faststart", str(REEL),
    ]
    with RENDER_LOG.open("wb") as log:
        subprocess.run(cmd, cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)

    probe = json.loads(subprocess.run([
        str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
        "-show_entries", "stream=index,codec_type,width,height,r_frame_rate,nb_frames,duration",
        "-of", "json", str(REEL),
    ], check=True, capture_output=True, text=True).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    if video["width"] != 720 or video["height"] != 1280 or video["r_frame_rate"] != "24/1":
        raise RuntimeError(f"unexpected video geometry {probe}")
    if int(video["nb_frames"]) != expected_frames or abs(float(probe["format"]["duration"]) - expected_duration) > 0.01:
        raise RuntimeError(f"unexpected duration/frame count {probe}")
    PROBE.write_text(json.dumps(probe, indent=2) + "\n", encoding="utf-8")
    with DECODE_LOG.open("wb") as log:
        subprocess.run([str(FFMPEG), "-v", "error", "-i", str(REEL), "-f", "null", "-"], check=True, stderr=log)

    sample_seconds = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 10.5, 12.5, 14.5]
    cap = cv2.VideoCapture(str(REEL))
    frames = []
    for second in sample_seconds:
        cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"cannot sample {second}")
        frames.append(cv2.resize(frame, (180, 320), interpolation=cv2.INTER_AREA))
    cap.release()
    sheet = cv2.vconcat([cv2.hconcat(frames[i:i + 4]) for i in range(0, 12, 4)])
    if not cv2.imwrite(str(CONTACT), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise RuntimeError("cannot write representative contact sheet")

    manifest = {
        "schema": "e36_v19_native24_worst_cluster_fullscreen_realtime_reel_v1",
        "source_cl2x": "CL2X-914",
        "source_mailbox_sha256": "fea59b5aa15786cd2e1224d9c4e5fca57f6d07f80a2e8c132495d43e6f4050b0",
        "candidate": {"path": str(V19.relative_to(ROOT)), "sha256": sha256(V19), "status": "REVERSIBLE_NOT_PROMOTED"},
        "motion_authority": {"path": str(AUTHORITY.relative_to(ROOT)), "sha256": sha256(AUTHORITY)},
        "mapping": {"insert_at_seconds": INSERT_AT, "insert_duration_seconds": INSERT_DURATION},
        "windows": windows,
        "review_reel": {"path": str(REEL.relative_to(ROOT)), "sha256": sha256(REEL), "duration_seconds": expected_duration, "fps": 24, "frames": expected_frames, "fullscreen": True},
        "representative_contact_sheet": {"path": str(CONTACT.relative_to(ROOT)), "sha256": sha256(CONTACT), "scope_limit": "STATIC_FRAMING_IDENTITY_ONLY_NOT_REALTIME_COMFORT"},
        "probe": {"path": str(PROBE.relative_to(ROOT)), "sha256": sha256(PROBE)},
        "decode_log": {"path": str(DECODE_LOG.relative_to(ROOT)), "sha256": sha256(DECODE_LOG), "error_lines": 0},
        "render_log": {"path": str(RENDER_LOG.relative_to(ROOT)), "sha256": sha256(RENDER_LOG)},
        "purpose": "Fullscreen native-speed audiovisual review media for the worst V18C motion clusters mapped into V19; not a promotion clearance by itself.",
        "authority_summary": {
            "full_runtime_pairs": authority["sampling"]["pair_count"],
            "reliable_pairs": authority["aggregate"]["reliable_pair_count"],
            "excess_translation_p95_px_at_180x320": authority["aggregate"]["excess_translation_px_at_180x320"]["p95"],
        },
        "gates": {
            "media_integrity": "PASS",
            "native_speed": "PASS_24FPS",
            "continuous_full_runtime_human_watch": "NOT_COMPLETE",
            "promotion": "NOT_GRANTED",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "manifest": str(MANIFEST.relative_to(ROOT)), "manifest_sha256": sha256(MANIFEST),
        "reel": str(REEL.relative_to(ROOT)), "reel_sha256": sha256(REEL),
        "contact": str(CONTACT.relative_to(ROOT)), "contact_sha256": sha256(CONTACT),
        "duration": expected_duration, "frames": expected_frames,
    }))


if __name__ == "__main__":
    main()
