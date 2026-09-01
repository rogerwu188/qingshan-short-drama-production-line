#!/usr/bin/env python3
"""Objective post-generation motion-energy gate for no-cut combat impulses."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "qingshan.media_motion_energy_gate.v2_precontact_baseline_advisory_uncalibrated"


def evaluate_energy_series(
    values: Iterable[float], *, unit_class: str, no_cut: bool,
    source_id: str, previous_ratio: float | None = None,
    calibrated_fail_floor: float | None = None,
) -> dict[str, Any]:
    samples = [float(value) for value in values if float(value) >= 0]
    applicable = unit_class == "COMBAT_IMPULSE" and no_cut
    if not applicable:
        return {
            "schema": SCHEMA, "status": "NOT_APPLICABLE", "source_id": source_id,
            "unit_class": unit_class, "no_cut": no_cut, "failures": [],
        }
    failures: list[str] = []
    warnings: list[str] = []
    if len(samples) < 3:
        failures.append("MOTION_ENERGY_SAMPLE_COUNT_INSUFFICIENT")
        baseline_median = peak = ratio = 0.0
    else:
        baseline_count = max(3, int(len(samples) * 0.25))
        baseline = sorted(samples[:baseline_count])
        middle = len(baseline) // 2
        baseline_median = baseline[middle] if len(baseline) % 2 else (baseline[middle - 1] + baseline[middle]) / 2
        peak = max(samples)
        ratio = peak / max(baseline_median, 1e-6)
        if calibrated_fail_floor is None:
            warnings.append(
                f"MOTION_ENERGY_ABSOLUTE_THRESHOLD_ADVISORY_UNCALIBRATED:{ratio:.3f}"
            )
        elif ratio < float(calibrated_fail_floor):
            failures.append(
                f"MOTION_ENERGY_PRECONTACT_BASELINE_TOO_LOW:{ratio:.3f}<{float(calibrated_fail_floor):.3f}"
            )
        if previous_ratio is not None and ratio < float(previous_ratio) * 1.8:
            failures.append(
                f"MOTION_ENERGY_AB_IMPROVEMENT_TOO_LOW:{ratio:.3f}<{float(previous_ratio) * 1.8:.3f}"
            )
    return {
        "schema": SCHEMA,
        "status": "FAIL" if failures else ("ADVISORY" if warnings else "PASS"),
        "source_id": source_id,
        "unit_class": unit_class,
        "no_cut": no_cut,
        "sample_count": len(samples),
        "precontact_baseline_median_energy": round(baseline_median, 6),
        "peak_frame_difference_energy": round(peak, 6),
        "peak_precontact_baseline_ratio": round(ratio, 6),
        "previous_ratio": previous_ratio,
        "calibrated_fail_floor": calibrated_fail_floor,
        "absolute_threshold_mode": "ADVISORY_UNTIL_6_DIRECTOR_ACCEPTED_SAMPLES" if calibrated_fail_floor is None else "CALIBRATED_BLOCKING",
        "retry_policy": (
            "REDESIGN_PROMPT_NEW_SHA_NO_SAME_PROMPT_TWEAK_RETRY" if failures else "NONE"
        ),
        "warnings": warnings,
        "failures": failures,
    }


def video_energy_series(path: Path) -> list[float]:
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise RuntimeError("opencv-python is required for media energy inspection") from exc
    capture = cv2.VideoCapture(str(path))
    previous = None
    values: list[float] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (180, 320), interpolation=cv2.INTER_AREA)
        if previous is not None:
            values.append(float(cv2.absdiff(gray, previous).mean()))
        previous = gray
    capture.release()
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--unit-class", default="COMBAT_IMPULSE")
    parser.add_argument("--contains-cut", action="store_true")
    parser.add_argument("--previous-ratio", type=float)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = evaluate_energy_series(
        video_energy_series(args.video), unit_class=args.unit_class,
        no_cut=not args.contains_cut, source_id=args.source_id,
        previous_ratio=args.previous_ratio,
    )
    report["media_path"] = str(args.video)
    report["media_sha256"] = hashlib.sha256(args.video.read_bytes()).hexdigest()
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    raise SystemExit(0 if report["status"] in {"PASS", "ADVISORY", "NOT_APPLICABLE"} else 1)


if __name__ == "__main__":
    main()
