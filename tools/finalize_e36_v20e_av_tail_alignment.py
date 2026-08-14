#!/usr/bin/env python3
"""Finalize the zero-credit V20E tail-alignment repair and synchronize local state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CL2X = "CL2X-921"
MAILBOX_SHA = "0f7af7c227c3c4c674a9ab697d84642d13642d5bb99eb57f885cc10a3476e86c"
CANONICAL_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
V20D = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v20d_temporally_smoothed_registered_hybrid/E36_ACCEPTED_ONLY_AGENTCUT_V20D_TEMPORALLY_SMOOTHED_REGISTERED_HYBRID.mp4"
V20E = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v20e_av_tail_aligned_hybrid/E36_ACCEPTED_ONLY_AGENTCUT_V20E_AV_TAIL_ALIGNED_HYBRID.mp4"
QA_DIR = ROOT / "qa/e36_agentcut_20260730/v20d_full_av_integrity_v1"
TIMELINE_D = QA_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V20D_FULL_AV_TIMELINE_AUDIT_V1.json"
TIMELINE_E = QA_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V20E_FULL_AV_TIMELINE_AUDIT_V1.json"
AHASH_D = QA_DIR / "E36_V20D_FPS1_ADJACENT_AHASH_RETEST_V2.json"
AHASH_E = QA_DIR / "E36_V20E_FPS1_ADJACENT_AHASH_RETEST_V2.json"
CADENCE_E = QA_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V20E_FRAME_CADENCE_QA_V1.json"
OCR_E = QA_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V20E_FULL_RUNTIME_OCR_QA_V2.json"
OCR_FRAME = QA_DIR / "E36_V20D_OCR_DIRECT_188P5S.jpg"
DECODE_E = QA_DIR / "E36_V20E_FULL_DECODE_V1.log"
SILENCE_E = QA_DIR / "E36_V20E_SILENCEDETECT_V1.log"
BLACK_FREEZE_E = QA_DIR / "E36_V20E_BLACK_FREEZE_V1.log"
VIDEO_HASH_D = QA_DIR / "E36_V20D_VIDEO_PACKET_HASH_V1.txt"
VIDEO_HASH_E = QA_DIR / "E36_V20E_VIDEO_PACKET_HASH_V1.txt"
AUDIO_HASH_D = QA_DIR / "E36_V20D_AUDIO_PACKET_PREFIX_HASH_V1.txt"
AUDIO_HASH_E = QA_DIR / "E36_V20E_AUDIO_PACKET_HASH_V1.txt"
MANIFEST = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V20E_AV_TAIL_ALIGNED_HYBRID_MANIFEST_V1.json"
DIRECT_OCR = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V20E_OCR_DIRECT_ADJUDICATION_V1.json"
MAIN_QA = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V20E_AV_TAIL_ALIGNED_HYBRID_QA_V1.json"
WQ = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPT = ROOT / "workflow/CODEX_TO_CLAUDE.md"


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(name, path)
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise


def packet_hash(path: Path) -> str:
    match = re.fullmatch(r"SHA256=([0-9a-f]{64})\s*", path.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"Malformed packet hash: {path}")
    return match.group(1)


def count_events(path: Path, token: str) -> int:
    return path.read_text(encoding="utf-8", errors="replace").count(token)


def main() -> None:
    canonical = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
    canonical_manifest = load(ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json")
    if sha256(canonical) != CANONICAL_SHA or canonical_manifest.get("sha256") != CANONICAL_SHA:
        raise RuntimeError("Canonical script/manifest authority mismatch")
    if sha256(ROOT / "codex_docs/CLAUDE_TO_CODEX.md") != MAILBOX_SHA:
        raise RuntimeError("Mailbox changed; consume the new CL2X message before finalizing")

    required = [
        V20D, V20E, TIMELINE_D, TIMELINE_E, AHASH_D, AHASH_E, CADENCE_E,
        OCR_E, OCR_FRAME, DECODE_E, SILENCE_E, BLACK_FREEZE_E,
        VIDEO_HASH_D, VIDEO_HASH_E, AUDIO_HASH_D, AUDIO_HASH_E,
    ]
    missing = [rel(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing required artifacts: {missing}")

    timeline_d, timeline_e = load(TIMELINE_D), load(TIMELINE_E)
    ahash_d, ahash_e = load(AHASH_D), load(AHASH_E)
    cadence_e, ocr_e = load(CADENCE_E), load(OCR_E)
    video_hash_d, video_hash_e = packet_hash(VIDEO_HASH_D), packet_hash(VIDEO_HASH_E)
    audio_hash_d, audio_hash_e = packet_hash(AUDIO_HASH_D), packet_hash(AUDIO_HASH_E)
    checks = {
        "v20d_media_sha": sha256(V20D) == "993de024693b05100515ad3f130c52d9b157093d18499145e0bc4b2f1bf6e35a",
        "v20e_media_sha": sha256(V20E) == "7ce6c65b9fdf4935f3889ceaef103cad7b864e749ce3b9fe12cc9d1b8a8ed697",
        "video_packet_payload_identity": video_hash_d == video_hash_e,
        "retained_audio_packet_payload_identity": audio_hash_d == audio_hash_e,
        "v20d_endpoint_fail_preserved": timeline_d["gate_results"]["av_endpoint_alignment"] == "FAIL",
        "v20e_endpoint_pass": timeline_e["gate_results"]["av_endpoint_alignment"] == "PASS",
        "v20e_interleave_pass": timeline_e["gate_results"]["packet_interleave_alignment"] == "PASS",
        "v20e_ahash_pass": ahash_e["status"] == "PASS" and ahash_e["near_pair_ratio_percent"] <= 15.0,
        "v20d_v20e_ahash_retest_parity": ahash_d["near_pair_indices"] == ahash_e["near_pair_indices"],
        "v20e_cadence_pass": cadence_e["status"] == "PASS",
        "v20e_ocr_pass": ocr_e["status"] == "PASS" and ocr_e["critical_text_failures"] == 0,
        "v20e_full_decode_pass": DECODE_E.stat().st_size == 0,
        "v20e_black_pass": count_events(BLACK_FREEZE_E, "black_start") == 0,
        "v20e_freeze_pass": count_events(BLACK_FREEZE_E, "freeze_start") == 0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"V20E finalization checks failed: {checks}")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    blocked = (
        "PROMOTION_ONLY:V20E_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;"
        "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;"
        "RELEASE_ONLY:MOTION_29_OF_30_U08;"
        "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
        "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
    )
    next_action = (
        "Perform uninterrupted native-speed full-runtime audiovisual review of V20E, using the ready V19/V20D comparison reel for the repaired window; "
        "concurrently continue zero-credit recovery for lines4/5/11/12/23/24/27/28 and U08 without promoting V20E."
    )

    direct_ocr = {
        "schema": "qingshan.e36.agentcut_v20e_ocr_direct_adjudication.v1",
        "episode": "E36",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "candidate": rel(V20E),
        "candidate_sha256": sha256(V20E),
        "machine_report": rel(OCR_E),
        "machine_report_sha256": sha256(OCR_E),
        "direct_frame": rel(OCR_FRAME),
        "direct_frame_sha256": sha256(OCR_FRAME),
        "adjudication": {
            "time_seconds": 188.5,
            "machine_text": "刘家",
            "canonical_evidence": "E36 canonical scene 9-4 requires the period-diegetic 刘家 stamp to become visible on the old ticket.",
            "visual_result": "PASS_PERIOD_DIEGETIC_CHINESE_TICKET_STAMP_NO_MODERN_OR_GARBLED_OVERLAY",
        },
        "gate_results": {
            "machine_ocr_with_bidirectional_lexicon": "PASS_143_SAMPLES_ZERO_CRITICAL_FAILURES",
            "direct_visual_ocr": "PASS",
            "modern_text": "PASS_NONE",
            "period_diegetic_text": "PASS_CANONICAL_LIU_JIA_STAMP",
            "release": "HOLD_OTHER_GATES",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    atomic_json(DIRECT_OCR, direct_ocr)

    manifest = {
        "schema": "qingshan.e36.agentcut_v20e_av_tail_aligned_manifest.v1",
        "episode": "E36",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "canonical_script": rel(canonical),
        "canonical_sha256": CANONICAL_SHA,
        "source_candidate": rel(V20D),
        "source_candidate_sha256": sha256(V20D),
        "candidate": rel(V20E),
        "candidate_sha256": sha256(V20E),
        "repair": "STREAM_COPY_TRIM_AUDIO_ONLY_TAIL_TO_VIDEO_ENDPOINT_NEAREST_PACKET_BOUNDARY",
        "source_video_packet_sha256": video_hash_d,
        "candidate_video_packet_sha256": video_hash_e,
        "retained_source_audio_packet_sha256": audio_hash_d,
        "candidate_audio_packet_sha256": audio_hash_e,
        "video_packet_payload_identity": "PASS_EXACT",
        "retained_audio_packet_payload_identity": "PASS_EXACT",
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "promotion": "REVERSIBLE_NOT_PROMOTED",
    }
    atomic_json(MANIFEST, manifest)

    main_qa = {
        "schema": "qingshan.e36.agentcut_v20e_av_tail_aligned_qa.v1",
        "episode": "E36",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "candidate": rel(V20E),
        "candidate_sha256": sha256(V20E),
        "manifest": rel(MANIFEST),
        "manifest_sha256": sha256(MANIFEST),
        "repair_chain": {
            "v20d_full_av_timeline": {"path": rel(TIMELINE_D), "sha256": sha256(TIMELINE_D), "endpoint_delta_seconds": timeline_d["av_endpoint_delta_seconds"], "result": "FAIL_PRESERVED"},
            "v20e_full_av_timeline": {"path": rel(TIMELINE_E), "sha256": sha256(TIMELINE_E), "endpoint_delta_seconds": timeline_e["av_endpoint_delta_seconds"], "result": "PASS"},
            "trimmed_audio_packets": timeline_d["audio_packets"]["packet_count"] - timeline_e["audio_packets"]["packet_count"],
            "video_packets_preserved": timeline_e["video_packets"]["packet_count"],
            "video_packet_payload_identity": "PASS_EXACT",
            "retained_audio_packet_payload_identity": "PASS_EXACT",
        },
        "objective_qa": {
            "fps1_adjacent_ahash_retest": {"path": rel(AHASH_E), "sha256": sha256(AHASH_E), "near_pairs": ahash_e["near_pairs"], "adjacent_pairs": ahash_e["adjacent_pairs"], "ratio_percent": ahash_e["near_pair_ratio_percent"], "margin_percentage_points": round(15.0 - ahash_e["near_pair_ratio_percent"], 3), "status": ahash_e["status"], "note": "Back-to-back retest gives identical 42-pair indices for V20D and V20E; historical V20D 40-pair result is preserved but not used for this candidate."},
            "frame_cadence": {"path": rel(CADENCE_E), "sha256": sha256(CADENCE_E), "near_duplicate_frames": cadence_e["periodic_duplicates"]["near_duplicate_frame_count"], "frozen_runs": len(cadence_e["freeze"]["frozen_runs"]), "periodic_chains": cadence_e["periodic_duplicates"]["periodic_chain_count"], "status": cadence_e["status"]},
            "full_runtime_ocr": {"path": rel(OCR_E), "sha256": sha256(OCR_E), "samples": ocr_e["sample_count"], "critical_failures": ocr_e["critical_text_failures"], "status": ocr_e["status"]},
            "direct_ocr": {"path": rel(DIRECT_OCR), "sha256": sha256(DIRECT_OCR), "status": "PASS_CANONICAL_PERIOD_DIEGETIC_TEXT"},
            "silence_events_over_1s_at_minus45db": count_events(SILENCE_E, "silence_start"),
            "black_events": count_events(BLACK_FREEZE_E, "black_start"),
            "freeze_events": count_events(BLACK_FREEZE_E, "freeze_start"),
            "full_decode_error_lines": sum(1 for line in DECODE_E.read_text().splitlines() if line.strip()),
        },
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "V20D_av_endpoint_alignment": "FAIL_PRESERVED_108P060MS",
            "V20E_av_endpoint_alignment": "PASS_9P915MS",
            "packet_interleave_alignment": "PASS_MAX_10P667MS",
            "video_packet_payload_identity": "PASS_EXACT",
            "retained_audio_packet_payload_identity": "PASS_EXACT",
            "full_decode": "PASS_ZERO_ERRORS",
            "fps1_adjacent_ahash": "PASS_42_OF_288_14P583_PERCENT_MARGIN_0P417PP",
            "frame_cadence": "PASS_ZERO_FREEZES_ZERO_PERIODIC_CHAINS",
            "full_runtime_ocr": "PASS_143_SAMPLES_ZERO_CRITICAL_FAILURES",
            "direct_period_text": "PASS_CANONICAL_LIU_JIA_STAMP",
            "continuous_full_runtime_human_watch": "NOT_COMPLETE",
            "V20E_promotion": "NOT_GRANTED_KEEP_V15_CANONICAL",
            "transcript": "HOLD_39_OF_47",
            "motion": "HOLD_29_OF_30_U08",
            "release": "HOLD",
        },
        "blocked_by": blocked,
        "workaround_executed": "Detected V20D's 108.060ms audio-only tail with a fresh packet audit, preserved the objective FAIL, stream-copied all video packets and the retained audio prefix into V20E while dropping five terminal audio packets, then reran full decode, packet timing, aHash twice, cadence, full-runtime OCR and direct OCR adjudication.",
        "credits": {"pay_this_action": 0, "refund_this_action": 0, "net_this_action": 0, "episode_source_net": 9976, "episode_cap": 10000, "refunds_separate": 3084, "headroom": 24, "calls": 135, "active": 0},
        "next_action": next_action,
        "promotion": "REVERSIBLE_NOT_PROMOTED",
    }
    atomic_json(MAIN_QA, main_qa)

    note = (
        "Consumed CL2X-921 and synchronized the stale nested E36 state. Fresh packet-level QA found V20D had a 108.060ms audio-only tail, narrowly failing the 100ms endpoint gate. "
        "Built zero-credit V20E by stream-copying all video and retained audio packets while dropping five terminal audio packets. Endpoint delta is now9.915ms; video and retained-audio packet payload hashes are exact. "
        "V20E fully decodes, passes cadence, full-runtime OCR and the current strict aHash retest at42/288=14.583%. V20E remains reversible/unpromoted and V15 remains canonical."
    )
    latest = {
        "status": "REVERSIBLE_NOT_PROMOTED",
        "media": rel(V20E),
        "media_sha256": sha256(V20E),
        "qa": rel(MAIN_QA),
        "qa_sha256": sha256(MAIN_QA),
    }
    wq = load(WQ)
    wq.update({
        "status": "E36_CL2X921_CONSUMED_V20E_AV_TAIL_ALIGNMENT_PASS_REALTIME_WATCH_ACTIVE",
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "updated_at": now,
        "updated_note_latest": note,
        "blocked_by": blocked,
        "next_action": next_action,
        "latest_reversible_candidate": latest,
        "latest_cl2x921_v20e_av_tail_alignment": note,
    })
    e36 = wq.setdefault("lines", {}).setdefault("E36", {})
    e36.update({
        "status": "E36_CL2X921_CONSUMED_V20E_AV_TAIL_ALIGNMENT_PASS_REALTIME_WATCH_ACTIVE",
        "current_phase": note,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "blocked_by": blocked,
        "next_action": next_action,
        "latest_reversible_candidate": latest,
        "latest_cl2x921_v20e_av_tail_alignment": note,
    })
    atomic_json(WQ, wq)

    dispatch = load(DISPATCH)
    dispatch.update({
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "updated_at": now,
        "blocked_by": blocked,
        "next_action": next_action,
        "latest_reversible_candidate": latest,
        "latest_cl2x921_v20e_av_tail_alignment": note,
    })
    atomic_json(DISPATCH, dispatch)

    marker = "# [X2CL-20260801-0745] CL2X-921 consumed; E36 V20E A/V tail alignment"
    receipt_text = RECEIPT.read_text(encoding="utf-8")
    if marker in receipt_text:
        raise RuntimeError("Receipt marker already exists")
    artifact_pairs = [
        (V20E, sha256(V20E)), (MANIFEST, sha256(MANIFEST)), (MAIN_QA, sha256(MAIN_QA)),
        (TIMELINE_E, sha256(TIMELINE_E)), (AHASH_E, sha256(AHASH_E)),
        (CADENCE_E, sha256(CADENCE_E)), (OCR_E, sha256(OCR_E)),
        (DIRECT_OCR, sha256(DIRECT_OCR)), (OCR_FRAME, sha256(OCR_FRAME)),
        (WQ, sha256(WQ)), (DISPATCH, sha256(DISPATCH)),
    ]
    artifacts = "; ".join(f"`{rel(path)}` sha256=`{digest}`" for path, digest in artifact_pairs)
    receipt = f"""


{marker}
- source_cl2x: `{SOURCE_CL2X}`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{blocked}`
- workaround_executed: `Fresh packet audit exposed V20D's 108.060ms audio-only tail as an objective endpoint FAIL. Preserved that FAIL, stream-copied every video packet and the retained audio prefix into V20E, dropped five terminal audio packets, and reran full decode, packet timing, strict aHash twice, mpdecimate-backed cadence, full-runtime OCR and direct period-text adjudication. Also synchronized the stale nested lines.E36 status/blocked_by/next_action fields requested by CL2X-921.`
- artifacts: {artifacts}
- gate_results: `canonical_script_manifest:PASS_EXACT;CL2X921_consumed:PASS;V20D_av_endpoint:FAIL_PRESERVED_108P060MS;V20E_av_endpoint:PASS_9P915MS;video_packet_payload:PASS_EXACT;retained_audio_packet_payload:PASS_EXACT;V20E_full_decode:PASS_ZERO_ERRORS;V20E_fps1_adjacent_ahash:PASS_42_OF_288_14P583_PERCENT_MARGIN_0P417PP;V20E_frame_cadence:PASS_ZERO_FREEZES_ZERO_PERIODIC_CHAINS;V20E_full_runtime_ocr:PASS_143_SAMPLES_ZERO_CRITICAL_FAILURES;V20E_direct_period_text:PASS_CANONICAL_LIU_JIA_STAMP;continuous_full_runtime_human_watch:NOT_COMPLETE;V20E_promotion:NOT_GRANTED;V15_status:CANONICAL;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
    RECEIPT.write_text(receipt_text + receipt, encoding="utf-8")
    print(json.dumps({"status": "PASS", "candidate": rel(V20E), "candidate_sha256": sha256(V20E), "qa": rel(MAIN_QA), "qa_sha256": sha256(MAIN_QA)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
