#!/usr/bin/env python3
"""Materially changed U29C head-motion source that survives editorial cadence.

This wrapper deliberately reuses the V58 SHA-pinned compositor and replaces
only the head articulation representation after the recorded V59/V60 cadence
failures.  It has no network or provider capability.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import render_e40_u29c_v58_articulated_head as base


FAILURE_MEMORY_SHA256 = "b61d387c622353f121ddbde6b80008313621b2d7c0402082cc6b3b0c31dceabf"
SPEC_SHA256 = "25cbce864d9e477c09ca7c116dad719b00ac94384a66ac1317efc0595e540d8f"
ORIGINAL_SPLIT = base.split_layer


def split_layer(layer, which: str):
    body, head, metadata = ORIGINAL_SPLIT(layer, which)
    degrees = 10.0 if which == "jiaotu" else 7.0
    sign = -1.0 if which == "jiaotu" else 1.0
    metadata["nominal_shear"] = sign * math.tan(math.radians(degrees))
    metadata["equivalent_degrees"] = degrees
    return body, head, metadata


def smooth_track(seconds: float, points: tuple[tuple[float, float], ...]) -> float:
    if seconds <= points[0][0]:
        return points[0][1]
    for (left_t, left_v), (right_t, right_v) in zip(points, points[1:]):
        if seconds <= right_t:
            ratio = (seconds - left_t) / (right_t - left_t)
            eased = ratio * ratio * (3.0 - 2.0 * ratio)
            return left_v + (right_v - left_v) * eased
    return points[-1][1]


def articulation_amplitudes(seconds: float) -> tuple[float, float]:
    # Different irregular extrema and timings avoid a loop or mirrored motion.
    jiaotu = smooth_track(seconds, (
        (0.00, 0.00), (0.22, 0.33), (0.51, 0.74), (0.79, 0.96),
        (1.03, 0.61), (1.27, 1.00), (1.54, 0.52), (1.78, 0.87),
        (2.06, 0.43), (2.29, 0.79), (2.57, 0.36), (2.83, 0.71),
        (3.11, 0.30), (3.34, 0.65), (3.62, 0.25), (3.81, 0.58),
        (4.00, 0.39),
    ))
    yunyang = smooth_track(seconds, (
        (0.00, 0.00), (0.17, 0.24), (0.43, 0.55), (0.68, 0.83),
        (0.92, 1.00), (1.19, 0.57), (1.48, 0.91), (1.71, 0.44),
        (1.98, 0.81), (2.24, 0.34), (2.52, 0.73), (2.77, 0.29),
        (3.04, 0.67), (3.31, 0.23), (3.55, 0.61), (3.76, 0.31),
        (4.00, 0.52),
    ))
    return jiaotu, yunyang


def main() -> int:
    args = base.parser().parse_args()
    base.EXPECTED["failure_memory"] = FAILURE_MEMORY_SHA256
    base.EXPECTED["spec"] = SPEC_SHA256
    base.split_layer = split_layer
    base.articulation_amplitudes = articulation_amplitudes
    report = base.render(args)
    articulation = report["articulation"]
    passed = (
        report["frame0_raw_rgb_exact"]
        and report["audio_stream_count"] == 0
        and 9.8 <= articulation["jiaotu_peak_equivalent_degrees"] <= 10.1
        and 6.8 <= articulation["yunyang_peak_equivalent_degrees"] <= 7.1
        and articulation["opposite_signed_shears"]
        and articulation["body_layers_fixed"]
    )
    report.update({
        "schema": "qingshan.e40.u29c.v61.editorial_survival_head_render_report.v1",
        "status": "PASS_RENDER_PENDING_SOURCE_AND_EDITORIAL_SURVIVAL_QA" if passed else "FAIL_CLOSED",
        "predecessor_failure_memory_sha256": FAILURE_MEMORY_SHA256,
        "material_change": "10/7-degree smooth nonperiodic tracks with no hold longer than 0.29 seconds",
    })
    base.atomic_json(args.report, report)
    print(json.dumps({"status": report["status"], "output": report["output"], "sha256": report["output_sha256"]}))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
