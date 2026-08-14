#!/usr/bin/env python3
"""Build five contiguous native-speed V23 review packages and objective QA."""

from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = Path("/Users/rogerwu/Documents/Codex/2026-07-17/referenced-chatgpt-conversation-this-is-untrusted/agentcut-0.9.7/agentcut/vendor/darwin-arm64/ffmpeg")
FFPROBE = FFMPEG.with_name("ffprobe")
SOURCE = ROOT / "working_assets/e36_agentcut_20260801/accepted_only_v23_canonical_dialogue_order/E36_ACCEPTED_ONLY_AGENTCUT_V23_CANONICAL_DIALOGUE_ORDER.mp4"
SOURCE_SHA = "89af22464112ec0be2da1fdd8897fd35f46d37cb40c19342422dcd76bb118a83"
OUT_DIR = ROOT / "working_assets/e36_agentcut_20260801/v23_bounded_watch_packages_v1"
QA_DIR = ROOT / "qa/e36_agentcut_20260730/v23_bounded_watch_packages_v1"
QA = ROOT / "qa/e36_agentcut_20260730/E36_V23_BOUNDED_NATIVE_SPEED_REVIEW_PACKAGES_QA_V1.json"
WINDOWS = [(0.0, 60.0), (60.0, 120.0), (120.0, 180.0), (180.0, 240.0), (240.0, 293.942646)]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def probe(path: Path) -> dict:
    return json.loads(subprocess.check_output([
        str(FFPROBE), "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,duration,avg_frame_rate,nb_frames,sample_rate,channels",
        "-of", "json", str(path),
    ], text=True))


def build_window(index: int, start: float, end: float) -> dict:
    label = f"{int(start):03d}"
    reel = OUT_DIR / f"E36_V23_WATCH_{label}_REVIEW_REEL_V1.mp4"
    contact = QA_DIR / f"E36_V23_WATCH_{label}_CONTACT_SHEET_V1.jpg"
    decode_log = QA_DIR / f"E36_V23_WATCH_{label}_FULL_DECODE.log"
    ffprobe_path = QA_DIR / f"E36_V23_WATCH_{label}_FFPROBE.json"
    duration = end - start
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(SOURCE),
        "-ss", f"{start:.6f}", "-t", f"{duration:.6f}",
        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "18", "-pix_fmt", "yuv420p", "-r", "24", "-fps_mode", "cfr",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(reel),
    ], check=True)
    details = probe(reel)
    ffprobe_path.write_text(json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with decode_log.open("w", encoding="utf-8") as handle:
        subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-i", str(reel), "-f", "null", "-"], stdout=handle, stderr=handle, check=True)
    expected_samples = 20 if index < 4 else 18
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(reel),
        "-vf", f"fps=1/3,scale=180:-1,tile=5x4:nb_frames={expected_samples}:padding=2:margin=2",
        "-frames:v", "1", str(contact),
    ], check=True)
    streams = {row["codec_type"]: row for row in details["streams"]}
    return {
        "source_window_seconds": [start, end],
        "reel": rel(reel),
        "reel_sha256": sha256(reel),
        "duration_seconds": float(details["format"]["duration"]),
        "fps": streams["video"]["avg_frame_rate"],
        "frames": int(streams["video"]["nb_frames"]),
        "video_duration_seconds": float(streams["video"]["duration"]),
        "audio_duration_seconds": float(streams["audio"]["duration"]),
        "audio_sample_rate": int(streams["audio"]["sample_rate"]),
        "audio_channels": int(streams["audio"]["channels"]),
        "contact_sheet": rel(contact),
        "contact_sheet_sha256": sha256(contact),
        "ordered_visual_samples": expected_samples,
        "ffprobe": rel(ffprobe_path),
        "ffprobe_sha256": sha256(ffprobe_path),
        "decode_log": rel(decode_log),
        "decode_log_sha256": sha256(decode_log),
        "full_decode": "PASS_ZERO_ERRORS" if decode_log.stat().st_size == 0 else "FAIL",
    }


def main() -> None:
    if sha256(SOURCE) != SOURCE_SHA:
        raise RuntimeError("V23 source changed")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = list(pool.map(lambda args: build_window(*args), [(i, *window) for i, window in enumerate(WINDOWS)]))
    overview = QA_DIR / "E36_V23_FULL_RUNTIME_98_SAMPLE_OVERVIEW_V1.jpg"
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(SOURCE),
        "-vf", "fps=1/3,scale=144:-1,tile=10x10:nb_frames=98:padding=2:margin=2",
        "-frames:v", "1", str(overview),
    ], check=True)
    total_frames = sum(row["frames"] for row in rows)
    all_decode = all(row["full_decode"] == "PASS_ZERO_ERRORS" for row in rows)
    payload = {
        "schema": "qingshan.e36.v23_bounded_native_speed_review_packages_qa.v1",
        "episode": "E36",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_cl2x": "CL2X-924",
        "source_mailbox_sha256": "1421e83dd9e802c1a16eaf57df6c757f761d227c6578e85891b35ddb1834e8f7",
        "canonical_script": "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md",
        "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
        "manifest": "workflow/claude_writer_agent/scripts/E36_manifest_v2.json",
        "manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
        "candidate": rel(SOURCE),
        "candidate_sha256": SOURCE_SHA,
        "status": "PASS_FIVE_CONTIGUOUS_NATIVE_SPEED_REVIEW_PACKAGES_FULL_UNINTERRUPTED_WATCH_NOT_COMPLETE" if all_decode and total_frames == 7053 else "FAIL",
        "review_packages": rows,
        "coverage_integrity": {
            "source_windows_contiguous": all(left[1] == right[0] for left, right in zip(WINDOWS, WINDOWS[1:])),
            "source_windows_overlap_seconds": 0.0,
            "source_windows_gap_seconds": 0.0,
            "package_video_frames_sum": total_frames,
            "candidate_video_frames": 7053,
            "video_frame_coverage": f"PASS_{total_frames}_OF_7053" if total_frames == 7053 else "FAIL",
        },
        "direct_visual_review": {
            "overview": rel(overview),
            "overview_sha256": sha256(overview),
            "sampling": "READY_98_ORDERED_REPRESENTATIVE_SAMPLES_ACROSS_FULL_RUNTIME",
            "scope_limit": "Contact sheets and bounded reels prepare continuous review but do not prove full native-speed audiovisual comfort, lip sync, breath, expression, dialogue timing, identity continuity, or causal continuity.",
        },
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "bounded_review_media": "PASS_5_OF_5_CONTIGUOUS_PACKAGES" if all_decode else "FAIL",
            "video_frame_coverage": f"PASS_{total_frames}_OF_7053" if total_frames == 7053 else "FAIL",
            "bounded_media_full_decode": "PASS_5_OF_5_ZERO_ERRORS" if all_decode else "FAIL",
            "ordered_direct_visual_samples": "READY_98_NOT_YET_ADJUDICATED",
            "continuous_full_runtime_human_watch": "NOT_COMPLETE",
            "transcript": "HOLD_39_OF_47",
            "motion": "PASS_30_OF_30",
            "V23_promotion": "NOT_GRANTED_KEEP_V15_CANONICAL",
            "release": "HOLD",
        },
        "blocked_by": "PROMOTION_ONLY:V23_CONTINUOUS_AUDIOVISUAL_WATCH_INCOMPLETE;RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED",
        "workaround_executed": "Rendered V23 into five contiguous native-speed audiovisual review packages concurrently, full-decoded all packages, verified exact7053-frame video coverage, and generated98 ordered visual samples for the next direct review pass.",
        "credits": {"pay_this_action": 0, "refund_this_action": 0, "net_this_action": 0, "episode_source_net": 9976, "episode_cap": 10000, "refunds_separate": 3084, "headroom": 24, "calls": 135, "active": 0},
        "next_action": "Directly inspect the98-sample V23 overview and use all five bounded native-speed reels for uninterrupted audiovisual review; concurrently continue materially distinct zero-credit source-native recovery for lines4/5/11/12/23/24/27/28.",
    }
    QA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if payload["status"] == "FAIL":
        raise RuntimeError(json.dumps(payload["coverage_integrity"], ensure_ascii=False))
    print(json.dumps({"status": payload["status"], "qa": rel(QA), "qa_sha256": sha256(QA), "frames": total_frames}, ensure_ascii=False))


if __name__ == "__main__":
    main()
