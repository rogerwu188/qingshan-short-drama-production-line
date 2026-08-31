#!/usr/bin/env python3
"""Finalize the directly reviewed E48 VU011 official-Ref2VA probe."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e48_v5_h3_a4_official_ref2va"
POSTGEN = QA / "E48_V5_H3_A4_VU011_PROBE_POSTGEN_QA_V2.json"
CONTACT = QA / "vu011_probe_frames/contact_sheet.jpg"
END_FRAME = QA / "vu011_probe_frames/end_6p1.jpg"
VIDEO = ROOT / "working_assets/e48_v5_h3_video_units_a4_official_ref2va_probe/E48-VU-011-VIDEO-H3-A4-OFFICIAL-REF2VA.mp4"
OUT = QA / "E48_V5_H3_A4_VU011_PROBE_FINAL_QA_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def main() -> int:
    postgen = json.loads(POSTGEN.read_text(encoding="utf-8"))
    if postgen.get("status") != "PASS" or postgen.get("unit_count") != 1:
        raise RuntimeError("VU011 machine post-generation QA is not PASS")
    row = postgen["rows"][0]
    native = row["native_dialogue"]
    if native.get("best_conditioned_recall") != 1.0:
        raise RuntimeError("VU011 canonical dialogue was not recovered exactly")
    if not native.get("conditioned_exact_and_boundary_safe"):
        raise RuntimeError("VU011 final spoken word is not boundary-safe")
    for path in (CONTACT, END_FRAME, VIDEO):
        if not path.is_file():
            raise RuntimeError(f"missing probe evidence: {path}")
    report = {
        "schema": "qingshan.e48.v5.h3_a4.official_ref2va_probe_final_qa.v1",
        "episode": "E48",
        "unit_id": "E48-VU-011",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS",
        "video": rel(VIDEO),
        "video_sha256": sha(VIDEO),
        "machine_postgen_qa": rel(POSTGEN),
        "machine_postgen_qa_sha256": sha(POSTGEN),
        "direct_review": {
            "method": "Full-duration 2fps contact sheet plus exact late-frame review at 6.1 seconds.",
            "contact_sheet": rel(CONTACT),
            "contact_sheet_sha256": sha(CONTACT),
            "late_frame": rel(END_FRAME),
            "late_frame_sha256": sha(END_FRAME),
            "identity_and_role_binding": "PASS_TWO_REFERENCED_RIDERS_REMAIN_DISTINCT_AND_DO_NOT_SWAP",
            "wardrobe_and_mount_continuity": "PASS",
            "street_map_weather_lighting_and_axis": "PASS",
            "burned_text_subtitle_ui_logo_watermark": "PASS_ZERO_VISIBLE_READABLE_TEXT",
            "basic_plot": "PASS_TWO_RIDERS_CONTINUE_THROUGH_RAIN_AND_EXCHANGE_ONLY_THE_TWO_AUTHORIZED_LINES",
            "action_detail_or_taste_review": "EXCLUDED_BY_POSTGEN_QA_POLICY",
        },
        "native_dialogue": {
            "expected": ["景朝的头，藏在京城。", "谁见过他。"],
            "unconditioned_asr_note": "The proper noun 景朝 was once decoded as the homophone 警察.",
            "conditioned_dual_vad_exact_recall": 1.0,
            "last_word_end_seconds": 6.36,
            "decoded_duration_seconds": row["technical"]["duration_seconds"],
            "boundary_margin_seconds": round(row["technical"]["duration_seconds"] - 6.36, 6),
            "prompt_meta_or_extra_speech": "NONE_DETECTED",
        },
        "release_decision": "PASS_PROBE; REMAINING_FOUR_MAY_BE_AUTHORIZED_AFTER_THEIR_ZERO_COST_PRECHECK",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "out": rel(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
