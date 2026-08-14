#!/usr/bin/env python3
"""Build the fail-closed U04 V3 Fast720 precheck-only package."""

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
BASE = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u04_v3_fast720_coherent_frame_v1"
PROMPT = BASE / "E40_U04_V3_FAST720_SILENT_VISUAL_PROMPT_V1.txt"
MANIFEST = BASE / "E40_U04_V3_FAST720_NO_SUBMIT_MANIFEST_V1.json"
GATE = ROOT / "qa/e40_preproduction_20260814/u04_v3_fast720_no_submit_package_v1/E40_U04_V3_FAST720_STATIC_GATE_V1.json"
FRAME = ROOT / "working_assets/e40_preproduction_20260814/u04_v2_imagegen_coherent_exact_start_frame_v1/E40_U04_V2_IMAGEGEN_COHERENT_EXACT_START_FRAME_720X1280_V1.png"
FRAME_ADMISSION = ROOT / "workflow/releases/E40_U04_V2_EXACT_START_FRAME_ADMISSION_20260814.json"
OLD_FAILURE = ROOT / "qa/e40_preproduction_20260808/E40_U04_EXACT_START_FRAME_CANDIDATE_V1_FINAL_HUMAN_QA.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANON = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
CANON_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
FRAME_SHA = "c7604c76ba3f56e1ccab8a0c400fe3cf039091c37551bdf5259376204ccd853a"


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
    frame_admission = json.loads(FRAME_ADMISSION.read_text(encoding="utf-8"))
    old_failure = json.loads(OLD_FAILURE.read_text(encoding="utf-8"))
    text = PROMPT.read_text(encoding="utf-8")
    checks = {
        "canonical_script_sha": sha256(SCRIPT) == SCRIPT_SHA,
        "canonical_manifest_sha": sha256(CANON) == CANON_SHA,
        "admitted_frame_sha": sha256(FRAME) == FRAME_SHA,
        "frame_admission_pass": frame_admission.get("status") == "PASS_U04_EXACT_START_FRAME_ADMITTED_FOR_VIDEO_GENERATION",
        "old_collage_failure_preserved": "FAIL" in str(old_failure.get("status", "")),
        "model_fast_only": "seedance-2.0-fast" in text and "seedance-2.0-pro" not in text.lower() and "seedance-2.0-mini" not in text.lower(),
        "native_720p": "720p" in text,
        "duration_four_seconds": "4 秒" in text or "四秒" in text,
        "primary_action_complete_by_1p2": "1.20 秒内完成主动作" in text,
        "three_independent_successor_actions": text.count("独立后继动作") == 3,
        "silent_no_mouth": "不生成任何音频" in text and "不出现口型" in text,
        "owner_count_frost_lock": "visible_hand_count=1" in text and "frost_trace_count=1" in text and "frost_transfer=NONE" in text,
        "no_collage_reuse": "拼贴接缝" in text and "人物卡排版" in text,
    }
    if not all(checks.values()):
        raise SystemExit("FAIL_CLOSED_STATIC_GATE:" + json.dumps(checks, ensure_ascii=False))
    raw, width, height = raw_rgb_sha(FRAME)
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    atomic_json(GATE, {
        "schema": "qingshan.e40.u04.v3.fast720_static_gate.v1",
        "status": "PASS", "recorded_at": created, "checks": checks,
        "model": "seedance-2.0-fast", "resolution": "720p", "duration_seconds": 4,
        "primary_action_complete_by_seconds": 1.2, "exact_start_frame_sha256": FRAME_SHA,
        "prompt_sha256": sha256(PROMPT), "provider_posts": 0, "provider_queries": 0,
        "transactions": 0, "credits": 0, "maximum_new_submissions": 0,
    })
    task = {
        "task_key": "E40-U04-V3-FAST720-COHERENT-EXACT-FIRST-FRAME-FROST-RECEDE-SILENT-V1",
        "unit_id": "U04", "scene_id": "13-1", "kind": "silent_visual_reaction_insert",
        "action_unit": True, "combat_or_chase": False,
        "model": "seedance-2.0-fast", "resolution": "720p", "aspect_ratio": "9:16",
        "duration_seconds": 4, "generating_count": 1,
        "prompt_file": rel(PROMPT), "prompt_sha256": sha256(PROMPT),
        "material_change_from": "E40-U04-LOCAL-COLLAGE-CANDIDATE-V1",
        "material_change": "single coherent image-generated frame replaces the rejected multi-source collage; timed frost-recede, finger-flex, gaze-shift and sleeve-recoil actions replace the old null-frame prompt",
        "reference_images": [rel(FRAME)], "reference_sha256": [FRAME_SHA],
        "reference_roles": ["EXACT_FIRST_FRAME"], "exact_first_frame_sha256": FRAME_SHA,
        "video_transport": {"mode": "image_to_video_start_frame", "endpoint": "/api/v1/generation/image-to-video", "start_frame_path": rel(FRAME), "start_frame_sha256": FRAME_SHA, "ordinary_images": []},
        "frame0_authority_contract": {"source_sha256": FRAME_SHA, "pre_encode_raw_rgb_sha256_required": True, "raw_rgb_sha256": raw, "width": width, "height": height, "semantic_start_frame_human_score": 94},
        "post_harvest_exact_frame_gate": {"required": True, "single_frame_prepend_allowed": False, "single_frame_replacement_allowed": False, "frame0_thresholds": {"minimum_ssim": 0.98, "maximum_mae": 3.0, "maximum_phash_hamming": 3}, "frame0_to_frame1_continuity_required": True, "frame0_to_frame1_static_freeze_forbidden": True},
        "performance_tempo_contract": {
            "playback_speed": "REAL_TIME_1X", "first_visible_displacement_by_seconds": 0.20,
            "primary_action_complete_by_seconds": 1.2, "result_hold_seconds": 0.0,
            "maximum_atomic_window_seconds": 1.2, "maximum_action_gap_seconds": 0.0,
            "slow_motion_interpolation_post_speedup_forbidden": True,
            "atomic_action_windows": [
                {"start_seconds": 0.0, "end_seconds": 0.5, "action": "single frost trace visibly shortens while gaze locks", "state_change": "recession visible by 0.20 seconds"},
                {"start_seconds": 0.5, "end_seconds": 1.2, "action": "same frost trace finishes receding to a faint short remnant", "state_change": "primary frost action complete"},
                {"start_seconds": 1.2, "end_seconds": 2.1, "action": "owning finger performs one restrained flex", "state_change": "finger and dorsal tendons change naturally"},
                {"start_seconds": 2.1, "end_seconds": 3.05, "action": "eyes shift from frost to offscreen opponent", "state_change": "recognition focus changes"},
                {"start_seconds": 3.05, "end_seconds": 4.0, "action": "wrist retracts half a finger width and sleeve creases", "state_change": "residual motion persists through final frame"},
            ],
        },
        "identity_owner_count_contract": {"visible_entities": ["陈迹双眼", "陈迹自己的同一只手", "素白细麻衣袖"], "actor_count": 1, "hand_count": 1, "frost_trace_count": 1, "frost_owner": "陈迹同一根手指", "frost_transfer": "NONE", "second_person_allowed": False},
        "native_dialogue_required": False, "dialogue_lines": [],
        "dialogue_transport": "SILENT_VISUAL", "reference_audio_asset_ids": [], "exact_dialogue_audio_asset_ids": [],
        "source_subtitle_policy": "FORBID",
        "video_audio_contract": {"request_audio_inputs": [], "request_dialogue_text": [], "provider_audio_stream_allowed": False, "returned_audio_stream_is_hard_fail": True, "deterministic_audio_strip_allowed_as_remediation": False},
        "source_audio_contract": {"source_audio_required_absent": True, "audio_stream_required_absent": True, "low_volume_audio_still_fails": True, "post_harvest_audio_strip_as_admission_fix": False},
        "submission_authorization": {"precheck_only": True, "authorized": False, "paid_submission_allowed": False, "transaction_creation_allowed": False, "maximum_new_submissions": 0},
    }
    atomic_json(MANIFEST, {
        "schema": "qingshan.e40.u04.v3.fast720_no_submit_manifest.v1",
        "episode": "E40", "recorded_at": created,
        "status": "READY_LOCAL_PRECHECK_ONLY_NO_PAID_AUTHORIZATION", "provider": "giggle",
        "allowed_video_models": ["seedance-2.0-fast"],
        "forbidden_video_models": ["seedance-2.0-pro", "seedance-2.0-mini", "seedance-2.0"],
        "canonical": {"script_path": rel(SCRIPT), "script_sha256": SCRIPT_SHA, "manifest_path": rel(CANON), "manifest_sha256": CANON_SHA},
        "source_frame_admission": rel(FRAME_ADMISSION), "source_frame_admission_sha256": sha256(FRAME_ADMISSION),
        "rejected_collage_qa": rel(OLD_FAILURE), "rejected_collage_qa_sha256": sha256(OLD_FAILURE),
        "machine_gate_reports": [rel(GATE)], "tasks": [task],
        "submission_policy": {"precheck_only": True, "paid_submission_allowed": False, "provider_post_allowed": False, "durable_transaction_allowed": False, "maximum_new_submissions": 0, "same_round_retry_forbidden": True},
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "blocked_by": "ZERO_COST_PAID_READINESS_NOT_YET_CERTIFIED",
        "next_action": "Run the installed submitter with --precheck-only. If it passes, separately certify current price, collision, exact-frame transport and exactly-once transaction readiness before any provider POST.",
    })
    print(json.dumps({"status": "PASS", "prompt_sha256": sha256(PROMPT), "gate_sha256": sha256(GATE), "manifest_sha256": sha256(MANIFEST), "raw_rgb_sha256": raw}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
