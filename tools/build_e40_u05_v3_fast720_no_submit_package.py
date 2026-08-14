#!/usr/bin/env python3
"""Build the fail-closed U05 V3 Fast720 native-dialogue precheck package."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u05_v3_fast720_admitted_frame_v1"
PROMPT = BASE / "E40_U05_V3_FAST720_NATIVE_EXACT_LINE_PROMPT_V1.txt"
MANIFEST = BASE / "E40_U05_V3_FAST720_NO_SUBMIT_MANIFEST_V1.json"
GATE = ROOT / "qa/e40_preproduction_20260814/u05_v3_fast720_no_submit_package_v1/E40_U05_V3_FAST720_STATIC_GATE_V1.json"
FRAME = ROOT / "working_assets/e40_preproduction_20260814/u05_v2_imagegen_coherent_exact_start_frame_v1/E40_U05_V2_IMAGEGEN_COHERENT_EXACT_START_FRAME_720X1280_V1.png"
FRAME_ADMISSION = ROOT / "workflow/releases/E40_U05_V2_EXACT_START_FRAME_ADMISSION_20260814.json"
HUMAN_QA = ROOT / "qa/e40_preproduction_20260814/u05_v2_imagegen_coherent_exact_start_frame_v1/E40_U05_V2_EXACT_START_FRAME_HUMAN_QA_V1.json"
OCR_QA = ROOT / "qa/e40_preproduction_20260814/u05_v2_imagegen_coherent_exact_start_frame_v1/E40_U05_V2_EXACT_START_FRAME_OCR_AUDIT_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANON = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
CANON_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
FRAME_SHA = "4f5205fa8a001b1943a322ee146ec19f4a62c530a9b1286bf921e327c2dbcc7e"
LINE = "先请教娘娘——扣他，为何不杀？"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def raw_rgb_sha(path: Path) -> tuple[str, int, int]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        digest = hashlib.sha256(struct.pack(">QQ", width, height) + rgb.tobytes()).hexdigest()
    return digest, width, height


def main() -> int:
    admission = json.loads(FRAME_ADMISSION.read_text(encoding="utf-8"))
    human = json.loads(HUMAN_QA.read_text(encoding="utf-8"))
    ocr = json.loads(OCR_QA.read_text(encoding="utf-8"))
    text = PROMPT.read_text(encoding="utf-8")
    checks = {
        "canonical_script_sha": sha256(SCRIPT) == SCRIPT_SHA,
        "canonical_manifest_sha": sha256(CANON) == CANON_SHA,
        "admitted_frame_sha": sha256(FRAME) == FRAME_SHA,
        "frame_admission_pass": admission.get("status") == "PASS_U05_EXACT_START_FRAME_ADMITTED_FOR_VIDEO_AND_EXACT_AUDIO_PATH",
        "human_qa_pass_80": human.get("status") == "PASS_ADMIT_EXACT_START_FRAME" and int(human.get("human_score", 0)) >= 80,
        "ocr_qa_pass": ocr.get("status") == "PASS" and int(ocr.get("critical_text_failures", -1)) == 0,
        "model_fast_only": "seedance-2.0-fast" in text and "禁止 seedance-2.0-pro" in text and "seedance-2.0-mini" in text and "裸 seedance-2.0" in text,
        "native_720p": "720p" in text,
        "duration_four_seconds": "4秒" in text,
        "exact_dialogue_present_once_or_more": LINE in text,
        "owner_count_transfer_lock": "count=2" in text and "离案半寸" in text and "人物所有权不变" in text,
        "no_generated_text": "不得生成任何可辨文字" in text and "字幕" in text and "水印" in text,
    }
    if not all(checks.values()):
        raise SystemExit("FAIL_CLOSED_STATIC_GATE:" + json.dumps(checks, ensure_ascii=False))
    raw, width, height = raw_rgb_sha(FRAME)
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    atomic_json(GATE, {
        "schema": "qingshan.e40.u05.v3.fast720_static_gate.v1",
        "status": "PASS", "recorded_at": created, "checks": checks,
        "model": "seedance-2.0-fast", "resolution": "720p", "duration_seconds": 4,
        "exact_start_frame_sha256": FRAME_SHA, "prompt_sha256": sha256(PROMPT),
        "visible_dialogue": LINE, "dialogue_transport": "MODEL_NATIVE_EXACT_LINE_FROM_IMAGE_TO_VIDEO_PROMPT",
        "provider_posts": 0, "provider_queries": 0, "transactions": 0, "credits": 0,
        "maximum_new_submissions": 0,
    })
    task = {
        "task_key": "E40-U05-V3-FAST720-ADMITTED-FRAME-NATIVE-EXACT-DIA004-V1",
        "unit_id": "U05", "scene_id": "13-1", "kind": "visible_native_dialogue_action_unit",
        "action_unit": True, "combat_or_chase": False,
        "model": "seedance-2.0-fast", "resolution": "720p", "aspect_ratio": "9:16",
        "duration_seconds": 4, "generating_count": 1,
        "prompt_file": rel(PROMPT), "prompt_sha256": sha256(PROMPT),
        "material_change_from": "E40-U05-FAST720-PRECOMPILED-NULL-FRAME-V1",
        "material_change": "admitted coherent exact frame replaces null source; compact six-second exact-line performance contract is bound to the exact frame and current fast-only policy",
        "reference_images": [rel(FRAME)], "reference_sha256": [FRAME_SHA],
        "reference_roles": ["EXACT_FIRST_FRAME"], "exact_first_frame_sha256": FRAME_SHA,
        "video_transport": {"mode": "image_to_video_start_frame", "endpoint": "/api/v1/generation/image-to-video", "start_frame_path": rel(FRAME), "start_frame_sha256": FRAME_SHA, "ordinary_images": []},
        "frame0_authority_contract": {"source_sha256": FRAME_SHA, "pre_encode_raw_rgb_sha256_required": True, "raw_rgb_sha256": raw, "width": width, "height": height, "semantic_start_frame_human_score": int(human["human_score"])},
        "post_harvest_exact_frame_gate": {"required": True, "single_frame_prepend_allowed": False, "single_frame_replacement_allowed": False, "frame0_thresholds": {"minimum_ssim": 0.98, "maximum_mae": 3.0, "maximum_phash_hamming": 3}, "frame0_to_frame1_continuity_required": True, "frame0_to_frame1_static_freeze_forbidden": True},
        "performance_tempo_contract": {
            "playback_speed": "REAL_TIME_1X", "first_visible_displacement_by_seconds": 0.20,
            "primary_action_complete_by_seconds": 0.8, "result_hold_seconds": 0.0,
            "maximum_atomic_window_seconds": 1.2, "maximum_action_gap_seconds": 0.0,
            "slow_motion_interpolation_post_speedup_forbidden": True,
            "atomic_action_windows": [
                {"start_seconds": 0.0, "end_seconds": 0.3, "action": "two page edges descend while gaze locks curtain", "state_change": "air gap visibly narrows"},
                {"start_seconds": 0.3, "end_seconds": 0.8, "action": "first then second page contacts table", "state_change": "primary placement completes with exactly two pages"},
                {"start_seconds": 0.8, "end_seconds": 1.0, "action": "right palm settles and Chenji inhales to speak", "state_change": "native dialogue onset begins"},
                {"start_seconds": 1.0, "end_seconds": 2.1, "action": "Chenji speaks exact first phrase", "state_change": "visible lips and source syllables synchronize"},
                {"start_seconds": 2.1, "end_seconds": 3.35, "action": "Chenji completes exact question", "state_change": "dialogue finishes once without additions"},
                {"start_seconds": 3.35, "end_seconds": 4.0, "action": "Chenji closes mouth while breath sleeve curtain and candle continue", "state_change": "active reaction tail continues through cut"},
            ],
        },
        "identity_owner_count_contract": {"visible_entities": ["陈迹", "陈迹右手", "恰好两页空白账页", "长帘"], "actor_count": 1, "hand_count": 1, "page_count": 2, "page_owner": "陈迹", "page_transfer": "HAND_TO_TABLE_PLACEMENT_ONLY_OWNERSHIP_UNCHANGED", "second_visible_face_allowed": False, "second_speaker_allowed": False},
        "native_dialogue_required": True, "dialogue_lines": [LINE],
        "dialogue_transport": "MODEL_NATIVE_EXACT_LINE_FROM_IMAGE_TO_VIDEO_PROMPT",
        "reference_audio_asset_ids": [], "exact_dialogue_audio_asset_ids": [],
        "source_subtitle_policy": "POST_HARVEST_OCR_HARD_FAIL_NO_BURNED_TEXT",
        "video_audio_contract": {"provider_native_audio_required": True, "exact_asr_similarity_required": 1.0, "visible_lip_sync_required": True, "single_speaker_required": "陈迹", "audio_replacement_as_admission_fix_allowed": False},
        "submission_authorization": {"precheck_only": True, "authorized": False, "paid_submission_allowed": False, "transaction_creation_allowed": False, "maximum_new_submissions": 0},
    }
    atomic_json(MANIFEST, {
        "schema": "qingshan.e40.u05.v3.fast720_no_submit_manifest.v1",
        "episode": "E40", "recorded_at": created,
        "status": "READY_LOCAL_PRECHECK_ONLY_NO_PAID_AUTHORIZATION", "provider": "giggle",
        "allowed_video_models": ["seedance-2.0-fast"],
        "forbidden_video_models": ["seedance-2.0-pro", "seedance-2.0-mini", "seedance-2.0"],
        "canonical": {"script_path": rel(SCRIPT), "script_sha256": SCRIPT_SHA, "manifest_path": rel(CANON), "manifest_sha256": CANON_SHA},
        "source_frame_admission": rel(FRAME_ADMISSION), "source_frame_admission_sha256": sha256(FRAME_ADMISSION),
        "source_frame_human_qa": rel(HUMAN_QA), "source_frame_human_qa_sha256": sha256(HUMAN_QA),
        "source_frame_ocr_qa": rel(OCR_QA), "source_frame_ocr_qa_sha256": sha256(OCR_QA),
        "machine_gate_reports": [rel(GATE)], "tasks": [task],
        "submission_policy": {"precheck_only": True, "paid_submission_allowed": False, "provider_post_allowed": False, "durable_transaction_allowed": False, "maximum_new_submissions": 0, "same_round_retry_forbidden": True},
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "blocked_by": "ZERO_COST_PAID_READINESS_AND_NATIVE_DIALOGUE_TRANSPORT_NOT_YET_CERTIFIED",
        "next_action": "Run deployed submitter with --precheck-only. If it passes, separately certify current price, collision, native-audio capability and durable exactly-once transaction readiness before any provider POST.",
    })
    print(json.dumps({"status": "PASS", "prompt_sha256": sha256(PROMPT), "gate_sha256": sha256(GATE), "manifest_sha256": sha256(MANIFEST), "raw_rgb_sha256": raw}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
