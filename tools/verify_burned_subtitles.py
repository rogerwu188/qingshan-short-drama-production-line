#!/usr/bin/env python3
"""Verify burned subtitles by comparing captioned and raw renders frame by frame."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_frame(capture: cv2.VideoCapture, seconds: float) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"Could not read frame at {seconds:.3f}s")
    return frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--captioned", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    captioned = args.captioned.expanduser().resolve()
    raw = args.raw.expanduser().resolve()
    project_path = args.project.expanduser().resolve()
    project = json.loads(project_path.read_text())
    track = project["timeline"]["subtitleTracks"][0]
    clips = track["clips"]
    bottom_margin = int(track.get("style", {}).get("margins", {}).get("bottom", 170))

    captioned_capture = cv2.VideoCapture(str(captioned))
    raw_capture = cv2.VideoCapture(str(raw))
    if not captioned_capture.isOpened() or not raw_capture.isOpened():
        raise RuntimeError("Could not open one or both videos")

    rows = []
    for clip in clips:
        midpoint = float(clip["start"]) + float(clip["duration"]) / 2.0
        captioned_frame = read_frame(captioned_capture, midpoint)
        raw_frame = read_frame(raw_capture, midpoint)
        height, width = captioned_frame.shape[:2]
        band_bottom = max(1, height - bottom_margin + 36)
        band_top = max(0, band_bottom - 150)
        left = max(0, int(width * 0.08))
        right = min(width, int(width * 0.92))
        caption_band = captioned_frame[band_top:band_bottom, left:right]
        raw_band = raw_frame[band_top:band_bottom, left:right]
        diff = cv2.absdiff(caption_band, raw_band)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        changed_pixels = int(np.count_nonzero(gray >= 32))
        strong_pixels = int(np.count_nonzero(gray >= 64))
        p95 = float(np.percentile(gray, 95))
        # Short captions occupy less than five percent of the band, so p95 is
        # evidence only. Absolute changed/strong pixel counts remain robust.
        passed = changed_pixels >= 180 and strong_pixels >= 50
        rows.append(
            {
                "dialogue_id": clip.get("dialogue_id"),
                "caption_id": clip.get("id"),
                "text": clip.get("text"),
                "midpoint_seconds": round(midpoint, 6),
                "band": {"x": [left, right], "y": [band_top, band_bottom]},
                "changed_pixels_ge_32": changed_pixels,
                "strong_pixels_ge_64": strong_pixels,
                "difference_p95": round(p95, 3),
                "status": "PASS" if passed else "FAIL",
            }
        )

    captioned_capture.release()
    raw_capture.release()
    failures = [row for row in rows if row["status"] != "PASS"]
    expected_ids = project.get("expectedDialogueIds", [])
    actual_ids = [row["dialogue_id"] for row in rows]
    coverage_ok = actual_ids == expected_ids and len(actual_ids) == len(set(actual_ids))
    payload = {
        "schema": "qingshan.subtitle.pixel_diff.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if coverage_ok and not failures else "FAIL",
        "captioned_video": str(captioned),
        "captioned_sha256": sha256(captioned),
        "raw_qa_video": str(raw),
        "raw_sha256": sha256(raw),
        "agentcut_project": str(project_path),
        "coverage": {
            "expected": len(expected_ids),
            "checked": len(rows),
            "passed": len(rows) - len(failures),
            "failed": len(failures),
            "ordered_dialogue_ids_match": coverage_ok,
        },
        "thresholds": {
            "changed_pixels_ge_32": 180,
            "strong_pixels_ge_64": 50,
            "difference_p95": "evidence_only_for_short_caption_compatibility",
        },
        "failures": failures,
        "checks": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": payload["status"], **payload["coverage"], "out": str(args.out)}))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
