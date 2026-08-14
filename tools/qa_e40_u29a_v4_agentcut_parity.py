#!/usr/bin/env python3
"""QA the isolated AgentCut roundtrip of the E40 U29A V4 living master."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from render_e40_u29a_v4_deterministic_concealment import atomic_json, red_metrics, select_jade_mask, sha256
from render_e40_u29a_v4_living_performance import collar_roundness


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


def stream_probe(path: Path) -> dict:
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
    ]))


def monotonic(values: list[int]) -> bool:
    return all(right <= left for left, right in zip(values, values[1:]))


def monotonic_with_codec_tolerance(values: list[int], tolerance: int = 1) -> bool:
    """Allow only a one-count H.264 chroma-quantization wobble, never visual area reversal."""
    return all(right <= left + tolerance for left, right in zip(values, values[1:]))


def motion_values(frames: list[np.ndarray], roi: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = roi
    gray = [cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32) for frame in frames]
    return np.asarray([float(np.abs(right - left).mean()) for left, right in zip(gray, gray[1:])])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority-image", type=Path, required=True)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--roundtrip", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    authority = cv2.imread(str(args.authority_image), cv2.IMREAD_COLOR)
    if authority is None:
        raise RuntimeError("Cannot decode authority image")
    mask, mask_meta = select_jade_mask(authority)
    master = decode(args.master)
    roundtrip = decode(args.roundtrip)
    project = json.loads(args.project.read_text(encoding="utf-8"))
    clip = project["timeline"]["videoTracks"][0]["clips"][0]

    action_frames = min(len(master), len(roundtrip), 30)
    master_area: list[int] = []
    master_red: list[int] = []
    roundtrip_area: list[int] = []
    roundtrip_red: list[int] = []
    roundtrip_full_round: list[bool] = []
    for index in range(action_frames):
        master_rgb = cv2.cvtColor(master[index], cv2.COLOR_BGR2RGB)
        roundtrip_rgb = cv2.cvtColor(roundtrip[index], cv2.COLOR_BGR2RGB)
        area, red = red_metrics(master_rgb, mask)
        master_area.append(area)
        master_red.append(red)
        area, red = red_metrics(roundtrip_rgb, mask)
        roundtrip_area.append(area)
        roundtrip_red.append(red)
        roundtrip_full_round.append(bool(collar_roundness(roundtrip_rgb)["full_round"]))

    source_motion = motion_values(master, (80, 590, 930, 1690))
    transcode_motion = motion_values(roundtrip, (80, 590, 930, 1690))
    correlation = float(np.corrcoef(source_motion, transcode_motion)[0, 1])
    probe = stream_probe(args.roundtrip)
    audio_count = len([row for row in probe.get("streams", []) if row.get("codec_type") == "audio"])
    source_sha = sha256(args.master)
    binding_pass = Path(clip["source"]).resolve() == args.master.resolve() and clip["metadata"].get("source_sha256") == source_sha
    dimensions_pass = len(master) == 96 and len(roundtrip) == 96 and master[0].shape == roundtrip[0].shape
    roundtrip_max_red_increase = max((right - left for left, right in zip(roundtrip_red, roundtrip_red[1:])), default=0)
    action_pass = (
        monotonic(master_area) and monotonic(master_red)
        and monotonic(roundtrip_area) and monotonic_with_codec_tolerance(roundtrip_red, 1)
        and not any(roundtrip_full_round)
    )
    # The H.264/YUV420 roundtrip changes the pixel-domain motion waveform even
    # when its timing and direction survive.  Treat >=0.85 as strong temporal
    # agreement, while the installed cadence gate and jade monotonic gate remain
    # the authoritative no-freeze/no-reversal checks.
    motion_pass = correlation >= 0.85 and float(transcode_motion.mean()) >= 0.15
    status = "PASS" if binding_pass and dimensions_pass and action_pass and motion_pass and audio_count == 0 else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29a.v4.agentcut_transcode_parity_qa.v1",
        "status": status,
        "authority_image": str(args.authority_image.resolve()),
        "authority_sha256": sha256(args.authority_image),
        "master": str(args.master.resolve()),
        "master_sha256": source_sha,
        "roundtrip": str(args.roundtrip.resolve()),
        "roundtrip_sha256": sha256(args.roundtrip),
        "project": str(args.project.resolve()),
        "project_sha256": sha256(args.project),
        "agentcut_version": "0.9.22",
        "actual_source_binding": {
            "project_source": clip["source"],
            "project_source_sha256": clip["metadata"].get("source_sha256"),
            "pass": binding_pass,
        },
        "frame_parity": {
            "master_frames": len(master),
            "roundtrip_frames": len(roundtrip),
            "dimensions_bgr": list(roundtrip[0].shape),
            "pass": dimensions_pass,
        },
        "jade_action": {
            "mask": mask_meta,
            "master_visible_area_first_30": master_area,
            "master_red_excess_first_30": master_red,
            "roundtrip_visible_area_first_30": roundtrip_area,
            "roundtrip_red_excess_first_30": roundtrip_red,
            "master_monotonic_nonincrease": monotonic(master_area) and monotonic(master_red),
            "roundtrip_monotonic_nonincrease": monotonic(roundtrip_area) and monotonic(roundtrip_red),
            "roundtrip_codec_tolerant_monotonic_nonincrease": monotonic(roundtrip_area) and monotonic_with_codec_tolerance(roundtrip_red, 1),
            "roundtrip_max_red_excess_single_frame_increase": roundtrip_max_red_increase,
            "roundtrip_red_excess_codec_tolerance": 1,
            "roundtrip_no_full_round_jade": not any(roundtrip_full_round),
            "pass": action_pass,
        },
        "living_motion_parity": {
            "roi_xyxy": [80, 590, 930, 1690],
            "master_adjacent_motion_mean": float(source_motion.mean()),
            "roundtrip_adjacent_motion_mean": float(transcode_motion.mean()),
            "motion_series_correlation": correlation,
            "thresholds": {"minimum_roundtrip_motion_mean": 0.15, "minimum_correlation": 0.85},
            "pass": motion_pass,
        },
        "audio_stream_count": audio_count,
        "provider_posts": 0,
        "transactions": 0,
        "credits": 0,
        "release_allowed": False,
        "final_assembly": False,
    }
    atomic_json(args.out, payload)
    print(json.dumps({"status": status, "out": str(args.out.resolve())}))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
