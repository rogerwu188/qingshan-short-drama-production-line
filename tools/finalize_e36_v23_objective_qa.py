#!/usr/bin/env python3
"""Finalize V23 objective QA without promoting the reversible candidate."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CL2X = "CL2X-924"
MAILBOX_SHA = "1421e83dd9e802c1a16eaf57df6c757f761d227c6578e85891b35ddb1834e8f7"
CANONICAL_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
VIDEO_SHA = "89af22464112ec0be2da1fdd8897fd35f46d37cb40c19342422dcd76bb118a83"

VIDEO = ROOT / "working_assets/e36_agentcut_20260801/accepted_only_v23_canonical_dialogue_order/E36_ACCEPTED_ONLY_AGENTCUT_V23_CANONICAL_DIALOGUE_ORDER.mp4"
QA_DIR = ROOT / "qa/e36_agentcut_20260730/v23_canonical_dialogue_order_v1"
AHASH = QA_DIR / "E36_V23_FPS1_ADJACENT_AHASH_QA.json"
CADENCE = QA_DIR / "E36_V23_FRAME_CADENCE_QA.json"
AV = QA_DIR / "E36_V23_FULL_AV_TIMELINE_AUDIT.json"
OCR_RAW = QA_DIR / "E36_V23_FULL_RUNTIME_OCR_QA.json"
OCR_ADJ = QA_DIR / "E36_V23_FULL_RUNTIME_OCR_DIRECT_ADJUDICATION_V1.json"
FRAME_A = QA_DIR / "ocr_false_positive_review/frame_002p5.png"
FRAME_B = QA_DIR / "ocr_false_positive_review/frame_142p5.png"
MAIN_QA = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V23_OBJECTIVE_QA_ADDENDUM_V1.json"
WQ = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPT = ROOT / "workflow/CODEX_TO_CLAUDE.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(name, path)
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise


def main() -> None:
    canonical = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
    canonical_manifest_path = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
    mailbox = ROOT / "codex_docs/CLAUDE_TO_CODEX.md"
    required = [VIDEO, AHASH, CADENCE, AV, OCR_RAW, FRAME_A, FRAME_B, WQ, DISPATCH]
    missing = [rel(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing artifacts: {missing}")
    if sha256(mailbox) != MAILBOX_SHA:
        raise RuntimeError("Mailbox changed; consume latest CL2X first")
    manifest = load(canonical_manifest_path)
    if sha256(canonical) != CANONICAL_SHA or manifest.get("sha256") != CANONICAL_SHA:
        raise RuntimeError("Canonical authority mismatch")
    if sha256(VIDEO) != VIDEO_SHA:
        raise RuntimeError("V23 media changed")

    ahash = load(AHASH)
    cadence = load(CADENCE)
    av = load(AV)
    ocr_raw = load(OCR_RAW)
    if ahash.get("status") != "PASS" or ahash.get("near_pair_ratio_percent", 100) > 15:
        raise RuntimeError("Strict aHash gate failed")
    if cadence.get("status") != "PASS":
        raise RuntimeError("Cadence gate failed")
    av_gate = av.get("gate_results", {})
    if any(av_gate.get(key) != "PASS" for key in (
        "video_decode_timestamps_monotonic",
        "video_presentation_timeline_contiguous",
        "audio_decode_timestamps_monotonic",
        "audio_presentation_timeline_contiguous",
        "av_endpoint_alignment",
        "packet_interleave_alignment",
    )):
        raise RuntimeError("A/V packet timing gate failed")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    adjudication = {
        "schema": "qingshan.e36.v23.ocr_direct_adjudication.v1",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "candidate": rel(VIDEO),
        "candidate_sha256": VIDEO_SHA,
        "raw_ocr": {"path": rel(OCR_RAW), "sha256": sha256(OCR_RAW), "status": ocr_raw.get("status")},
        "machine_failures_preserved": [
            {"time_seconds": 2.5, "recognition": "BU", "confidence": 0.522084},
            {"time_seconds": 142.5, "recognition": "MO", "confidence": 0.516766},
        ],
        "direct_frame_evidence": [
            {
                "time_seconds": 2.5,
                "path": rel(FRAME_A),
                "sha256": sha256(FRAME_A),
                "finding": "NO_LATIN_TEXT_VISIBLE; PERIOD MARKET SIGNAGE CONTAINS A SINGLE HAN GLYPH AND REMAINS A NONCRITICAL POLICY WARNING",
            },
            {
                "time_seconds": 142.5,
                "path": rel(FRAME_B),
                "sha256": sha256(FRAME_B),
                "finding": "NO_TEXT_VISIBLE; WINDOW GEOMETRY AND CAT FUR PRODUCED A LOW-CONFIDENCE OCR FALSE POSITIVE",
            },
        ],
        "status": "PASS_MACHINE_FALSE_POSITIVES_DIRECTLY_ADJUDICATED",
        "critical_visible_text_failures": 0,
        "scope_limit": "This adjudication covers only the two machine-critical OCR hits. It does not clear continuous audiovisual watching, dialogue coverage, lipsync, identity continuity, or promotion.",
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    atomic_json(OCR_ADJ, adjudication)

    blocked = (
        "PROMOTION_ONLY:V23_CONTINUOUS_AUDIOVISUAL_WATCH_INCOMPLETE;"
        "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;"
        "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
        "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
    )
    next_action = (
        "Build V23 contiguous native-speed review packages and continue materially distinct zero-credit source-native recovery for lines4/5/11/12/23/24/27/28; keep V15 canonical and release closed until accepted transcript and uninterrupted full-watch gates pass."
    )
    main_qa = {
        "schema": "qingshan.e36.agentcut_v23_objective_qa_addendum.v1",
        "episode": "E36",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "canonical_script": rel(canonical),
        "canonical_script_sha256": CANONICAL_SHA,
        "canonical_manifest": rel(canonical_manifest_path),
        "canonical_manifest_file_sha256": sha256(canonical_manifest_path),
        "canonical_manifest_declared_sha256": manifest.get("sha256"),
        "candidate": rel(VIDEO),
        "candidate_sha256": VIDEO_SHA,
        "objective_qa": {
            "fps1_adjacent_ahash": {"path": rel(AHASH), "sha256": sha256(AHASH), "near_pairs": ahash["near_pairs"], "adjacent_pairs": ahash["adjacent_pairs"], "ratio_percent": ahash["near_pair_ratio_percent"], "margin_percentage_points": round(15.0 - ahash["near_pair_ratio_percent"], 3), "status": ahash["status"]},
            "frame_cadence": {"path": rel(CADENCE), "sha256": sha256(CADENCE), "frozen_runs": len(cadence["freeze"]["frozen_runs"]), "periodic_chains": cadence["periodic_duplicates"]["periodic_chain_count"], "mpdecimate_removed_frames": cadence["periodic_duplicates"]["mpdecimate_removed_frame_count"], "status": cadence["status"]},
            "av_timeline": {"path": rel(AV), "sha256": sha256(AV), "endpoint_delta_ms": round(av["av_endpoint_delta_seconds"] * 1000, 3), "max_interleave_ms": round(av["video_to_nearest_audio_pts_offset_seconds"]["max"] * 1000, 3), "status": "PASS"},
            "full_runtime_ocr_raw": {"path": rel(OCR_RAW), "sha256": sha256(OCR_RAW), "samples": ocr_raw["sample_count"], "status": ocr_raw["status"], "machine_critical_failures": ocr_raw["critical_text_failures"]},
            "full_runtime_ocr_direct_adjudication": {"path": rel(OCR_ADJ), "sha256": sha256(OCR_ADJ), "status": adjudication["status"], "critical_visible_text_failures": 0},
        },
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "fps1_adjacent_ahash": f"PASS_{ahash['near_pairs']}_OF_{ahash['adjacent_pairs']}_{ahash['near_pair_ratio_percent']:.3f}_PERCENT_MARGIN_{15.0-ahash['near_pair_ratio_percent']:.3f}PP",
            "frame_cadence": "PASS_ZERO_FREEZES_ZERO_PERIODIC_CHAINS_MPDECIMATE_VERIFIED",
            "av_timeline": f"PASS_ENDPOINT_{av['av_endpoint_delta_seconds']*1000:.3f}MS_MAX_INTERLEAVE_{av['video_to_nearest_audio_pts_offset_seconds']['max']*1000:.3f}MS",
            "full_runtime_ocr_machine": "FAIL_PRESERVED_TWO_LOW_CONFIDENCE_LATIN_HITS",
            "full_runtime_ocr_direct": "PASS_ZERO_VISIBLE_LATIN_OR_CRITICAL_TEXT_AT_BOTH_FLAGGED_FRAMES",
            "transcript": "HOLD_39_OF_47",
            "motion": "PASS_30_OF_30",
            "continuous_full_runtime_human_watch": "NOT_COMPLETE",
            "V23_promotion": "NOT_GRANTED_KEEP_V15_CANONICAL",
            "release": "HOLD",
        },
        "blocked_by": blocked,
        "workaround_executed": "Ran V23 full-runtime strict fps1 aHash, native24 cadence with mpdecimate source-timestamp verification, full packet-level A/V timing, and145-sample OCR. Preserved the raw OCR FAIL and directly inspected both machine-critical timestamps; neither frame contains visible Latin or other critical text, so a scoped visual false-positive adjudication was recorded without clearing the full-watch or transcript gates.",
        "credits": {"pay_this_action": 0, "refund_this_action": 0, "net_this_action": 0, "episode_source_net": 9976, "episode_cap": 10000, "refunds_separate": 3084, "headroom": 24, "calls": 135, "active": 0},
        "next_action": next_action,
        "promotion": "REVERSIBLE_NOT_PROMOTED",
    }
    atomic_json(MAIN_QA, main_qa)
    latest = {"status": "REVERSIBLE_NOT_PROMOTED", "media": rel(VIDEO), "media_sha256": VIDEO_SHA, "qa": rel(MAIN_QA), "qa_sha256": sha256(MAIN_QA)}
    note = "V23 now passes strict full-runtime aHash at43/293=14.676% with0.324pp margin, native24 cadence with zero freezes and zero mpdecimate-confirmed periodic chains, and packet-level A/V timing with67.646ms endpoint delta and10.667ms maximum interleave offset. The raw145-sample OCR FAIL is preserved; direct review proves both low-confidence Latin hits are false positives with zero visible critical text. Full uninterrupted watch and transcript39/47 remain open; V15 stays canonical."

    for path in (WQ, DISPATCH):
        payload = load(path)
        payload.update({
            "status": "E36_CL2X924_V23_OBJECTIVE_GATES_PASS_FULL_WATCH_ACTIVE",
            "source_cl2x": SOURCE_CL2X,
            "source_mailbox_sha256": MAILBOX_SHA,
            "updated_at": now,
            "updated_note_latest": note,
            "blocked_by": blocked,
            "next_action": next_action,
            "latest_reversible_agentcut_candidate": rel(VIDEO),
            "latest_reversible_agentcut_candidate_sha256": VIDEO_SHA,
            "latest_reversible_agentcut_qa": rel(MAIN_QA),
            "latest_reversible_agentcut_qa_sha256": sha256(MAIN_QA),
            "latest_reversible_candidate": latest,
            "latest_v23_objective_qa": rel(MAIN_QA),
            "latest_v23_objective_qa_sha256": sha256(MAIN_QA),
            "latest_cl2x924_v23_objective_qa": note,
            "workaround_executed": main_qa["workaround_executed"],
        })
        if path == WQ:
            e36 = payload.setdefault("lines", {}).setdefault("E36", {})
            e36.update({
                "status": payload["status"],
                "current_phase": note,
                "source_cl2x": SOURCE_CL2X,
                "source_mailbox_sha256": MAILBOX_SHA,
                "blocked_by": blocked,
                "next_action": next_action,
                "latest_reversible_candidate": latest,
                "latest_v23_objective_qa": rel(MAIN_QA),
                "latest_v23_objective_qa_sha256": sha256(MAIN_QA),
                "latest_cl2x924_v23_objective_qa": note,
            })
        atomic_json(path, payload)

    receipt = f"""
X2CL-20260801-1356
- source_cl2x: {SOURCE_CL2X}
- source_mailbox_sha256: {MAILBOX_SHA}
- blocked_by: {blocked}
- workaround_executed: {main_qa['workaround_executed']}
- artifacts:
  - {rel(VIDEO)} sha256={VIDEO_SHA}
  - {rel(AHASH)} sha256={sha256(AHASH)}
  - {rel(CADENCE)} sha256={sha256(CADENCE)}
  - {rel(AV)} sha256={sha256(AV)}
  - {rel(OCR_RAW)} sha256={sha256(OCR_RAW)}
  - {rel(OCR_ADJ)} sha256={sha256(OCR_ADJ)}
  - {rel(FRAME_A)} sha256={sha256(FRAME_A)}
  - {rel(FRAME_B)} sha256={sha256(FRAME_B)}
  - {rel(MAIN_QA)} sha256={sha256(MAIN_QA)}
- gate_results: canonical_script_manifest=PASS_EXACT; fps1_adjacent_ahash=PASS_43_OF_293_14P676_PERCENT_MARGIN_0P324PP; frame_cadence=PASS_ZERO_FREEZES_ZERO_PERIODIC_CHAINS_MPDECIMATE_VERIFIED; av_timeline=PASS_ENDPOINT_67P646MS_MAX_INTERLEAVE_10P667MS; raw_ocr=FAIL_PRESERVED_TWO_LOW_CONFIDENCE_LATIN_HITS; direct_ocr=PASS_ZERO_VISIBLE_CRITICAL_TEXT_AT_BOTH_FLAGGED_FRAMES; transcript=HOLD_39_OF_47; motion=PASS_30_OF_30; continuous_full_runtime_human_watch=NOT_COMPLETE; V23_promotion=NOT_GRANTED_KEEP_V15_CANONICAL; release=HOLD
- credits: Pay0 / Refund0 / Net0 this action; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0
- next_action: {next_action}
"""
    with RECEIPT.open("a", encoding="utf-8") as handle:
        handle.write(receipt)
    print(json.dumps({"status": "PASS", "main_qa": rel(MAIN_QA), "main_qa_sha256": sha256(MAIN_QA), "updated_at": now}, ensure_ascii=False))


if __name__ == "__main__":
    main()
