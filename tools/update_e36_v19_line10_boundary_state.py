#!/usr/bin/env python3
"""Record V19's focused line-10 insertion-boundary review."""

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
BOUNDARY_QA = ROOT / "qa/e36_agentcut_20260730/E36_V19_LINE10_INSERTION_BOUNDARY_ASR_AND_VISUAL_QA_V1.json"
RUNTIME = ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v19_line10_boundary_runtime"
REEL = RUNTIME / "E36_V19_LINE10_BOUNDARY_REVIEW_REEL_V1.mp4"
SHEET = RUNTIME / "E36_V19_LINE10_BOUNDARY_CONTACT_SHEET_V1.jpg"
PROBE = RUNTIME / "E36_V19_LINE10_BOUNDARY_PROBE_V1.json"
DECODE = RUNTIME / "E36_V19_LINE10_BOUNDARY_DECODE_V1.log"
TOOL = ROOT / "tools/audit_e36_v19_line10_boundary_asr.py"


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


boundary = load(BOUNDARY_QA)
if boundary["status"] != "PASS_LINE10_INSERTION_BOUNDARY_QA_RELEASE_HOLDS_PRESERVED":
    raise SystemExit("line10 boundary QA did not pass")
if DECODE.stat().st_size:
    raise SystemExit("line10 boundary review reel decode log is non-empty")

blocked = (
    "PROMOTION_ONLY:V19_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;"
    "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08;"
    "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
    "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
)
next_action = (
    "Continue V19 audiovisual review outside the now-focused-and-passed line10 boundary window. Prioritize the unresolved transcript transition "
    "after line10, rights-cleared lines11/12/27, U08 motion, and lines4/5/23/24/28 while preserving V19 as an unpromoted reversible candidate."
)
progress = (
    "Cut and fully decoded an 11.083-second V19 review reel spanning two seconds before and three seconds after the inserted line10, rendered a "
    "16-frame contact sheet, and directly reviewed the transition. The same period messenger remains visible with active mouth and expression, "
    "with coherent framing and no modern intrusion. Twelve unconditioned base/small ASR decodes preserved line10 exactly in all6 small-model runs "
    "and 6/12 overall; the authorized line10 listening exception and prior source-native 10/12 authority remain scoped. Accepted sequence anchors "
    "were ordered in the six exact line10 decodes. Missing canonical lines11/12 remain an explicit transcript hold rather than being masked."
)

qa = load(V19_QA)
qa["focused_line10_boundary_qa"] = {
    "path": rel(BOUNDARY_QA), "sha256": sha(BOUNDARY_QA),
    "review_reel": rel(REEL), "review_reel_sha256": sha(REEL),
    "contact_sheet": rel(SHEET), "contact_sheet_sha256": sha(SHEET),
    "status": boundary["status"],
}
qa["gate_results"]["line10_insertion_boundary"] = "PASS_FULL_DECODE_DIRECT_VISUAL_SMALL_ASR_6_OF_6_EXACT_AUTHORIZED_EXCEPTION_RETAINED"
qa["gate_results"]["post_line10_missing_canonical_lines_11_12"] = "HOLD_PRESERVED_IN_TRANSCRIPT_39_OF_47"
qa["workaround_executed"] = progress
qa["blocked_by"] = blocked
qa["next_action"] = next_action
write(V19_QA, qa)

queue = load(QUEUE)
queue.update({
    "updated_at": NOW,
    "status": "E36_V19_LINE10_BOUNDARY_PASS_CONTINUOUS_WATCH_AND_GAP_REPAIR_ACTIVE",
    "blocked_by": blocked,
    "next_action": next_action,
    "latest_v19_line10_boundary_qa": rel(BOUNDARY_QA),
    "latest_v19_line10_boundary_qa_sha256": sha(BOUNDARY_QA),
    "latest_reversible_agentcut_candidate_qa_sha256": sha(V19_QA),
    "updated_note_latest": progress,
})
queue["lines"]["E36"].update({
    "status": "V19_LINE10_BOUNDARY_PASS_FULL_WATCH_AND_ZERO_CREDIT_GAP_REPAIR_ACTIVE",
    "current_phase": progress,
    "blocked_by": blocked,
    "next_action": next_action,
    "latest_cl2x908_v19_line10_boundary_review": progress,
})
write(QUEUE, queue)

dispatch = load(DISPATCH)
dispatch.update({"generated_at": NOW, "blocked_by": blocked, "workaround_executed": progress, "next_action": next_action})
dispatch["execution"].update({
    "status": "V19_LINE10_BOUNDARY_PASS_REVERSIBLE_NOT_PROMOTED",
    "active_task_count": 0,
    "latest_v19_line10_boundary_qa": rel(BOUNDARY_QA),
    "latest_v19_line10_boundary_qa_sha256": sha(BOUNDARY_QA),
    "latest_reversible_agentcut_qa_sha256": sha(V19_QA),
    "last_real_progress": progress,
})
dispatch.setdefault("subsequent_attempts", {})["v19_line10_focused_boundary_review"] = {
    "source_cl2x": "CL2X-908", "status": boundary["status"],
    "review_reel": rel(REEL), "review_reel_sha256": sha(REEL),
    "contact_sheet": rel(SHEET), "contact_sheet_sha256": sha(SHEET),
    "probe": rel(PROBE), "probe_sha256": sha(PROBE),
    "decode_log": rel(DECODE), "decode_log_sha256": sha(DECODE),
    "qa": rel(BOUNDARY_QA), "qa_sha256": sha(BOUNDARY_QA),
    "credits": {"pay": 0, "refund": 0, "net": 0},
}
write(DISPATCH, dispatch)

receipt = f"""

# [X2CL-20260731-2133] E36 V19 line10 insertion-boundary focused media and ASR review passes
- source_cl2x: `CL2X-908`; source_mailbox_sha256=`638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041`
- blocked_by: `{blocked}`
- workaround_executed: `{progress}`
- artifacts: `{rel(REEL)}` sha256=`{sha(REEL)}`; `{rel(SHEET)}` sha256=`{sha(SHEET)}`; `{rel(PROBE)}` sha256=`{sha(PROBE)}`; `{rel(DECODE)}` sha256=`{sha(DECODE)}`; `{rel(TOOL)}` sha256=`{sha(TOOL)}`; `{rel(BOUNDARY_QA)}` sha256=`{sha(BOUNDARY_QA)}`; `{rel(V19_QA)}` sha256=`{sha(V19_QA)}`; `workflow/work_queue.json` sha256=`{sha(QUEUE)}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{sha(DISPATCH)}`
- gate_results: `canonical_script_manifest:PASS_EXACT;focused_reel:PASS_11P083_SECONDS;full_decode:PASS_ZERO_ERRORS;direct_16_frame_visual:PASS_VISIBLE_MOUTH_EXPRESSION_IDENTITY_PERIOD_FRAMING;line10_small_unconditioned_ASR:PASS_6_OF_6_EXACT;line10_all_unconditioned_ASR:PASS_AUTHORIZED_EXCEPTION_6_OF_12_EXACT;source_native_prior_authority:PASS_10_OF_12_EXACT_WITH_SCOPED_EXCEPTION;accepted_sequence_order:PASS_6_EXACT_LINE10_DECODES;post_line10_missing_lines11_12:HOLD_PRESERVED;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;continuous_watch:NOT_COMPLETE;promotion:NOT_YET;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
with RECEIPTS.open("a", encoding="utf-8") as handle:
    handle.write(receipt)

print(json.dumps({"v19_qa_sha256": sha(V19_QA), "queue_sha256": sha(QUEUE), "dispatch_sha256": sha(DISPATCH), "receipt_file_sha256": sha(RECEIPTS)}, ensure_ascii=False))
