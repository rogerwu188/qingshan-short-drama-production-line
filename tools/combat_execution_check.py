#!/usr/bin/env python3
"""combat_execution — post-generation fight execution measurement (Roger 2026-11-07, authorised narrow scope).

E15 VU-020 passed every prompt gate and still rendered one spark followed by ~4.5 s of the two fighters standing
side by side facing the lens.  Whole-frame motion (YAVG) cannot see that: snow, fire and sparks keep it high.
This measures the PEOPLE: 17 body keypoints per fighter (RTMO, Apache-2.0, onnxruntime only — no torch, no AGPL
weights) sampled at 8 fps.

Scope (Roger approved 2026-11-07, deliberately narrow):
  * runs ONLY on COMBAT units (combat_or_chase / fight_or_chase / action_classification == COMBAT);
  * measures ONE thing: the longest window in which every detected fighter's keypoints move
    < STILL_SPEED body-heights/s ("still");
  * a FAIL is COMBAT_TABLEAU: the unit goes back to the writer for redesign; it is never an automatic reroll.

Calibration (E15 real clips, 2026-11-07): passing fights 0.12-0.25 s longest still window; VU-020 1.12 s;
the original side-by-side pose 1.5 s.  Threshold 1.0 s.  Regression fixtures: tools/tests/test_combat_execution_check.py.
Facing the lens is NOT measured here: on full-body 9:16 frames the faces are too small for RTMO's face
keypoints (frontal share 0.00-0.13 on the known side-by-side pose), so FD5 at S1, the start-frame review and
major_event_presence keep that condition.
If the pose backend is not installed the result is NOT_MEASURED (never PASS) and the plot review decides.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

CHECK_NAME = "combat_execution"
SAMPLE_FPS = 8.0
STILL_SPEED = 0.12          # body heights per second
STILL_SECONDS_MAX = 1.0
MIN_PERSON_HEIGHT = 0.25    # share of frame height; smaller figures are background
KEYPOINT_CONF = 0.5
RTMO_MODEL = ("https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/"
              "rtmo-s_8xb32-600e_body7-640x640-dac2bf74_20231211.zip")


def _people(keypoints, scores, frame_height: float) -> list[dict[str, Any]]:
    import numpy as np
    out = []
    for k, s in zip(keypoints, scores):
        good = s > KEYPOINT_CONF
        if good.sum() < 5:
            continue
        ys = k[good][:, 1]
        height = float(ys.max() - ys.min())
        if height < frame_height * MIN_PERSON_HEIGHT:
            continue
        out.append({"k": k, "s": s, "h": height, "cx": float(np.median(k[good][:, 0]))})
    return sorted(out, key=lambda p: p["cx"])


def summarise(frames: list[list[dict[str, Any]]], sample_fps: float = SAMPLE_FPS) -> dict[str, Any]:
    """Pure function over per-frame people (testable without a model)."""
    import numpy as np
    dt = 1.0 / sample_fps
    still_flags = []
    for a, b in zip(frames, frames[1:]):
        speeds = []
        for pa, pb in zip(a, b):
            ok = (pa["s"] > KEYPOINT_CONF) & (pb["s"] > KEYPOINT_CONF)
            if ok.sum() >= 5:
                speeds.append(float(np.linalg.norm(pa["k"][ok] - pb["k"][ok], axis=1).mean()) / pa["h"] / dt)
        still = bool(speeds) and max(speeds) < STILL_SPEED
        still_flags.append(still)

    def longest(flags: Iterable[bool]) -> float:
        best = run = 0
        for flag in flags:
            run = run + 1 if flag else 0
            best = max(best, run)
        return round(best * dt, 2)

    return {"sampled_frames": len(frames), "fighter_frames": sum(1 for f in frames if f),
            "longest_still_seconds": longest(still_flags)}


def verdict(summary: dict[str, Any]) -> dict[str, Any]:
    still = float(summary.get("longest_still_seconds") or 0.0)
    reasons = ["COMBAT_TABLEAU_STILL"] if still > STILL_SECONDS_MAX else []
    return {"check": CHECK_NAME, "status": "FAIL" if reasons else "PASS", "reasons": reasons,
            "threshold_seconds": STILL_SECONDS_MAX, "still_speed_body_heights_per_s": STILL_SPEED,
            "on_fail": "REDESIGN_UNIT_NOT_REROLL", **summary}


def measure(video: str | Path, *, sample_fps: float = SAMPLE_FPS) -> dict[str, Any]:
    try:
        import cv2
        from rtmlib import RTMO
    except ModuleNotFoundError as exc:
        return {"check": CHECK_NAME, "status": "NOT_MEASURED", "reason": f"POSE_BACKEND_MISSING:{exc.name}",
                "on_fail": "PLOT_REVIEW_DECIDES"}
    model = RTMO(RTMO_MODEL, backend="onnxruntime", device="cpu")
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    step = max(1, round(fps / sample_fps))
    frames, index = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % step == 0:
            keypoints, scores = model(frame)
            frames.append(_people(keypoints, scores, frame.shape[0]))
        index += 1
    cap.release()
    if not frames:
        return {"check": CHECK_NAME, "status": "NOT_MEASURED", "reason": "NO_FRAMES", "on_fail": "PLOT_REVIEW_DECIDES"}
    return verdict(summarise(frames, fps / step))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("videos", nargs="+")
    args = parser.parse_args(argv)
    worst = 0
    for video in args.videos:
        result = measure(video)
        print(json.dumps({"video": video, **result}, ensure_ascii=False))
        worst = max(worst, 3 if result["status"] == "FAIL" else 0)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
