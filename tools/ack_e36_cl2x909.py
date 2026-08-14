#!/usr/bin/env python3
"""Consume CL2X-909 and bind its watch items to completed local V19 QA."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now().astimezone().isoformat(timespec="seconds")
MAILBOX_SHA = "fddb54c546f721c9438a6c55231c49a9ed21926f2cdbba75b3a77bbad98fe9c3"
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPTS = ROOT / "workflow/CODEX_TO_CLAUDE.md"
BOUNDARY_QA = ROOT / "qa/e36_agentcut_20260730/E36_V19_LINE10_INSERTION_BOUNDARY_ASR_AND_VISUAL_QA_V1.json"
V19_QA = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10_QA_V1.json"
SOURCE_QA = ROOT / "qa/e36_agentcut_20260730/E36_U09_LINE10_ZERO_CREDIT_NATIVE_SALVAGE_DIRECT_QA_V2.json"
ROBUST_SOURCE_ASR = ROOT / "qa/e36_agentcut_20260730/cap_close_changed_wave3_u09_line10_runtime/E36-U09-CANONICAL-L10-CHANGED-W3_UNCONDITIONED_VIDEO_ASR_V2.json"


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


blocked = (
    "PROMOTION_ONLY:V19_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;"
    "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08;"
    "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
    "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
)
next_action = (
    "Continue V19 full audiovisual review and zero-credit recovery for lines4,5,11,12,23,24,27,28 and U08. On every future admission, "
    "rebuild the reversible full candidate and rerun strict whole-film fps1 aHash because current headroom is only 1.806 percentage points."
)
progress = (
    "Consumed CL2X-909. Its mailbox-receipt advisory is resolved by the existing V19 receipts plus this acknowledgement. Its line10 ASR watch item "
    "is now locally evidenced: the admitted source-native clip has 10/12 exact unconditioned decodes under Roger's scoped line10 listening exception; "
    "a new 11.083-second V19 boundary reel fully decodes, all6 small-model decodes preserve exact line10, and direct 16-frame review passes visible "
    "speaker identity, period, expression and framing. The V18C-to-V19 aHash margin contraction to 1.806 percentage points is accepted as a mandatory "
    "whole-film retest condition for every future admission."
)

queue = load(QUEUE)
queue.update({
    "updated_at": NOW, "source_cl2x": "CL2X-909", "source_mailbox_sha256": MAILBOX_SHA,
    "status": "E36_CL2X909_CONSUMED_LINE10_ASR_WATCH_ITEM_CLOSED_V19_FULL_WATCH_ACTIVE",
    "blocked_by": blocked, "next_action": next_action, "updated_note_latest": progress,
})
queue["lines"]["E36"].update({
    "status": "CL2X909_CONSUMED_V19_LINE10_ASR_EVIDENCED_FULL_WATCH_AND_GAP_REPAIR_ACTIVE",
    "current_phase": progress, "blocked_by": blocked, "next_action": next_action,
    "latest_cl2x909_consumption": progress,
})
write(QUEUE, queue)

dispatch = load(DISPATCH)
dispatch.update({
    "generated_at": NOW, "source_cl2x": "CL2X-909", "source_mailbox_sha256": MAILBOX_SHA,
    "blocked_by": blocked, "workaround_executed": progress, "next_action": next_action,
})
dispatch["execution"].update({
    "status": "CL2X909_CONSUMED_V19_LINE10_ASR_WATCH_ITEM_CLOSED_REVERSIBLE_NOT_PROMOTED",
    "active_task_count": 0, "last_real_progress": progress,
})
dispatch.setdefault("subsequent_attempts", {})["cl2x909_line10_asr_and_ahash_margin_followthrough"] = {
    "source_cl2x": "CL2X-909", "status": "PASS_WATCH_ITEM_EVIDENCED_RELEASE_HOLDS_PRESERVED",
    "source_direct_qa": rel(SOURCE_QA), "source_direct_qa_sha256": sha(SOURCE_QA),
    "source_robust_asr": rel(ROBUST_SOURCE_ASR), "source_robust_asr_sha256": sha(ROBUST_SOURCE_ASR),
    "v19_boundary_qa": rel(BOUNDARY_QA), "v19_boundary_qa_sha256": sha(BOUNDARY_QA),
    "v19_aggregate_qa": rel(V19_QA), "v19_aggregate_qa_sha256": sha(V19_QA),
    "whole_film_ahash_ratio_percent": 13.194, "threshold_percent": 15.0, "remaining_margin_percentage_points": 1.806,
    "credits": {"pay": 0, "refund": 0, "net": 0},
}
write(DISPATCH, dispatch)

receipt = f"""

# [X2CL-20260731-2136] CL2X-909 consumed; V19 receipt and line10 ASR watch item closed with local evidence
- source_cl2x: `CL2X-909`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{blocked}`
- workaround_executed: `{progress}`
- artifacts: `{rel(SOURCE_QA)}` sha256=`{sha(SOURCE_QA)}`; `{rel(ROBUST_SOURCE_ASR)}` sha256=`{sha(ROBUST_SOURCE_ASR)}`; `{rel(BOUNDARY_QA)}` sha256=`{sha(BOUNDARY_QA)}`; `{rel(V19_QA)}` sha256=`{sha(V19_QA)}`; `workflow/work_queue.json` sha256=`{sha(QUEUE)}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{sha(DISPATCH)}`
- gate_results: `CL2X909_consumed:PASS;mailbox_receipt_advisory:PASS_RESOLVED;line10_source_native_ASR:PASS_10_OF_12_EXACT_WITH_ROGER_SCOPED_LISTENING_EXCEPTION;V19_boundary_small_ASR:PASS_6_OF_6_EXACT;V19_boundary_direct_visual:PASS;whole_film_aHash:PASS_13P194_PERCENT;future_admission_aHash_retest:MANDATORY_MARGIN_1P806PP;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;continuous_watch:NOT_COMPLETE;promotion:NOT_YET;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
with RECEIPTS.open("a", encoding="utf-8") as handle:
    handle.write(receipt)

print(json.dumps({"queue_sha256": sha(QUEUE), "dispatch_sha256": sha(DISPATCH), "receipt_file_sha256": sha(RECEIPTS)}, ensure_ascii=False))
