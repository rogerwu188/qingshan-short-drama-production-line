#!/usr/bin/env python3
"""Finalize reversible V21 objective QA and synchronize E36 local state."""

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
V21 = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v21_u08_motion_complete/E36_ACCEPTED_ONLY_AGENTCUT_V21_U08_MOTION_COMPLETE.mp4"
MANIFEST = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v21_u08_motion_complete/E36_ACCEPTED_ONLY_AGENTCUT_V21_U08_MOTION_COMPLETE_MANIFEST.json"
QA_DIR = ROOT / "qa/e36_agentcut_20260730/v21_u08_motion_complete_v1"
AHASH = QA_DIR / "E36_V21_FPS1_ADJACENT_AHASH_QA.json"
CADENCE = QA_DIR / "E36_V21_FRAME_CADENCE_QA.json"
OCR = QA_DIR / "E36_V21_FULL_RUNTIME_OCR_QA.json"
AV = QA_DIR / "E36_V21_FULL_AV_TIMELINE_AUDIT.json"
DECODE = QA_DIR / "E36_V21_FULL_DECODE.log"
SILENCE = QA_DIR / "E36_V21_SILENCEDETECT.log"
BLACK_FREEZE = QA_DIR / "E36_V21_BLACK_FREEZE.log"
CONTACT = QA_DIR / "E36_V21_U07_U08_U09_4FPS_BOUNDARY_CONTACT.jpg"
U08_QA = ROOT / "qa/e36_agentcut_20260730/E36_U08_ZERO_CREDIT_PAPER_CHAOS_TERMINAL_DIRECT_QA_V1.json"
U08_MEDIA = ROOT / "working_assets/e36_autonomous_recovery_20260731/u08_zero_credit_vfx_bridge_v6/E36_U08_ZERO_CREDIT_PAPER_CHAOS_TERMINAL_BRIDGE_V6.mp4"
SOURCE_MAP = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V11.json"
TRANSCRIPT = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V15.json"
CHAIN = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_PACKAGE_49_SOURCE_CHAIN_OF_CUSTODY_INTEGRITY_QA_V5.json"
MAIN_QA = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V21_U08_MOTION_COMPLETE_QA_V1.json"
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


def count(path: Path, token: str) -> int:
    return path.read_text(encoding="utf-8", errors="replace").count(token)


def main() -> None:
    canonical = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
    canonical_manifest = load(ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json")
    if sha256(canonical) != CANONICAL_SHA or canonical_manifest.get("sha256") != CANONICAL_SHA:
        raise RuntimeError("Canonical authority mismatch")
    if sha256(ROOT / "codex_docs/CLAUDE_TO_CODEX.md") != MAILBOX_SHA:
        raise RuntimeError("Mailbox changed; consume the latest CL2X before finalizing")
    required = [V21, MANIFEST, AHASH, CADENCE, OCR, AV, DECODE, SILENCE, BLACK_FREEZE, CONTACT, U08_QA, SOURCE_MAP, TRANSCRIPT, CHAIN]
    missing = [rel(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing artifacts: {missing}")

    ahash, cadence, ocr, av = load(AHASH), load(CADENCE), load(OCR), load(AV)
    u08, source_map, transcript, chain = load(U08_QA), load(SOURCE_MAP), load(TRANSCRIPT), load(CHAIN)
    checks = {
        "media_sha": sha256(V21) == "1bf79214c8d7fc2473bf90c79203fda3a721ae659751f2cc7d8e1b7424d3eb26",
        "canonical_manifest": True,
        "u08_acceptance": u08.get("status") == "PASS_ACCEPTED_U08_MOTION_30_OF_30",
        "source_map_motion_complete": source_map.get("accepted_canonical_unit_count") == 30 and source_map.get("assembly_gate") == "PASS",
        "transcript_exact_hold": transcript["binding_summary"]["canonical_lines_covered_by_bound_transcript_stream"] == 39,
        "chain_49": chain.get("status") == "PASS_49_SOURCE_ACCEPTED_PACKAGE_CHAIN_OF_CUSTODY",
        "ahash": ahash.get("status") == "PASS" and ahash.get("near_pair_ratio_percent", 100) <= 15,
        "cadence": cadence.get("status") == "PASS",
        "ocr": ocr.get("status") == "PASS" and ocr.get("critical_text_failures") == 0,
        "decode": DECODE.stat().st_size == 0,
        "av_endpoint": av["gate_results"]["av_endpoint_alignment"] == "PASS",
        "av_interleave": av["gate_results"]["packet_interleave_alignment"] == "PASS",
        "black": count(BLACK_FREEZE, "black_start") == 0,
        "freeze": count(BLACK_FREEZE, "freeze_start") == 0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"V21 checks failed: {checks}")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    blocked = (
        "PROMOTION_ONLY:V21_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;"
        "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;"
        "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
        "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
    )
    next_action = (
        "Perform uninterrupted native-speed full-runtime audiovisual review of V21 with focused U07-U08-U09 boundary review; concurrently continue zero-credit source-native recovery for lines4/5/11/12/23/24/27/28 and prepare the release package without promoting V21."
    )
    main_qa = {
        "schema": "qingshan.e36.agentcut_v21_u08_motion_complete_qa.v1",
        "episode": "E36",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "canonical_script": rel(canonical),
        "canonical_script_sha256": CANONICAL_SHA,
        "candidate": rel(V21),
        "candidate_sha256": sha256(V21),
        "manifest": rel(MANIFEST),
        "manifest_sha256": sha256(MANIFEST),
        "accepted_only_authority": {
            "source_map": {"path": rel(SOURCE_MAP), "sha256": sha256(SOURCE_MAP), "sources": 49, "motion": "PASS_30_OF_30"},
            "transcript": {"path": rel(TRANSCRIPT), "sha256": sha256(TRANSCRIPT), "coverage": "HOLD_39_OF_47"},
            "chain_of_custody": {"path": rel(CHAIN), "sha256": sha256(CHAIN), "status": chain["status"]},
            "u08_direct_qa": {"path": rel(U08_QA), "sha256": sha256(U08_QA), "status": u08["status"]}
        },
        "objective_qa": {
            "full_decode": {"path": rel(DECODE), "sha256": sha256(DECODE), "status": "PASS_ZERO_ERRORS"},
            "av_timeline": {"path": rel(AV), "sha256": sha256(AV), "endpoint_delta_ms": round(av["av_endpoint_delta_seconds"] * 1000, 3), "max_interleave_ms": round(av["video_to_nearest_audio_pts_offset_seconds"]["max"] * 1000, 3), "status": "PASS"},
            "fps1_adjacent_ahash": {"path": rel(AHASH), "sha256": sha256(AHASH), "near_pairs": ahash["near_pairs"], "adjacent_pairs": ahash["adjacent_pairs"], "ratio_percent": ahash["near_pair_ratio_percent"], "margin_percentage_points": round(15.0 - ahash["near_pair_ratio_percent"], 3), "status": ahash["status"]},
            "frame_cadence": {"path": rel(CADENCE), "sha256": sha256(CADENCE), "frozen_runs": len(cadence["freeze"]["frozen_runs"]), "periodic_chains": cadence["periodic_duplicates"]["periodic_chain_count"], "status": cadence["status"]},
            "full_runtime_ocr": {"path": rel(OCR), "sha256": sha256(OCR), "samples": ocr["sample_count"], "critical_failures": ocr["critical_text_failures"], "status": ocr["status"]},
            "silence_events_over_1s_at_minus45db": count(SILENCE, "silence_start"),
            "silence_parity": "PASS_SAME_THREE_EVENTS_AS_V20E_SHIFTED_BY_U08_INSERTION",
            "black_events": count(BLACK_FREEZE, "black_start"),
            "freeze_events": count(BLACK_FREEZE, "freeze_start")
        },
        "direct_boundary_qa": {
            "contact_sheet": rel(CONTACT),
            "contact_sheet_sha256": sha256(CONTACT),
            "sampling": "PASS_28_ORDERED_FRAMES_AT_4FPS_OVER_55P5_TO_62P5_SECONDS",
            "u07_to_u08_causality": "PASS_WITHDRAWAL_AND_PAPER_SUBSTITUTE_PRECEDE_BLADE_IMPACT",
            "u08_contact": "PASS_BLADE_CONTACTS_ONLY_PAPER_SHELL_WITH_OUTWARD_FRAGMENTS",
            "u08_terminal": "PASS_PAPER_CHAOS_TRUE_CAPTIVE_NOT_VISIBLE",
            "u08_to_u09_causality": "PASS_EXECUTION_GROUND_ESCAPE_BUTTON_TO_INTERROGATION_INTERIOR",
            "identity_period_weather": "PASS_REPRESENTATIVE_BOUNDARY_SAMPLES",
            "scope_limit": "Boundary samples and objective gates do not clear uninterrupted full-runtime audiovisual comfort, lipsync, breath, or causal continuity."
        },
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "accepted_source_chain": "PASS_49_OF_49_SHA_EXACT_ZERO_GAPS",
            "transcript": "HOLD_39_OF_47",
            "motion": "PASS_30_OF_30",
            "u08": "PASS_ACCEPTED_ZERO_CREDIT_SOURCE_NATIVE_RECOMPOSITION",
            "full_decode": "PASS_ZERO_ERRORS",
            "av_endpoint": "PASS_32P478MS",
            "packet_interleave": "PASS_MAX_10P667MS",
            "fps1_adjacent_ahash": "PASS_42_OF_293_14P334_PERCENT_MARGIN_0P666PP",
            "frame_cadence": "PASS_ZERO_FREEZES_ZERO_PERIODIC_CHAINS",
            "full_runtime_ocr": "PASS_145_SAMPLES_ZERO_CRITICAL_FAILURES",
            "boundary_causality": "PASS_REPRESENTATIVE_4FPS",
            "continuous_full_runtime_human_watch": "NOT_COMPLETE",
            "V21_promotion": "NOT_GRANTED_KEEP_V15_CANONICAL",
            "release": "HOLD"
        },
        "blocked_by": blocked,
        "workaround_executed": "Preserved V3-V5 U08 failures, repaired the real-captive leak and terminal-state violation with source-native moving layers, admitted V6 at zero credits, rebuilt the accepted-only map to49 sources and30/30 motion, inserted U08 into reversible V21, and reran full decode, packet timing, strict aHash, cadence, OCR, black/freeze, silence-parity and boundary-causality QA.",
        "credits": {"pay_this_action": 0, "refund_this_action": 0, "net_this_action": 0, "episode_source_net": 9976, "episode_cap": 10000, "refunds_separate": 3084, "headroom": 24, "calls": 135, "active": 0},
        "next_action": next_action,
        "promotion": "REVERSIBLE_NOT_PROMOTED"
    }
    atomic_json(MAIN_QA, main_qa)

    latest = {"status": "REVERSIBLE_NOT_PROMOTED", "media": rel(V21), "media_sha256": sha256(V21), "qa": rel(MAIN_QA), "qa_sha256": sha256(MAIN_QA)}
    note = (
        "Consumed CL2X-924 and resolved both carried advisories: the dedicated reversible-candidate pointer now targets V21, and the strict aHash retest now runs on the rebuilt full candidate at42/293=14.334% with0.666pp margin. Zero-credit U08 V6 passes canonical blade-to-paper contact, outward paper burst and no-visible-captive terminal; accepted source map V11 binds49 sources and closes motion30/30. V21 also passes full decode, A/V endpoint/interleave, cadence and145-sample OCR. Transcript remains39/47, continuous full watch remains incomplete, V21 is unpromoted and V15 remains canonical."
    )
    wq = load(WQ)
    wq.update({
        "status": "E36_CL2X924_CONSUMED_V21_U08_MOTION_30_OF_30_FULL_WATCH_ACTIVE",
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "updated_at": now,
        "updated_note_latest": note,
        "blocked_by": blocked,
        "next_action": next_action,
        "latest_agentcut_candidate": rel(V21),
        "latest_reversible_agentcut_candidate": rel(V21),
        "latest_reversible_agentcut_candidate_sha256": sha256(V21),
        "latest_reversible_agentcut_candidate_qa": rel(MAIN_QA),
        "latest_reversible_agentcut_candidate_qa_sha256": sha256(MAIN_QA),
        "latest_reversible_candidate": latest,
        "latest_u08_zero_credit_motion_admission": {"media": rel(U08_MEDIA), "media_sha256": sha256(U08_MEDIA), "qa": rel(U08_QA), "qa_sha256": sha256(U08_QA), "source_map": rel(SOURCE_MAP), "source_map_sha256": sha256(SOURCE_MAP), "motion": "PASS_30_OF_30"},
        "latest_cl2x924_v21_u08_motion_complete": note
    })
    e36 = wq.setdefault("lines", {}).setdefault("E36", {})
    e36.update({
        "status": "E36_CL2X924_CONSUMED_V21_U08_MOTION_30_OF_30_FULL_WATCH_ACTIVE",
        "current_phase": note,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "blocked_by": blocked,
        "next_action": next_action,
        "latest_reversible_candidate": latest,
        "latest_u08_zero_credit_motion_admission": wq["latest_u08_zero_credit_motion_admission"],
        "latest_cl2x924_v21_u08_motion_complete": note
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
        "latest_u08_zero_credit_motion_admission": wq["latest_u08_zero_credit_motion_admission"],
        "latest_cl2x924_v21_u08_motion_complete": note,
        "workaround_executed": main_qa["workaround_executed"]
    })
    atomic_json(DISPATCH, dispatch)

    receipt_id = datetime.now(timezone.utc).strftime("X2CL-%Y%m%d-%H%M")
    receipt = f"""
\n{receipt_id} [codex→Claude] E36 {SOURCE_CL2X} zero-credit U08 motion closure and reversible V21 objective QA
- source_cl2x: `{SOURCE_CL2X}`; source_mailbox_sha256: `{MAILBOX_SHA}`
- blocked_by: `{blocked}`
- workaround_executed: `{main_qa['workaround_executed']}`
- artifacts: `{rel(U08_QA)}` sha `{sha256(U08_QA)}`; `{rel(SOURCE_MAP)}` sha `{sha256(SOURCE_MAP)}`; `{rel(TRANSCRIPT)}` sha `{sha256(TRANSCRIPT)}`; `{rel(CHAIN)}` sha `{sha256(CHAIN)}`; `{rel(V21)}` sha `{sha256(V21)}`; `{rel(MAIN_QA)}` sha `{sha256(MAIN_QA)}`
- gate_results: `canonical:PASS_EXACT;accepted_sources:PASS_49_OF_49;transcript:HOLD_39_OF_47;motion:PASS_30_OF_30;U08:PASS_ZERO_CREDIT_SOURCE_NATIVE_RECOMPOSITION;V21_full_decode:PASS_ZERO_ERRORS;V21_AV_endpoint:PASS_32P478MS;V21_interleave:PASS_MAX_10P667MS;V21_aHash:PASS_42_OF_293_14P334_PERCENT;V21_cadence:PASS_ZERO_FREEZES_ZERO_PERIODIC_CHAINS;V21_OCR:PASS_145_SAMPLES_ZERO_CRITICAL;continuous_full_watch:NOT_COMPLETE;V21_promotion:NOT_GRANTED;V15:CANONICAL;release:HOLD`
- credits: `Pay0/Refund0/Net0 this action; episode source Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
    with RECEIPT.open("a", encoding="utf-8") as handle:
        handle.write(receipt)
    print(json.dumps({"qa": rel(MAIN_QA), "qa_sha256": sha256(MAIN_QA), "work_queue_sha256": sha256(WQ), "dispatch_sha256": sha256(DISPATCH), "receipt": receipt_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
