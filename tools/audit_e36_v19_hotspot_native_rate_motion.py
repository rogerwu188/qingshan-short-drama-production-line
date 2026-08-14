#!/usr/bin/env python3
"""Audit mapped V18C/V19 hotspot motion at every 24 fps review frame."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from audit_e36_v18c_interframe_motion_attribution import affine_motion, percentile, reversal_ratio


ROOT = Path(__file__).resolve().parents[1]
REEL = ROOT / "qa/e36_agentcut_20260730/v19_mapped_high_motion_realtime_reel_v1/E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_REALTIME_REEL_V1.mp4"
MANIFEST = ROOT / "qa/e36_agentcut_20260730/v19_mapped_high_motion_realtime_reel_v1/E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_MANIFEST_V1.json"
OUTPUT = ROOT / "qa/e36_agentcut_20260730/E36_V19_HOTSPOT_NATIVE_24FPS_MOTION_ATTRIBUTION_V1.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cap = cv2.VideoCapture(str(REEL))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        left = cv2.resize(cv2.cvtColor(frame[58:, :360], cv2.COLOR_BGR2GRAY), (180, 320), interpolation=cv2.INTER_AREA)
        right = cv2.resize(cv2.cvtColor(frame[58:, 360:], cv2.COLOR_BGR2GRAY), (180, 320), interpolation=cv2.INTER_AREA)
        frames.append((left, right))
    cap.release()
    # OpenCV reports the container average (24.0313) for this exact 768-frame,
    # 32-second reel; the authoritative stream rate is 24/1 in ffprobe.
    if len(frames) != 768:
        raise SystemExit(f"unexpected reel geometry fps={fps} frames={len(frames)}")
    orb = cv2.ORB_create(nfeatures=800, scaleFactor=1.2, nlevels=8, fastThreshold=10)
    records = []
    per_window = []
    for window in range(8):
        start = window * 96
        window_records = []
        for local in range(1, 96):
            index = start + local
            source = affine_motion(frames[index - 1][0], frames[index][0], orb)
            candidate = affine_motion(frames[index - 1][1], frames[index][1], orb)
            record = {
                "window": window + 1,
                "local_frame": local,
                "local_time_seconds": local / 24.0,
                "source": source,
                "candidate": candidate,
            }
            if source.get("reliable") and candidate.get("reliable"):
                dx = candidate["dx"] - source["dx"]
                dy = candidate["dy"] - source["dy"]
                record["excess"] = {"dx": dx, "dy": dy, "translation": math.hypot(dx, dy)}
            records.append(record)
            window_records.append(record)
        reliable = [r for r in window_records if "excess" in r]
        translations = [r["excess"]["translation"] for r in reliable]
        vectors = [(r["excess"]["dx"], r["excess"]["dy"]) for r in reliable]
        reversals, valid, ratio = reversal_ratio(vectors)
        per_window.append({
            "window": window + 1,
            "base_center_seconds": manifest["windows"][window]["base_center_seconds"],
            "v19_center_seconds": manifest["windows"][window]["v19_center_seconds"],
            "pair_count": 95,
            "reliable_pair_count": len(reliable),
            "reliable_pair_ratio": len(reliable) / 95,
            "excess_translation_px_at_180x320": {
                "p50": percentile(translations, 0.50),
                "p95": percentile(translations, 0.95),
                "max": max(translations, default=0.0),
            },
            "direction_reversal": {"count": reversals, "valid_pair_count": valid, "ratio": ratio},
        })
    reliable = [r for r in records if "excess" in r]
    translations = [r["excess"]["translation"] for r in reliable]
    vectors = [(r["excess"]["dx"], r["excess"]["dy"]) for r in reliable]
    reversals, valid, ratio = reversal_ratio(vectors)
    report = {
        "schema": "e36_v19_hotspot_native_24fps_motion_attribution_v1",
        "source_cl2x": "CL2X-913",
        "source_mailbox_sha256": "6e4678c691873227857cbbe804617d64930b1df18e79d1039174e11ddb6b4632",
        "review_reel": {"path": str(REEL.relative_to(ROOT)), "sha256": sha256(REEL)},
        "mapping_manifest": {"path": str(MANIFEST.relative_to(ROOT)), "sha256": sha256(MANIFEST)},
        "sampling": {"fps": 24, "interval_seconds": 1 / 24, "windows": 8, "seconds_per_window": 4, "frame_count": 768, "pair_count_excluding_segment_boundaries": 760},
        "aggregate": {
            "reliable_pair_count": len(reliable),
            "reliable_pair_ratio": len(reliable) / 760,
            "excess_translation_px_at_180x320": {
                "p50": percentile(translations, 0.50),
                "p90": percentile(translations, 0.90),
                "p95": percentile(translations, 0.95),
                "p99": percentile(translations, 0.99),
                "max": max(translations, default=0.0),
            },
            "direction_reversal": {"count": reversals, "valid_pair_count": valid, "ratio": ratio},
        },
        "per_window": per_window,
        "method": {
            "paired_layout": "V18C base left and time-mapped V19 right",
            "frame_interval": "every rendered frame at 24fps; this avoids the 0.25-second contact-sheet aliasing identified by CL2X-913",
            "feature": "ORB_800_RANSAC_partial_affine",
            "attribution": "V19 interframe translation minus mapped V18C interframe translation after identical review sizing",
            "limitations": "The paired review reel is re-encoded, so small residuals include codec noise and transform estimation error. This objective audit cannot replace uninterrupted subjective comfort review.",
        },
        "gate_results": {
            "native_rate_sampling": "PASS_24FPS_760_WITHIN_WINDOW_PAIRS",
            "reliable_motion_attribution": "PASS" if len(reliable) / 760 >= 0.70 else "FAIL_LOW_RELIABLE_RATIO",
            "quarter_second_contact_aliasing": "BYPASSED_WITH_1_OVER_24_SECOND_SAMPLING",
            "continuous_realtime_human_comfort_watch": "NOT_COMPLETE",
            "promotion": "NOT_GRANTED",
        },
        "records": records,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "sha256": sha256(OUTPUT), "reliable": len(reliable), "pairs": 760, "p95": report["aggregate"]["excess_translation_px_at_180x320"]["p95"]}))


if __name__ == "__main__":
    main()
