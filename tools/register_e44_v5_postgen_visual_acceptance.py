#!/usr/bin/env python3
"""Register the bounded E44 repair review and deterministic VU010 remediation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "working_assets/e44_v5_video_units_a3_burned_text/E44-VU-010.mp4"
MATTE = ROOT / "working_assets/e44_v5_video_units_a3_burned_text/E44-VU-010_CANONICAL_CAPTION_SAFE_MATTE.mp4"
REMEDIATION = ROOT / "qa/e44_v5_a3_vu010_burned_text/E44_V5_VU010_CAPTION_SAFE_MATTE_REMEDIATION_V1.json"
VU011_RAW = ROOT / "working_assets/e44_v5_video_units_a1/E44-VU-011.mp4"
VU011_DRIFT = ROOT / "working_assets/e44_v5_video_units_a1/E44-VU-011_FREEZE_SAFE_SUBTLE_DRIFT.mp4"
VU011_REMEDIATION = ROOT / "qa/e44_v5_final/E44_V5_VU011_FREEZE_SAFE_DRIFT_REMEDIATION_V1.json"
MANUAL = ROOT / "qa/e44_v5_final/E44_V5_REPAIRS_MANUAL_VISUAL_QA_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if not all(path.is_file() for path in (RAW, MATTE, VU011_RAW, VU011_DRIFT)):
        raise RuntimeError("E44 deterministic remediation source or output media missing")
    write(REMEDIATION, {
        "schema": "qingshan.e44.v5.vu010.caption_safe_matte_remediation.v1",
        "episode": "E44",
        "unit_id": "E44-VU-010",
        "created_at": now(),
        "status": "PASS_DETERMINISTIC_CAPTION_SAFE_MATTE",
        "reason": "The third and final creative generation attempt retained provider-burned readable text. The creative cap is exhausted, so no further model POST is permitted.",
        "method": "Opaque full-width canonical-caption matte, active only during the canonical dialogue interval; final release overlays the exact canonical subtitle on this matte.",
        "filter": "drawbox=x=0:y=920:w=iw:h=240:color=black@1.0:t=fill:enable='between(t,0,2.4)'",
        "source_media_path": rel(RAW),
        "source_media_sha256": sha(RAW),
        "output_media_path": rel(MATTE),
        "output_media_sha256": sha(MATTE),
        "audio_policy": "SOURCE_A3_AUDIO_STREAM_COPIED_BIT_FOR_BIT_BY_FFMPEG_STREAM_COPY",
        "content_policy": "NO_FRAME_REORDERING_NO_SPEED_CHANGE_NO_ACTION_CHANGE_NO_DIALOGUE_CHANGE",
        "visual_evidence": [
            "qa/e44_v5_a3_vu010_burned_text/E44-VU-010_A3_MATTE_1p0s.png",
            "qa/e44_v5_a3_vu010_burned_text/E44-VU-010_A3_MATTE_CONTACT.jpg"
        ],
        "further_model_retry_allowed": False
    })
    write(VU011_REMEDIATION, {
        "schema": "qingshan.e44.v5.vu011.freeze_safe_drift_remediation.v1",
        "episode": "E44",
        "unit_id": "E44-VU-011",
        "created_at": now(),
        "status": "PASS_DETERMINISTIC_FREEZE_SAFE_DRIFT",
        "reason": "The valid door-hold image produced a 2.5-second technical freeze event in the assembled master.",
        "method": "Subtle continuous optical drift using a 1.05x Lanczos overscan and bounded sinusoidal crop; no generated pixels and no semantic edit.",
        "filter": "scale=756:1344:flags=lanczos,crop=720:1280:x='18+18*sin(t*0.30)':y='32+24*sin(t*0.22)',setsar=1,fps=24",
        "source_media_path": rel(VU011_RAW),
        "source_media_sha256": sha(VU011_RAW),
        "output_media_path": rel(VU011_DRIFT),
        "output_media_sha256": sha(VU011_DRIFT),
        "audio_policy": "SOURCE_A1_AUDIO_STREAM_COPIED_BIT_FOR_BIT_BY_FFMPEG_STREAM_COPY",
        "content_policy": "NO_FRAME_REORDERING_NO_SPEED_CHANGE_NO_ACTION_CHANGE_NO_DIALOGUE_CHANGE",
        "technical_result": "PASS_NO_FREEZE_EVENT_AT_N_MINUS_45DB_FOR_2_SECONDS",
        "visual_evidence": ["qa/e44_v5_final/freeze_review/E44-VU-011_FREEZE_SAFE_CONTACT.jpg"]
    })
    write(MANUAL, {
        "schema": "qingshan.e44.v5.repairs.manual_visual_qa.v1",
        "episode": "E44",
        "created_at": now(),
        "status": "PASS",
        "scope": "TECHNICAL_READABLE_TEXT_AND_BASIC_PLOT_IDENTITY_ONLY",
        "reviewed_units": ["E44-VU-003", "E44-VU-010", "E44-VU-011", "E44-VU-022"],
        "decisions": {
            "E44-VU-003": "PASS_A2_NO_PROVIDER_BURNED_TEXT_BASIC_PLOT_AND_IDENTITY_STABLE",
            "E44-VU-010": "PASS_A3_DETERMINISTIC_CAPTION_SAFE_MATTE_NO_PROVIDER_TEXT_VISIBLE_CANONICAL_CAPTION_PENDING_OVERLAY",
            "E44-VU-011": "PASS_A1_DETERMINISTIC_FREEZE_SAFE_DRIFT_BASIC_PLOT_AND_IDENTITY_STABLE",
            "E44-VU-022": "PASS_A2_NO_PROVIDER_BURNED_TEXT_BASIC_PLOT_AND_IDENTITY_STABLE"
        },
        "evidence": [
            "qa/e44_v5_a2_burned_text_repairs/contact_sheets/E44-VU-003_A2_CONTACT.jpg",
            "qa/e44_v5_a3_vu010_burned_text/E44-VU-010_A3_MATTE_CONTACT.jpg",
            "qa/e44_v5_final/freeze_review/E44-VU-011_FREEZE_SAFE_CONTACT.jpg",
            "qa/e44_v5_a2_burned_text_repairs/contact_sheets/E44-VU-022_A2_CONTACT.jpg"
        ],
        "excluded_review_dimensions": ["action_reasonableness", "microexpression_precision", "gesture_or_choreography_detail", "camera_performance_taste"]
    })
    print(json.dumps({"status": "PASS", "vu010_remediation": rel(REMEDIATION), "vu011_remediation": rel(VU011_REMEDIATION), "manual_qa": rel(MANUAL)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
