#!/usr/bin/env python3
"""Record V19 full A/V timing and 48-source chain-of-custody QA."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now().astimezone().isoformat(timespec="seconds")
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPTS = ROOT / "workflow/CODEX_TO_CLAUDE.md"
V19_QA = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10_QA_V1.json"
AV = ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v19_runtime/E36_ACCEPTED_ONLY_AGENTCUT_V19_FULL_AV_TIMELINE_AUDIT_V1.json"
CHAIN = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_PACKAGE_48_SOURCE_CHAIN_OF_CUSTODY_INTEGRITY_QA_V4.json"
TSV = ROOT / "qa/e36_agentcut_20260730/accepted_package_chain_of_custody_20260731/E36_ACCEPTED_PACKAGE_48_SOURCE_CHAIN_OF_CUSTODY_EVIDENCE_V4.tsv"
V19 = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v19_v18c_plus_line10/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10.mp4"
AV_TOOL = ROOT / "tools/audit_e36_v18c_av_timeline.py"
CHAIN_TOOL = ROOT / "tools/audit_e36_accepted_package_chain_v4.py"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


av = load(AV)
chain = load(CHAIN)
if any(value == "FAIL" for value in av["gate_results"].values()):
    raise SystemExit("V19 A/V timeline audit contains a failed gate")
if chain["status"] != "PASS_48_SOURCE_ACCEPTED_PACKAGE_CHAIN_OF_CUSTODY":
    raise SystemExit("48-source chain-of-custody audit is not PASS")

blocked = (
    "PROMOTION_ONLY:V19_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;"
    "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08;"
    "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
    "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
)
next_action = (
    "Continue the uninterrupted 288.911-second V19 audiovisual watch with special attention to the inserted line10 boundaries, visible lipsync, "
    "action causality, identity, period, evidence visibility and reframe comfort. In parallel continue zero-credit U08 motion and remaining-line recovery."
)
progress = (
    "Ran two new full-package zero-credit audits on V19. Packet-level A/V timing passed monotonic decode timelines, contiguous presentation, "
    "36.646ms endpoint alignment and 10.667ms maximum video-to-nearest-audio PTS offset. Independently recomputed all48 accepted media and QA "
    "hashes plus every accepted-only timeline interval: 48/48 media and QA bindings exact, 48 unique media, zero aliases, zero timeline gaps and "
    "zero duration mismatches. The continuous human watch, transcript39/47 and motion29/30 holds remain intact."
)

qa = load(V19_QA)
qa["objective_qa"]["full_av_timeline"] = {
    "path": rel(AV),
    "sha256": sha(AV),
    "video_packets": av["video_packets"]["packet_count"],
    "audio_packets": av["audio_packets"]["packet_count"],
    "av_endpoint_delta_seconds": av["av_endpoint_delta_seconds"],
    "max_video_to_nearest_audio_pts_offset_seconds": av["video_to_nearest_audio_pts_offset_seconds"]["max"],
    "status": "PASS",
}
qa["accepted_only_binding"]["chain_of_custody"] = {
    "path": rel(CHAIN),
    "sha256": sha(CHAIN),
    "evidence_tsv": rel(TSV),
    "evidence_tsv_sha256": sha(TSV),
    "status": chain["status"],
}
qa["gate_results"]["full_av_timeline"] = "PASS_DTS_MONOTONIC_PRESENTATION_CONTIGUOUS_ENDPOINT_36P646MS_MAX_PTS_OFFSET_10P667MS"
qa["gate_results"]["accepted_package_chain_of_custody"] = "PASS_48_OF_48_MEDIA_AND_QA_SHA_EXACT_ZERO_TIMELINE_GAPS"
qa["workaround_executed"] = progress
qa["blocked_by"] = blocked
qa["next_action"] = next_action
write(V19_QA, qa)

queue = load(QUEUE)
queue.update({
    "updated_at": NOW,
    "status": "E36_V19_OBJECTIVE_MEDIA_AND_48_SOURCE_INTEGRITY_PASS_CONTINUOUS_WATCH_ACTIVE",
    "blocked_by": blocked,
    "next_action": next_action,
    "latest_v19_full_av_timeline_audit": rel(AV),
    "latest_v19_full_av_timeline_audit_sha256": sha(AV),
    "latest_accepted_package_chain_of_custody_qa": rel(CHAIN),
    "latest_accepted_package_chain_of_custody_qa_sha256": sha(CHAIN),
    "latest_reversible_agentcut_candidate_qa_sha256": sha(V19_QA),
    "updated_note_latest": progress,
})
queue["lines"]["E36"].update({
    "status": "V19_OBJECTIVE_AND_48_SOURCE_INTEGRITY_PASS_CONTINUOUS_WATCH_AND_GAP_REPAIR_ACTIVE",
    "current_phase": progress,
    "blocked_by": blocked,
    "next_action": next_action,
    "latest_cl2x908_v19_integrity": progress,
})
write(QUEUE, queue)

dispatch = load(DISPATCH)
dispatch.update({"generated_at": NOW, "blocked_by": blocked, "workaround_executed": progress, "next_action": next_action})
execution = dispatch["execution"]
execution.update({
    "status": "V19_OBJECTIVE_AND_48_SOURCE_INTEGRITY_PASS_REVERSIBLE_NOT_PROMOTED",
    "active_task_count": 0,
    "latest_v19_full_av_timeline_audit": rel(AV),
    "latest_v19_full_av_timeline_audit_sha256": sha(AV),
    "latest_accepted_package_chain_of_custody_qa": rel(CHAIN),
    "latest_accepted_package_chain_of_custody_qa_sha256": sha(CHAIN),
    "latest_reversible_agentcut_qa_sha256": sha(V19_QA),
    "last_real_progress": progress,
})
dispatch.setdefault("subsequent_attempts", {})["v19_full_av_and_48_source_integrity"] = {
    "source_cl2x": "CL2X-908",
    "status": "PASS_ZERO_CREDIT_FULL_PACKAGE_INTEGRITY_QA",
    "media": rel(V19), "media_sha256": sha(V19),
    "av_timeline_audit": rel(AV), "av_timeline_audit_sha256": sha(AV),
    "chain_of_custody_qa": rel(CHAIN), "chain_of_custody_qa_sha256": sha(CHAIN),
    "evidence_tsv": rel(TSV), "evidence_tsv_sha256": sha(TSV),
    "credits": {"pay": 0, "refund": 0, "net": 0},
}
write(DISPATCH, dispatch)

receipt = f"""

# [X2CL-20260731-2126] E36 V19 full A/V timeline and 48-source chain-of-custody audits pass
- source_cl2x: `CL2X-908`; source_mailbox_sha256=`638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041`
- blocked_by: `{blocked}`
- workaround_executed: `{progress}`
- artifacts: `{rel(AV_TOOL)}` sha256=`{sha(AV_TOOL)}`; `{rel(AV)}` sha256=`{sha(AV)}`; `{rel(CHAIN_TOOL)}` sha256=`{sha(CHAIN_TOOL)}`; `{rel(CHAIN)}` sha256=`{sha(CHAIN)}`; `{rel(TSV)}` sha256=`{sha(TSV)}`; `{rel(V19_QA)}` sha256=`{sha(V19_QA)}`; `workflow/work_queue.json` sha256=`{sha(QUEUE)}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{sha(DISPATCH)}`
- gate_results: `canonical_script_manifest:PASS_EXACT;V19_media_sha:PASS;V19_video_packets:PASS_6896;V19_audio_packets:PASS_13613;V19_DTS:PASS_BOTH_MONOTONIC;V19_presentation_timeline:PASS_BOTH_CONTIGUOUS;V19_AV_endpoint:PASS_36P646MS;V19_packet_interleave:PASS_MAX_10P667MS;accepted_media:PASS_48_OF_48_SHA_EXACT;accepted_QA:PASS_48_OF_48_SHA_EXACT;accepted_media_uniqueness:PASS_48;timeline:PASS_ZERO_GAPS_ZERO_DURATION_MISMATCHES;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;continuous_watch:NOT_COMPLETE;promotion:NOT_YET;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
with RECEIPTS.open("a", encoding="utf-8") as handle:
    handle.write(receipt)

print(json.dumps({"v19_qa_sha256": sha(V19_QA), "queue_sha256": sha(QUEUE), "dispatch_sha256": sha(DISPATCH), "receipt_file_sha256": sha(RECEIPTS)}, ensure_ascii=False))
