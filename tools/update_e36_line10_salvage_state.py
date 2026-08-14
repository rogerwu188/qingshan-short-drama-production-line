#!/usr/bin/env python3
"""Record the E36 line-10 salvage heartbeat in local shared state."""

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
V16_QA = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V16_LINE10_ZERO_CREDIT_SALVAGE_QA_V1.json"
CADENCE = ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v16_line10_salvage_runtime/E36_ACCEPTED_ONLY_AGENTCUT_V16_FRAME_CADENCE_QA.json"
AHASH = ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v16_line10_salvage_runtime/E36_ACCEPTED_ONLY_AGENTCUT_V16_FPS1_ADJACENT_AHASH_QA.json"
V16 = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v16_line10_salvage/E36_ACCEPTED_ONLY_AGENTCUT_V16_LINE10_ZERO_CREDIT_SALVAGE.mp4"
DIRECT = ROOT / "qa/e36_agentcut_20260730/E36_U09_LINE10_ZERO_CREDIT_NATIVE_SALVAGE_DIRECT_QA_V2.json"
SALVAGE = ROOT / "qa/e36_agentcut_20260730/E36_UNADMITTED_NATIVE_VIDEO_SALVAGE_AUDIT_V1.json"
MAP = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V10.json"
TRANSCRIPT = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V14.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


blocked = (
    "RELEASE_ONLY:V16_ADJACENT_FPS1_AHASH_51P042_PERCENT_GT15;"
    "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08;"
    "RELEASE_ONLY:V16_CONTINUOUS_AUDIOVISUAL_WATCH_INCOMPLETE;"
    "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
    "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
)
next_action = (
    "Preserve the new line10 admission and V16. Localize V16 fps1 aHash static runs for reversible source-native repair, "
    "continue zero-credit U08 motion recovery and mine the remaining eight transcript gaps; run continuous V16 watch before promotion."
)
progress = (
    "Consumed CL2X-908 and exhaustively ran unconditioned small-model ASR over all61 local unadmitted E36 recovery MP4s. "
    "This recovered exact model-native canonical line10 in three clips; the visually clean changed-W3 messenger take then passed10/12 "
    "unconditioned base/small decodes exact and the authorized line10 manual-listening exception, while prior direct visible lips/breath/identity/period gates remained PASS. "
    "Admitted line10 at zero credits, advanced accepted transcript38/47 to39/47 and sources47 to48, built reversible V16, fully decoded it, "
    "and ran cadence PASS plus strict fps1 aHash FAIL51.042% without waiving the release hold."
)

v16_qa = load(V16_QA)
v16_qa["frame_cadence_qa"] = {"path": rel(CADENCE), "sha256": sha(CADENCE), "status": load(CADENCE)["status"]}
v16_qa["fps1_adjacent_ahash_qa"] = {"path": rel(AHASH), "sha256": sha(AHASH), "status": "FAIL", "near_pairs": 147, "adjacent_pairs": 288, "ratio_percent": 51.042}
v16_qa["gate_results"]["frame_cadence"] = "PASS_ZERO_FREEZE_OR_PERIODIC_DUPLICATE_FAILURES"
v16_qa["gate_results"]["strict_fps1_adjacent_ahash"] = "FAIL_147_OF_288_51P042_PERCENT_GT15"
v16_qa["gate_results"]["direct_24_sample_full_span_visual"] = "PASS_IDENTITY_PERIOD_PROP_AND_NO_INCOHERENT_OVERLAP"
v16_qa["blocked_by"] = blocked
v16_qa["next_action"] = next_action
write(V16_QA, v16_qa)

queue = load(QUEUE)
queue.update({
    "updated_at": NOW, "source_cl2x": "CL2X-908", "source_mailbox_sha256": "638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041",
    "status": "E36_LINE10_ZERO_CREDIT_SALVAGED_TRANSCRIPT_39_OF_47_V16_QA_ACTIVE", "blocked_by": blocked,
    "next_action": next_action, "real_active_handle_count": 0, "occupied_scope_count": 1,
    "latest_agentcut_candidate": rel(V16), "updated_note_latest": progress,
})
line = queue["lines"]["E36"]
line.update({
    "status": "CONTINUOUS_ZERO_CREDIT_RECOVERY_ACTIVE_LINE10_ADMITTED_V16_QA", "blocked_by": blocked,
    "running_or_pending_task_ids": [], "local_pid": None, "next_action": next_action,
    "latest_cl2x908_line10_zero_credit_salvage": progress,
})
queue["latest_line10_zero_credit_salvage_qa"] = rel(DIRECT)
queue["latest_unadmitted_native_video_salvage_audit"] = rel(SALVAGE)
queue["latest_agentcut_v16_line10_salvage_qa"] = rel(V16_QA)
write(QUEUE, queue)

dispatch = load(DISPATCH)
dispatch.update({
    "generated_at": NOW, "source_cl2x": "CL2X-908", "source_mailbox_sha256": "638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041",
    "blocked_by": blocked, "workaround_executed": progress, "next_action": next_action,
})
execution = dispatch["execution"]
execution.update({
    "status": "LINE10_ZERO_CREDIT_SALVAGED_TRANSCRIPT_39_OF_47_V16_QA_ACTIVE", "active_task_count": 0,
    "accepted_transcript_coverage": "39/47", "accepted_motion_coverage": "29/30", "accepted_source_count": 48,
    "latest_accepted_only_source_map": rel(MAP), "latest_accepted_only_source_map_sha256": sha(MAP),
    "latest_transcript_audit": rel(TRANSCRIPT), "latest_transcript_audit_sha256": sha(TRANSCRIPT),
    "latest_unadmitted_native_video_salvage_audit": rel(SALVAGE), "latest_unadmitted_native_video_salvage_audit_sha256": sha(SALVAGE),
    "latest_line10_zero_credit_direct_qa": rel(DIRECT), "latest_line10_zero_credit_direct_qa_sha256": sha(DIRECT),
    "latest_agentcut_candidate": rel(V16), "latest_agentcut_candidate_sha256": sha(V16),
    "latest_agentcut_assembly_qa": rel(V16_QA), "latest_agentcut_assembly_qa_sha256": sha(V16_QA),
    "latest_agentcut_frame_cadence_qa": rel(CADENCE), "latest_agentcut_frame_cadence_qa_sha256": sha(CADENCE),
    "latest_agentcut_adjacent_fps1_qa": rel(AHASH), "latest_agentcut_adjacent_fps1_qa_sha256": sha(AHASH),
    "latest_agentcut_adjacent_fps1_ratio": 0.51042, "last_real_progress": progress,
})
dispatch.setdefault("subsequent_attempts", {})["line10_zero_credit_native_salvage"] = {
    "source_cl2x": "CL2X-908", "status": "PASS_ADMITTED_LINE10_V16_RENDERED_QA_ACTIVE",
    "salvage_audit": rel(SALVAGE), "salvage_audit_sha256": sha(SALVAGE),
    "direct_qa": rel(DIRECT), "direct_qa_sha256": sha(DIRECT), "media": rel(V16), "media_sha256": sha(V16),
    "source_map": rel(MAP), "source_map_sha256": sha(MAP), "transcript_audit": rel(TRANSCRIPT), "transcript_audit_sha256": sha(TRANSCRIPT),
    "credits": {"pay": 0, "refund": 0, "net": 0},
}
write(DISPATCH, dispatch)

receipt = f"""

# [X2CL-20260731-2107] E36 line10 zero-credit source-native salvage admitted; transcript39/47; V16 rendered and objectively gated
- source_cl2x: `CL2X-908`; source_mailbox_sha256=`638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041`
- blocked_by: `{blocked}`
- workaround_executed: `{progress}`
- artifacts: `{rel(SALVAGE)}` sha256=`{sha(SALVAGE)}`; `{rel(DIRECT)}` sha256=`{sha(DIRECT)}`; `{rel(MAP)}` sha256=`{sha(MAP)}`; `{rel(TRANSCRIPT)}` sha256=`{sha(TRANSCRIPT)}`; `{rel(V16)}` sha256=`{sha(V16)}`; `{rel(V16_QA)}` sha256=`{sha(V16_QA)}`; `{rel(CADENCE)}` sha256=`{sha(CADENCE)}`; `{rel(AHASH)}` sha256=`{sha(AHASH)}`; `workflow/work_queue.json` sha256=`{sha(QUEUE)}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{sha(DISPATCH)}`
- gate_results: `canonical_sha:PASS;manifest_sha:PASS;local_unadmitted_scan:PASS_61_MP4;line10_native_video_asr:PASS_10_OF_12_EXACT_WITH_AUTHORIZED_MANUAL_LISTENING_EXCEPTION;line10_visible_lips_breath_identity_period:PASS;accepted_sources:PASS_48;accepted_transcript:FAIL_39_OF_47;motion:FAIL_29_OF_30_U08;V16_full_decode:PASS_ZERO_ERRORS;V16_frame_cadence:PASS;V16_fps1_aHash:FAIL_147_OF_288_51P042_PERCENT_GT15;continuous_watch:HOLD;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
with RECEIPTS.open("a", encoding="utf-8") as handle:
    handle.write(receipt)

print(json.dumps({"queue_sha256": sha(QUEUE), "dispatch_sha256": sha(DISPATCH), "receipt_file_sha256": sha(RECEIPTS), "v16_qa_sha256": sha(V16_QA)}, ensure_ascii=False))
