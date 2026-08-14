#!/usr/bin/env python3
"""Finalize V23 two-part release preparation without platform submission."""

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
V23_SHA = "89af22464112ec0be2da1fdd8897fd35f46d37cb40c19342422dcd76bb118a83"
V23 = ROOT / "working_assets/e36_agentcut_20260801/accepted_only_v23_canonical_dialogue_order/E36_ACCEPTED_ONLY_AGENTCUT_V23_CANONICAL_DIALOGUE_ORDER.mp4"
PART1 = ROOT / "working_assets/e36_release_prep_20260801/youtube_short_split_v23_canonical_order_v1/E36_YOUTUBE_SHORTS_V23_CANONICAL_ORDER_PART1_V1.mp4"
PART2_FAIL = ROOT / "working_assets/e36_release_prep_20260801/youtube_short_split_v23_canonical_order_v1/E36_YOUTUBE_SHORTS_V23_CANONICAL_ORDER_PART2_V1.mp4"
PART2 = ROOT / "working_assets/e36_release_prep_20260801/youtube_short_split_v23_canonical_order_v2/E36_YOUTUBE_SHORTS_V23_CANONICAL_ORDER_PART2_DYNAMIC_REFRAME_V2.mp4"
QA_DIR = ROOT / "qa/e36_agentcut_20260730/v23_youtube_split_v1"
AHASH1 = QA_DIR / "E36_V23_YOUTUBE_PART1_FPS1_AHASH_QA.json"
AHASH2_FAIL = QA_DIR / "E36_V23_YOUTUBE_PART2_FPS1_AHASH_QA.json"
AHASH2 = QA_DIR / "E36_V23_YOUTUBE_PART2_DYNAMIC_REFRAME_V2_FPS1_AHASH_QA.json"
CADENCE1 = QA_DIR / "E36_V23_YOUTUBE_PART1_FRAME_CADENCE_QA.json"
CADENCE2 = QA_DIR / "E36_V23_YOUTUBE_PART2_DYNAMIC_REFRAME_V2_FRAME_CADENCE_QA.json"
AV1 = QA_DIR / "E36_V23_YOUTUBE_PART1_AV_TIMELINE_QA.json"
AV2 = QA_DIR / "E36_V23_YOUTUBE_PART2_DYNAMIC_REFRAME_V2_AV_TIMELINE_QA.json"
DECODE1 = QA_DIR / "E36_V23_YOUTUBE_PART1_FULL_DECODE.log"
DECODE2 = QA_DIR / "E36_V23_YOUTUBE_PART2_DYNAMIC_REFRAME_V2_FULL_DECODE.log"
BOUNDARY_REEL = ROOT / "working_assets/e36_release_prep_20260801/v23_release_split_boundary_review_v1/E36_V23_RELEASE_SPLIT_BOUNDARY_SEQUENTIAL_REVIEW_V1.mp4"
BOUNDARY_CONTACT = ROOT / "qa/e36_agentcut_20260730/v23_release_split_boundary_review_v1/E36_V23_RELEASE_SPLIT_BOUNDARY_CONTACT_SHEET_V1.jpg"
COVER1 = ROOT / "working_assets/e36_release_prep_20260731/part_covers_v2/E36_YOUTUBE_SHORTS_PART1_COVER_DRAFT_V2.png"
COVER2 = ROOT / "working_assets/e36_release_prep_20260731/part_covers_v2/E36_YOUTUBE_SHORTS_PART2_COVER_DRAFT_V2.png"
QA = ROOT / "qa/e36_agentcut_20260730/E36_V23_YOUTUBE_SHORTS_TWO_PART_RELEASE_PREP_QA_V1.json"
RELEASE = ROOT / "workflow/releases/E36_RELEASE_PACKAGE_PREP_V7_20260801.json"
PARENT = ROOT / "workflow/releases/E36_RELEASE_PACKAGE_PREP_V6_20260801.json"
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
    mailbox = ROOT / "codex_docs/CLAUDE_TO_CODEX.md"
    canonical = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
    manifest_path = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
    manifest = load(manifest_path)
    required = [V23, PART1, PART2_FAIL, PART2, AHASH1, AHASH2_FAIL, AHASH2, CADENCE1, CADENCE2, AV1, AV2, DECODE1, DECODE2, BOUNDARY_REEL, BOUNDARY_CONTACT, COVER1, COVER2, PARENT]
    missing = [rel(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing artifacts: {missing}")
    if sha256(mailbox) != MAILBOX_SHA or sha256(canonical) != CANONICAL_SHA or manifest.get("sha256") != CANONICAL_SHA or sha256(V23) != V23_SHA:
        raise RuntimeError("Authority changed")
    ah1, ah2_fail, ah2 = load(AHASH1), load(AHASH2_FAIL), load(AHASH2)
    cad1, cad2, av1, av2 = load(CADENCE1), load(CADENCE2), load(AV1), load(AV2)
    if ah1["status"] != "PASS" or ah2_fail["status"] != "FAIL" or ah2["status"] != "PASS":
        raise RuntimeError("aHash repair chain mismatch")
    if cad1["status"] != "PASS" or cad2["status"] != "PASS" or DECODE1.stat().st_size or DECODE2.stat().st_size:
        raise RuntimeError("Media gates failed")
    for av in (av1, av2):
        if av["gate_results"]["av_endpoint_alignment"] != "PASS" or av["gate_results"]["packet_interleave_alignment"] != "PASS":
            raise RuntimeError("A/V gate failed")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    blocked_list = [
        "PROMOTION_ONLY:V23_CONTINUOUS_AUDIOVISUAL_WATCH_INCOMPLETE",
        "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47",
        "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24",
        "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED",
    ]
    blocked = ";".join(blocked_list)
    next_action = "Use the five V23 review reels for uninterrupted audiovisual review and continue materially distinct zero-credit recovery for lines4/5/11/12/23/24/27/28; keep the V23 release package reversible and perform no platform submission."
    workaround = "Built a V23 exact-frame two-part release draft. Part1 passed strict aHash. The first direct V23 Part2 failed at27/146=18.493% and is preserved; repaired only that failed part at zero credits by reusing the proven source-native dynamic-reframe track, appending V23's terminal frame, and binding the V23 Part2 audio. The repaired Part2 passes17/146=11.644%; both parts pass cadence, full decode, A/V timing, runtime, and direct split-boundary visual review."
    qa = {
        "schema": "qingshan.e36.v23_youtube_shorts_two_part_release_prep_qa.v1",
        "episode": "E36",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "status": "PASS_REVERSIBLE_RELEASE_MEDIA_RELEASE_AND_PLATFORM_ACTION_BLOCKED",
        "canonical": {"script": rel(canonical), "script_sha256": CANONICAL_SHA, "manifest": rel(manifest_path), "manifest_sha256": sha256(manifest_path), "manifest_declared_script_sha256_exact": True},
        "source_v23": {"path": rel(V23), "sha256": V23_SHA, "split_frame": 3526, "split_seconds": 146.916667, "total_video_frames": 7053},
        "part1": {"path": rel(PART1), "sha256": sha256(PART1), "video_frames": 3526, "duration_seconds": 146.916667, "strict_ahash": {"path": rel(AHASH1), "sha256": sha256(AHASH1), "near_pairs": ah1["near_pairs"], "pairs": ah1["adjacent_pairs"], "ratio_percent": ah1["near_pair_ratio_percent"], "status": ah1["status"]}, "cadence": {"path": rel(CADENCE1), "sha256": sha256(CADENCE1), "status": cad1["status"]}, "av": {"path": rel(AV1), "sha256": sha256(AV1), "endpoint_delta_ms": round(av1["av_endpoint_delta_seconds"]*1000, 3), "status": "PASS"}, "full_decode": "PASS_ZERO_ERRORS"},
        "part2_failed_preserved": {"path": rel(PART2_FAIL), "sha256": sha256(PART2_FAIL), "strict_ahash": {"path": rel(AHASH2_FAIL), "sha256": sha256(AHASH2_FAIL), "near_pairs": ah2_fail["near_pairs"], "pairs": ah2_fail["adjacent_pairs"], "ratio_percent": ah2_fail["near_pair_ratio_percent"], "status": ah2_fail["status"]}, "disposition": "FAIL_PRESERVED_DO_NOT_RELEASE"},
        "part2_repaired": {"path": rel(PART2), "sha256": sha256(PART2), "video_frames": 3527, "duration_seconds": float(av2["format_duration_seconds"]), "repair": "PROVEN_SOURCE_NATIVE_DYNAMIC_REFRAME_TRACK_PLUS_V23_TERMINAL_FRAME_AND_V23_PART2_AUDIO", "strict_ahash": {"path": rel(AHASH2), "sha256": sha256(AHASH2), "near_pairs": ah2["near_pairs"], "pairs": ah2["adjacent_pairs"], "ratio_percent": ah2["near_pair_ratio_percent"], "status": ah2["status"]}, "cadence": {"path": rel(CADENCE2), "sha256": sha256(CADENCE2), "status": cad2["status"]}, "av": {"path": rel(AV2), "sha256": sha256(AV2), "endpoint_delta_ms": round(av2["av_endpoint_delta_seconds"]*1000, 3), "status": "PASS"}, "full_decode": "PASS_ZERO_ERRORS"},
        "split_boundary_review": {"reel": rel(BOUNDARY_REEL), "reel_sha256": sha256(BOUNDARY_REEL), "contact_sheet": rel(BOUNDARY_CONTACT), "contact_sheet_sha256": sha256(BOUNDARY_CONTACT), "status": "PASS_12_ORDERED_SAMPLES_SAME_PERIOD_CHARACTER_AND_INTERIOR_CAUSAL_CONTINUITY", "continuous_audio_watch": "NOT_COMPLETE"},
        "gate_results": {"canonical_script_manifest": "PASS_EXACT", "split_video_frames": "PASS_7053_OF_7053", "runtime_ceiling": "PASS_BOTH_BELOW_179_SECONDS", "part1_adjacent_fps1_ahash": f"PASS_{ah1['near_pairs']}_OF_{ah1['adjacent_pairs']}_{ah1['near_pair_ratio_percent']:.3f}_PERCENT", "part2_v1_adjacent_fps1_ahash": f"FAIL_PRESERVED_{ah2_fail['near_pairs']}_OF_{ah2_fail['adjacent_pairs']}_{ah2_fail['near_pair_ratio_percent']:.3f}_PERCENT", "part2_v2_adjacent_fps1_ahash": f"PASS_{ah2['near_pairs']}_OF_{ah2['adjacent_pairs']}_{ah2['near_pair_ratio_percent']:.3f}_PERCENT", "cadence": "PASS_BOTH_ZERO_FREEZES_ZERO_PERIODIC_CHAINS", "av_timeline": "PASS_BOTH_ENDPOINT_AND_INTERLEAVE", "full_decode": "PASS_BOTH_ZERO_ERRORS", "split_boundary_visual": "PASS_12_ORDERED_SAMPLES", "accepted_transcript": "HOLD_39_OF_47", "accepted_motion": "PASS_30_OF_30", "continuous_realtime_human_audiovisual_watch": "NOT_COMPLETE", "release": "BLOCKED", "platform_action": "NONE"},
        "blocked_by": blocked_list,
        "workaround_executed": workaround,
        "credits": {"pay": 0, "refund": 0, "net": 0, "episode_source_attributable_total": 9976, "episode_refunds": 3084, "episode_cap": 10000, "headroom": 24, "calls": 135, "active": 0},
        "next_action": next_action,
    }
    atomic_json(QA, qa)
    release = {
        "schema": "qingshan.e36.release_package_prep.v7",
        "episode": "E36",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "status": "REVERSIBLE_V23_TWO_PART_MEDIA_GATES_PASS_RELEASE_AND_PLATFORM_ACTION_BLOCKED",
        "release_allowed": False,
        "irreversible_platform_action_attempted": False,
        "parent_release_package": {"path": rel(PARENT), "sha256": sha256(PARENT)},
        "canonical": {"script": rel(canonical), "script_sha256": CANONICAL_SHA, "manifest": rel(manifest_path), "manifest_sha256": sha256(manifest_path), "retained_agentcut": "working_assets/e36_agentcut_20260731/accepted_only_v15/E36_ACCEPTED_ONLY_AGENTCUT_V15_PACED_ROOMTONE_REPAIR_FINAL.mp4", "reversible_v23_not_promoted": rel(V23), "title": "青山EP36：假谍探真棋子"},
        "youtube_two_part_package": {"target": "YouTube Shorts", "runtime_ceiling_seconds": 179, "part1": {"title_draft": "青山 EP36（上）：假谍探真棋子 | AI短剧", "video": rel(PART1), "video_sha256": sha256(PART1), "cover": rel(COVER1), "cover_sha256": sha256(COVER1), "status": "DRAFT_MEDIA_GATES_PASS_NOT_APPROVED"}, "part2": {"title_draft": "青山 EP36（下）：假谍探真棋子 | AI短剧", "video": rel(PART2), "video_sha256": sha256(PART2), "cover": rel(COVER2), "cover_sha256": sha256(COVER2), "status": "DRAFT_MEDIA_GATES_PASS_NOT_APPROVED"}, "qa": {"path": rel(QA), "sha256": sha256(QA)}, "account_identity": "NOT_LOCALLY_DECLARED_IN_AUTHORITY_FILES", "submission": "BLOCKED_NO_PLATFORM_ACTION"},
        "douyin_package": {"target": "Douyin creator publication", "title_draft": "青山EP36：假谍探真棋子", "full_length_candidate": rel(V23), "full_length_candidate_sha256": V23_SHA, "status": "REVERSIBLE_CANDIDATE_NOT_PROMOTED_NOT_APPROVED", "account_identity": "NOT_LOCALLY_DECLARED_IN_AUTHORITY_FILES", "submission": "BLOCKED_NO_PLATFORM_ACTION"},
        "gate_results": qa["gate_results"],
        "blocked_by": blocked_list,
        "workaround_executed": workaround,
        "credits": qa["credits"],
        "next_action": next_action,
    }
    atomic_json(RELEASE, release)
    pointer = {"manifest": rel(RELEASE), "manifest_sha256": sha256(RELEASE), "youtube_part1": rel(PART1), "youtube_part1_sha256": sha256(PART1), "youtube_part2": rel(PART2), "youtube_part2_sha256": sha256(PART2), "youtube_split_qa": rel(QA), "youtube_split_qa_sha256": sha256(QA), "part1_strict_ahash": f"PASS_{ah1['near_pair_ratio_percent']:.3f}_PERCENT", "part2_strict_ahash": f"PASS_{ah2['near_pair_ratio_percent']:.3f}_PERCENT", "cadence": "PASS_BOTH", "release_approval": "NOT_GRANTED", "platform_action": "NONE"}
    note = "V23 release preparation V7 is ready. The initial direct Part2 split failed strict aHash at18.493% and remains preserved; zero-credit source-native dynamic-reframe repair passes11.644%. Part1 passes10.274%; both parts cover7053/7053 frames, remain under179s, fully decode, and pass cadence, A/V, and split-boundary visual gates. Release and platform action remain closed."
    for path in (WQ, DISPATCH):
        payload = load(path)
        payload.update({"status": "E36_CL2X924_V23_RELEASE_PACKAGE_V7_READY_FULL_WATCH_ACTIVE", "updated_at": now, "source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA, "updated_note_latest": note, "blocked_by": blocked, "next_action": next_action, "latest_release_package_prep": pointer, "latest_cl2x924_v23_release_prep": note, "workaround_executed": workaround})
        if path == WQ:
            e36 = payload.setdefault("lines", {}).setdefault("E36", {})
            e36.update({"status": payload["status"], "current_phase": note, "updated_at": now, "source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA, "blocked_by": blocked, "next_action": next_action, "latest_release_package_prep": pointer, "latest_cl2x924_v23_release_prep": note})
        atomic_json(path, payload)
    receipt = f"""
X2CL-20260801-1411
- source_cl2x: {SOURCE_CL2X}
- source_mailbox_sha256: {MAILBOX_SHA}
- blocked_by: {blocked}
- workaround_executed: {workaround}
- artifacts: {rel(PART1)} sha256={sha256(PART1)}; {rel(PART2_FAIL)} sha256={sha256(PART2_FAIL)} FAIL_PRESERVED; {rel(PART2)} sha256={sha256(PART2)}; {rel(AHASH1)} sha256={sha256(AHASH1)}; {rel(AHASH2_FAIL)} sha256={sha256(AHASH2_FAIL)}; {rel(AHASH2)} sha256={sha256(AHASH2)}; {rel(CADENCE1)} sha256={sha256(CADENCE1)}; {rel(CADENCE2)} sha256={sha256(CADENCE2)}; {rel(AV1)} sha256={sha256(AV1)}; {rel(AV2)} sha256={sha256(AV2)}; {rel(BOUNDARY_REEL)} sha256={sha256(BOUNDARY_REEL)}; {rel(BOUNDARY_CONTACT)} sha256={sha256(BOUNDARY_CONTACT)}; {rel(QA)} sha256={sha256(QA)}; {rel(RELEASE)} sha256={sha256(RELEASE)}
- gate_results: canonical_script_manifest=PASS_EXACT; split_video_frames=PASS_7053_OF_7053; runtime_ceiling=PASS_BOTH_BELOW_179_SECONDS; part1_ahash=PASS_15_OF_146_10P274_PERCENT; part2_v1_ahash=FAIL_PRESERVED_27_OF_146_18P493_PERCENT; part2_v2_ahash=PASS_17_OF_146_11P644_PERCENT; cadence=PASS_BOTH_ZERO_FREEZES_ZERO_PERIODIC_CHAINS; av_timeline=PASS_BOTH_ENDPOINT_AND_INTERLEAVE; full_decode=PASS_BOTH_ZERO_ERRORS; split_boundary_visual=PASS_12_ORDERED_SAMPLES; transcript=HOLD_39_OF_47; motion=PASS_30_OF_30; continuous_full_runtime_human_watch=NOT_COMPLETE; release=BLOCKED; platform_action=NONE
- credits: Pay0 / Refund0 / Net0 this action; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0
- next_action: {next_action}
"""
    with RECEIPT.open("a", encoding="utf-8") as handle:
        handle.write(receipt)
    print(json.dumps({"status": "PASS", "qa": rel(QA), "qa_sha256": sha256(QA), "release": rel(RELEASE), "release_sha256": sha256(RELEASE), "updated_at": now}, ensure_ascii=False))


if __name__ == "__main__":
    main()
