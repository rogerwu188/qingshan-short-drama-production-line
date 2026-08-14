#!/usr/bin/env python3
"""Zero-video precheck and closed-set negative tests for the V57 renderer."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path

import cv2
import numpy as np

from render_e40_u29c_v55_local_living_reaction import atomic_json, sha256
from render_e40_u29c_v58_articulated_head import articulation_amplitudes, make_frame, prepare


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--clean-hall", type=Path, required=True)
    parser.add_argument("--jiaotu-layer", type=Path, required=True)
    parser.add_argument("--yunyang-layer", type=Path, required=True)
    parser.add_argument("--failure-memory", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    # prepare() is intentionally exercised without writing any frame or video.
    prepared = prepare(args)
    sample_indices = [0, 12, 20, 29, 36, 43, 60, 84, 95]
    frames = []
    metadata = []
    for index in sample_indices:
        frame, row = make_frame(prepared, index, 24)
        frames.append(frame)
        metadata.append(row)
    source = prepared["source"]
    frame0_exact = bool(np.array_equal(frames[0], source))
    peak_jiaotu = max(row["jiaotu_equivalent_degrees"] for row in metadata)
    peak_yunyang = max(row["yunyang_equivalent_degrees"] for row in metadata)
    amplitudes = [articulation_amplitudes(index / 24.0) for index in sample_indices]
    distinct_tracks = any(abs(left - right) >= 0.08 for left, right in amplitudes[2:])
    opposite_signed = prepared["jiaotu_meta"]["nominal_shear"] * prepared["yunyang_meta"]["nominal_shear"] < 0

    # Spatial differences must remain above the shoulders; the lower body and
    # feet are bit exact in every sampled frame.
    lower_body_rois = {
        "jiaotu": (58, 1120, 374, 1747),
        "yunyang": (617, 1080, 870, 1516),
    }
    lower_body_max_changed = {}
    for key, (x0, y0, x1, y1) in lower_body_rois.items():
        lower_body_max_changed[key] = max(
            int(np.count_nonzero(np.any(frame[y0:y1, x0:x1] != source[y0:y1, x0:x1], axis=2)))
            for frame in frames
        )
    lower_body_exact = max(lower_body_max_changed.values()) == 0

    # Neck seams are anchored below each pivot; a narrow band below the head
    # split must remain unchanged.
    neck_rois = {
        "jiaotu": (180, 980, 285, 1005),
        "yunyang": (700, 980, 785, 1005),
    }
    neck_max_changed = {}
    for key, (x0, y0, x1, y1) in neck_rois.items():
        neck_max_changed[key] = max(
            int(np.count_nonzero(np.any(frame[y0:y1, x0:x1] != source[y0:y1, x0:x1], axis=2)))
            for frame in frames
        )
    neck_anchor_pass = max(neck_max_changed.values()) == 0

    negative_tests = {
        "same_signed_mirrored_turn_rejected": opposite_signed,
        "identical_motion_tracks_rejected": distinct_tracks,
        "missing_failure_memory_rejected_by_exact_sha_contract": sha256(args.failure_memory) != sha256(args.spec),
        "old_v55_renderer_reuse_rejected": sha256(Path(__file__).resolve().parent / "render_e40_u29c_v55_local_living_reaction.py") != sha256(Path(__file__).resolve().parent / "render_e40_u29c_v58_articulated_head.py"),
        "body_or_foot_motion_rejected": lower_body_exact,
    }
    passed = (
        frame0_exact
        and prepared["exact_recomposition_mae"] <= 0.55
        and 2.9 <= peak_jiaotu <= 3.1
        and 1.9 <= peak_yunyang <= 2.1
        and distinct_tracks
        and opposite_signed
        and lower_body_exact
        and neck_anchor_pass
        and all(negative_tests.values())
    )
    payload = {
        "schema": "qingshan.e40.u29c.v57.articulated_head_renderer_zero_video_precheck.v1",
        "status": "PASS_ZERO_VIDEO_PRECHECK_RENDER_V58_MAY_BE_REGISTERED" if passed else "FAIL_CLOSED",
        "renderer": str((Path(__file__).resolve().parent / "render_e40_u29c_v58_articulated_head.py")),
        "renderer_sha256": sha256(Path(__file__).resolve().parent / "render_e40_u29c_v58_articulated_head.py"),
        "failure_memory_sha256": sha256(args.failure_memory),
        "spec_sha256": sha256(args.spec),
        "sample_indices_in_memory_only": sample_indices,
        "frame0_exact": frame0_exact,
        "exact_recomposition_mae_bgr": prepared["exact_recomposition_mae"],
        "jiaotu_peak_equivalent_degrees": peak_jiaotu,
        "yunyang_peak_equivalent_degrees": peak_yunyang,
        "opposite_signed_turns": opposite_signed,
        "distinct_tracks": distinct_tracks,
        "lower_body_max_changed_pixels": lower_body_max_changed,
        "lower_body_and_feet_exact": lower_body_exact,
        "neck_band_max_changed_pixels": neck_max_changed,
        "neck_anchor_pass": neck_anchor_pass,
        "negative_tests": negative_tests,
        "negative_pass_count": sum(negative_tests.values()),
        "negative_total": len(negative_tests),
        "video_files_written": 0,
        "frame_files_written": 0,
        "provider_posts": 0,
        "provider_queries": 0,
        "transactions": 0,
        "credits": 0,
        "render_v58_authorized": passed,
    }
    atomic_json(args.out, payload)
    print(json.dumps({"status": payload["status"], "out": str(args.out.resolve())}))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
