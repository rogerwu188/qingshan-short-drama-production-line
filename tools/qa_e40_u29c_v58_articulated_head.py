#!/usr/bin/env python3
"""Machine QA for the local V58 articulated-head candidate."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from render_e40_u29c_v55_local_living_reaction import atomic_json, sha256


def decode(path: Path) -> list[np.ndarray]:
    capture = cv2.VideoCapture(str(path))
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames:
        raise RuntimeError("No decoded frames")
    return frames


def motion(frames: list[np.ndarray], roi: tuple[int, int, int, int]) -> dict:
    x0, y0, x1, y1 = roi
    gray = [cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32) for frame in frames]
    adjacent = np.asarray([float(np.abs(right - left).mean()) for left, right in zip(gray, gray[1:])])
    from_start = np.asarray([float(np.abs(frame - gray[0]).mean()) for frame in gray])
    return {
        "roi_xyxy": list(roi),
        "mean_adjacent_abs_change": float(adjacent.mean()),
        "active_adjacent_pair_count_ge_0_02": int(np.count_nonzero(adjacent >= 0.02)),
        "peak_mean_abs_change_from_frame0": float(from_start.max()),
        "peak_frame_index": int(from_start.argmax()),
    }


def write_contact_sheet(frames: list[np.ndarray], output: Path) -> None:
    indices = [0, 12, 20, 29, 36, 43, 60, 84]
    full = [cv2.resize(frames[index], (252, 448), interpolation=cv2.INTER_AREA) for index in indices]
    top = np.vstack([np.hstack(full[:4]), np.hstack(full[4:])])
    face_rows = []
    for index in indices:
        left = cv2.resize(frames[index][700:990, 125:345], (220, 290), interpolation=cv2.INTER_CUBIC)
        right = cv2.resize(frames[index][750:990, 655:835], (220, 290), interpolation=cv2.INTER_CUBIC)
        face_rows.append(np.hstack([left, right]))
    faces = np.hstack(face_rows[:4])
    faces2 = np.hstack(face_rows[4:])
    faces = cv2.resize(faces, (top.shape[1], 330), interpolation=cv2.INTER_AREA)
    faces2 = cv2.resize(faces2, (top.shape[1], 330), interpolation=cv2.INTER_AREA)
    sheet = np.vstack([top, faces, faces2])
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), sheet, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
        raise RuntimeError("Could not write contact sheet")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--render-report", type=Path, required=True)
    parser.add_argument("--contact-sheet", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = cv2.imread(str(args.source), cv2.IMREAD_COLOR)
    if source is None:
        raise RuntimeError("Cannot decode source")
    frames = decode(args.video)
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(args.video),
    ]))
    video_streams = [item for item in probe.get("streams", []) if item.get("codec_type") == "video"]
    audio_count = len([item for item in probe.get("streams", []) if item.get("codec_type") == "audio"])
    frame0_exact = bool(np.array_equal(frames[0], source))
    geometry_pass = len(frames) == 96 and all(frame.shape == source.shape for frame in frames)
    cadence_pass = bool(video_streams) and video_streams[0].get("r_frame_rate") == "24/1"

    allowed = np.zeros(source.shape[:2], np.uint8)
    allowed[700:990, 120:350] = 1
    allowed[745:990, 650:840] = 1
    outside = allowed == 0
    outside_changed = [int(np.count_nonzero(np.any(frame != source, axis=2) & outside)) for frame in frames]
    lower_body = np.zeros(source.shape[:2], np.uint8)
    lower_body[1005:1747, 58:374] = 1
    lower_body[1005:1516, 617:870] = 1
    lower_changed = [int(np.count_nonzero(np.any(frame != source, axis=2) & (lower_body > 0))) for frame in frames]
    jiaotu_motion = motion(frames, (125, 700, 345, 990))
    yunyang_motion = motion(frames, (655, 745, 835, 990))
    motion_pass = (
        jiaotu_motion["peak_mean_abs_change_from_frame0"] >= 1.0
        and yunyang_motion["peak_mean_abs_change_from_frame0"] >= 0.7
        and jiaotu_motion["active_adjacent_pair_count_ge_0_02"] >= 40
        and yunyang_motion["active_adjacent_pair_count_ge_0_02"] >= 40
    )
    render_report = json.loads(args.render_report.read_text(encoding="utf-8"))
    binding_pass = (
        render_report.get("status") == "PASS_RENDER_PENDING_MACHINE_AND_HUMAN_QA"
        and render_report.get("output_sha256") == sha256(args.video)
        and render_report.get("source_sha256") == sha256(args.source)
    )
    support_pass = max(outside_changed) == 0 and max(lower_changed) == 0
    status = "PASS_MACHINE_QA_PENDING_OCR_AND_HUMAN_QA" if (
        frame0_exact and geometry_pass and cadence_pass and audio_count == 0
        and motion_pass and binding_pass and support_pass
    ) else "FAIL_CLOSED"
    write_contact_sheet(frames, args.contact_sheet)
    payload = {
        "schema": "qingshan.e40.u29c.v58.articulated_head_machine_qa.v1",
        "status": status,
        "source_sha256": sha256(args.source),
        "video": str(args.video.resolve()),
        "video_sha256": sha256(args.video),
        "render_report_sha256": sha256(args.render_report),
        "contact_sheet": str(args.contact_sheet.resolve()),
        "contact_sheet_sha256": sha256(args.contact_sheet),
        "frame0_exact": frame0_exact,
        "frame_count": len(frames),
        "dimensions_bgr": list(frames[0].shape),
        "geometry_pass": geometry_pass,
        "r_frame_rate": video_streams[0].get("r_frame_rate") if video_streams else None,
        "cadence_pass": cadence_pass,
        "audio_stream_count": audio_count,
        "jiaotu_motion": jiaotu_motion,
        "yunyang_motion": yunyang_motion,
        "motion_pass": motion_pass,
        "max_changed_pixels_outside_two_head_envelopes": max(outside_changed),
        "max_changed_lower_body_and_feet_pixels": max(lower_changed),
        "support_and_body_anchor_pass": support_pass,
        "render_binding_pass": binding_pass,
        "ocr": "PENDING_SEPARATE_SOURCE_MODE_AUDIT",
        "human_qa": "PENDING_ORIGINAL_RESOLUTION_FULL_DURATION_REVIEW",
        "editorial_admission": False,
        "provider_posts": 0,
        "provider_queries": 0,
        "transactions": 0,
        "credits": 0,
    }
    atomic_json(args.out, payload)
    print(json.dumps({"status": status, "out": str(args.out.resolve())}))
    return 0 if status.startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
