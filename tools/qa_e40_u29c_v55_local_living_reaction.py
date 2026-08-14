#!/usr/bin/env python3
"""Machine-QA the E40 U29C V55 local living-reaction candidate."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from render_e40_u29c_v55_local_living_reaction import atomic_json, build_masks, sha256


def decode(path: Path) -> list[np.ndarray]:
    capture = cv2.VideoCapture(str(path))
    frames: list[np.ndarray] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames:
        raise RuntimeError(f"No decoded frames: {path}")
    return frames


def mask_motion(frames: list[np.ndarray], mask: np.ndarray) -> dict[str, float | int]:
    support = mask > 0.025
    gray = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) for frame in frames]
    source = gray[0]
    from_source = [float(np.abs(frame[support] - source[support]).mean()) for frame in gray]
    adjacent = [float(np.abs(right[support] - left[support]).mean()) for left, right in zip(gray, gray[1:])]
    return {
        "support_pixels": int(np.count_nonzero(support)),
        "max_mean_abs_change_from_frame0": max(from_source),
        "mean_adjacent_abs_change": float(np.mean(adjacent)),
        "active_adjacent_pair_count_ge_0_02": int(np.count_nonzero(np.asarray(adjacent) >= 0.02)),
    }


def contact_sheet(frames: list[np.ndarray], output: Path) -> None:
    indices = [0, 12, 24, 36, 48, 60, 72, 84]
    thumbs = [cv2.resize(frames[index], (252, 448), interpolation=cv2.INTER_AREA) for index in indices]
    full = np.vstack([np.hstack(thumbs[:4]), np.hstack(thumbs[4:])])
    # Magnified face evidence preserves subtle eye-layer visibility without
    # adding labels or rendered text to the production frames themselves.
    crops = []
    for index in indices[:4]:
        jiaotu = cv2.resize(frames[index][790:910, 175:295], (252, 252), interpolation=cv2.INTER_NEAREST)
        yunyang = cv2.resize(frames[index][810:900, 700:790], (252, 252), interpolation=cv2.INTER_NEAREST)
        crops.extend([jiaotu, yunyang])
    faces = np.hstack(crops)
    if faces.shape[1] != full.shape[1]:
        faces = cv2.resize(faces, (full.shape[1], faces.shape[0]), interpolation=cv2.INTER_AREA)
    sheet = np.vstack([full, faces])
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), sheet, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
        raise RuntimeError("Could not write contact sheet")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--jiaotu-layer", type=Path, required=True)
    parser.add_argument("--yunyang-layer", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--render-report", type=Path, required=True)
    parser.add_argument("--ocr-audit", type=Path, required=True)
    parser.add_argument("--determinism-video", type=Path, required=True)
    parser.add_argument("--contact-sheet", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    source = cv2.imread(str(args.source), cv2.IMREAD_COLOR)
    if source is None:
        raise RuntimeError("Cannot decode source")
    frames = decode(args.video)
    height, width = source.shape[:2]
    masks = build_masks(height, width, args.jiaotu_layer, args.yunyang_layer)
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(args.video),
    ]))
    video_streams = [row for row in probe.get("streams", []) if row.get("codec_type") == "video"]
    audio_count = len([row for row in probe.get("streams", []) if row.get("codec_type") == "audio"])
    outside = masks["allowed"] == 0.0
    outside_changed = [int(np.count_nonzero(np.any(frame != source, axis=2) & outside)) for frame in frames]
    frame0_exact = bool(np.array_equal(frames[0], source))
    geometry_pass = len(frames) == 96 and all(frame.shape == source.shape for frame in frames)
    cadence_pass = bool(video_streams) and video_streams[0].get("r_frame_rate") == "24/1"
    motion = {
        key: mask_motion(frames, masks[key])
        for key in ("jiaotu_eyes", "yunyang_eyes", "jiaotu_garment", "yunyang_garment")
    }
    motion_pass = all(
        item["max_mean_abs_change_from_frame0"] >= threshold
        and item["active_adjacent_pair_count_ge_0_02"] >= 24
        for item, threshold in zip(motion.values(), (0.75, 0.60, 0.45, 0.40))
    )
    render_report = json.loads(args.render_report.read_text(encoding="utf-8"))
    ocr_audit = json.loads(args.ocr_audit.read_text(encoding="utf-8"))
    binding_pass = (
        render_report.get("status") == "PASS"
        and render_report.get("output_sha256") == sha256(args.video)
        and render_report.get("source_sha256") == sha256(args.source)
    )
    ocr_pass = (
        ocr_audit.get("status") == "PASS"
        and Path(ocr_audit.get("source_final_mp4", "")).resolve() == args.video.resolve()
    )
    determinism_sha = sha256(args.determinism_video)
    determinism_pass = determinism_sha == sha256(args.video)
    status = "PASS_MACHINE_QA_PENDING_HUMAN_QA" if (
        frame0_exact
        and geometry_pass
        and cadence_pass
        and audio_count == 0
        and max(outside_changed) == 0
        and motion_pass
        and binding_pass
        and ocr_pass
        and determinism_pass
    ) else "FAIL_CLOSED"
    contact_sheet(frames, args.contact_sheet)
    payload = {
        "schema": "qingshan.e40.u29c.v55.local_living_reaction_machine_qa.v1",
        "status": status,
        "source": str(args.source.resolve()),
        "source_sha256": sha256(args.source),
        "video": str(args.video.resolve()),
        "video_sha256": sha256(args.video),
        "render_report": str(args.render_report.resolve()),
        "render_report_sha256": sha256(args.render_report),
        "contact_sheet": str(args.contact_sheet.resolve()),
        "contact_sheet_sha256": sha256(args.contact_sheet),
        "frame0_raw_bgr_exact": frame0_exact,
        "frame_count": len(frames),
        "dimensions_bgr": list(frames[0].shape),
        "frame_geometry_pass": geometry_pass,
        "r_frame_rate": video_streams[0].get("r_frame_rate") if video_streams else None,
        "cadence_24fps_pass": cadence_pass,
        "audio_stream_count": audio_count,
        "max_changed_pixels_outside_explicit_support": max(outside_changed),
        "background_anatomy_anchor_exact": max(outside_changed) == 0,
        "motion": motion,
        "motion_pass": motion_pass,
        "render_binding_pass": binding_pass,
        "ocr_audit": str(args.ocr_audit.resolve()),
        "ocr_audit_sha256": sha256(args.ocr_audit),
        "ocr_gate": "PASS_SOURCE_FULL_DURATION_OCR0" if ocr_pass else "FAIL_CLOSED",
        "ocr_pass": ocr_pass,
        "determinism_rerun": str(args.determinism_video.resolve()),
        "determinism_rerun_sha256": determinism_sha,
        "deterministic_byte_exact_rerender": determinism_pass,
        "human_qa": "PENDING_ORIGINAL_RESOLUTION_REVIEW_SCORE_GE_80",
        "editorial_admission": False,
        "provider_posts": 0,
        "provider_queries": 0,
        "transactions": 0,
        "credits": 0,
        "retries": 0,
    }
    atomic_json(args.out, payload)
    print(json.dumps({"status": status, "out": str(args.out.resolve())}))
    return 0 if status.startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
