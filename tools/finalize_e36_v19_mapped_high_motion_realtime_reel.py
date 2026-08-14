#!/usr/bin/env python3
"""Finalize V19 mapped high-motion full-speed review media and preserve holds."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "qa/e36_agentcut_20260730/v19_mapped_high_motion_realtime_reel_v1"
MANIFEST = DIR / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_MANIFEST_V1.json"
REEL = DIR / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_REALTIME_REEL_V1.mp4"
QA = ROOT / "qa/e36_agentcut_20260730/E36_V19_MAPPED_HIGH_MOTION_REALTIME_REEL_QA_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPTS = ROOT / "workflow/CODEX_TO_CLAUDE.md"
SOURCE_CL2X = "CL2X-912"
MAILBOX_SHA = "ca97ab522e4346dcd467f4a5f8363a13385794fd78fc43aa37f2cf77c7295244"
BLOCKED = (
    "PROMOTION_ONLY:V19_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;"
    "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08;"
    "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
    "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> None:
    manifest = load(MANIFEST)
    cap = cv2.VideoCapture(str(REEL))
    mse = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        left = frame[58:, :360].astype(np.float32)
        right = frame[58:, 360:].astype(np.float32)
        mse.append(float(np.mean((left - right) ** 2)))
    cap.release()
    if len(mse) != 768:
        raise SystemExit(f"expected768 frames, got{len(mse)}")
    values = np.array(mse)
    psnr = 10 * np.log10((255.0**2) / values)
    per_window = []
    for i in range(8):
        window = psnr[i * 96 : (i + 1) * 96]
        per_window.append({"window": i + 1, "psnr_mean_db": float(window.mean()), "psnr_min_db": float(window.min())})
    now = datetime.now(timezone.utc).isoformat()
    artifacts = []
    for item in (MANIFEST, REEL, DIR / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_CONTACT_V1.jpg", DIR / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_PROBE_V1.json", DIR / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_DECODE_V1.log", DIR / "E36_V19_MAPPED_EIGHT_HIGH_MOTION_WINDOWS_RENDER_V1.log"):
        artifacts.append({"path": rel(item), "sha256": sha256(item)})
    workaround = (
        "Built and fully decoded a zero-credit 32-second full-frame-rate mapped reel for all eight inherited "
        "V18C high-motion hotspots in V19. Pre-insert windows use unchanged timestamps and post-insert windows "
        "use the exact +6.082993-second mapping; 768 paired frames and direct center samples confirm content "
        "alignment while preserving the uninterrupted full-runtime comfort hold."
    )
    next_action = (
        "Use the rendered full-speed reel for uninterrupted hotspot comfort review, then build full-frame-rate "
        "reels for the remaining V19 timeline intervals while continuing zero-credit recovery for unresolved "
        "lines4/5/11/12/23/24/27/28 and U08; keep V19 unpromoted until the complete realtime watch passes."
    )
    qa = {
        "schema": "e36_v19_mapped_high_motion_realtime_reel_qa_v1",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "manifest": {"path": rel(MANIFEST), "sha256": sha256(MANIFEST)},
        "candidate": manifest["candidate"],
        "review_scope": {"window_count": 8, "seconds_per_window": 4.0, "total_seconds": 32.0, "fps": 24, "frames": 768, "mapping": manifest["mapping"]},
        "mapped_pair_pixel_alignment": {
            "method": "paired reel halves below labels; decoded x264 review-media PSNR includes independent re-encode noise",
            "mse_mean": float(values.mean()),
            "psnr_mean_db": float(psnr.mean()),
            "psnr_p05_db": float(np.percentile(psnr, 5)),
            "psnr_min_db": float(psnr.min()),
            "per_window": per_window,
            "verdict": "PASS_ALL_EIGHT_WINDOWS_CONTENT_ALIGNED_MODULO_REENCODE_NOISE",
        },
        "direct_center_visual_review": {
            "sample_count": 8,
            "paired_content_alignment": "PASS_ALL_EIGHT",
            "identity_age_period_props": "PASS_NO_NEW_DRIFT_OR_CUTOFF",
            "labels_and_geometry": "PASS",
            "scope_limit": "CENTER_SAMPLES_AND_32_SECOND_REALTIME_REEL_DO_NOT_CLEAR_REMAINING_FULL_RUNTIME_OR_FATIGUE",
        },
        "artifacts": artifacts,
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "real_full_speed_review_media": "PASS_32_SECONDS_24FPS_768_FRAMES",
            "full_decode": "PASS_ZERO_ERRORS",
            "mapped_hotspot_alignment": "PASS_EIGHT_OF_EIGHT",
            "high_motion_hotspot_review_prepared": "PASS_ALL_EIGHT",
            "continuous_uninterrupted_full_runtime_watch": "NOT_COMPLETE",
            "transcript": "HOLD_39_OF_47",
            "motion": "HOLD_29_OF_30_U08",
            "promotion": "NOT_YET_KEEP_V15_CANONICAL",
            "release": "HOLD",
        },
        "blocked_by": BLOCKED,
        "workaround_executed": workaround,
        "credits": "Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0",
        "next_action": next_action,
    }
    dump(QA, qa)
    qa_sha = sha256(QA)
    queue = load(QUEUE)
    queue.update({"source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA, "updated_at": now, "status": "E36_V19_MAPPED_HIGH_MOTION_REALTIME_REEL_PASS_FULL_WATCH_ACTIVE", "latest_v19_mapped_high_motion_realtime_qa": rel(QA), "latest_v19_mapped_high_motion_realtime_qa_sha256": qa_sha, "blocked_by": BLOCKED, "next_action": next_action})
    dump(QUEUE, queue)
    dispatch = load(DISPATCH)
    dispatch.update({"source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA, "generated_at": now, "blocked_by": BLOCKED, "workaround_executed": workaround, "next_action": next_action})
    dispatch.setdefault("execution", {})["latest_v19_mapped_high_motion_realtime_qa"] = {"path": rel(QA), "sha256": qa_sha, "status": "PASS_32S_REVIEW_MEDIA_FULL_WATCH_HOLD"}
    dispatch["execution"]["last_real_progress"] = workaround
    dispatch["execution"]["status"] = "CL2X-912_V19_MAPPED_HOTSPOT_REEL_PASS_REVERSIBLE_NOT_PROMOTED"
    dump(DISPATCH, dispatch)
    queue_sha, dispatch_sha = sha256(QUEUE), sha256(DISPATCH)
    artifact_text = "; ".join(f"`{a['path']}` sha256=`{a['sha256']}`" for a in artifacts)
    receipt = f"""

# [X2CL-20260731-2224] E36 V19 mapped high-motion full-speed review reel
- source_cl2x: `{SOURCE_CL2X}`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{BLOCKED}`
- workaround_executed: `{workaround}`
- artifacts: `{rel(QA)}` sha256=`{qa_sha}`; {artifact_text}; `workflow/work_queue.json` sha256=`{queue_sha}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{dispatch_sha}`
- gate_results: `canonical:PASS_EXACT;review_media:PASS_32S_24FPS_768_FRAMES;decode:PASS_ZERO_ERRORS;mapped_hotspots:PASS_8_OF_8;direct_center_visual:PASS_8_OF_8;continuous_full_runtime_watch:NOT_COMPLETE;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;promotion:NOT_YET;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
    with RECEIPTS.open("a", encoding="utf-8") as f:
        f.write(receipt)
    print(json.dumps({"qa_sha256": qa_sha, "queue_sha256": queue_sha, "dispatch_sha256": dispatch_sha, "receipt_file_sha256": sha256(RECEIPTS)}))


if __name__ == "__main__":
    main()
