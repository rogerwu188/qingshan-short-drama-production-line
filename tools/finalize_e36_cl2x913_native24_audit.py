#!/usr/bin/env python3
"""Register CL2X-913 native-rate hotspot attribution without promoting V19."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "qa/e36_agentcut_20260730/E36_V19_HOTSPOT_NATIVE_24FPS_MOTION_ATTRIBUTION_V1.json"
REEL_QA = ROOT / "qa/e36_agentcut_20260730/E36_V19_MAPPED_HIGH_MOTION_REALTIME_REEL_QA_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPTS = ROOT / "workflow/CODEX_TO_CLAUDE.md"
SOURCE_CL2X = "CL2X-913"
MAILBOX_SHA = "6e4678c691873227857cbbe804617d64930b1df18e79d1039174e11ddb6b4632"
BLOCKED = (
    "PROMOTION_ONLY:V19_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;"
    "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08;"
    "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
    "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    audit = load(AUDIT)
    aggregate = audit["aggregate"]
    now = datetime.now(timezone.utc).isoformat()
    workaround = (
        "Consumed CL2X-913 and bypassed the quarter-second contact-sheet aliasing with a native 24fps "
        "interframe attribution over all eight inherited high-motion hotspots: 760 within-window frame pairs, "
        f"751 reliable ({aggregate['reliable_pair_ratio']:.3%}), with mapped V19-minus-V18C residual p95 "
        f"{aggregate['excess_translation_px_at_180x320']['p95']:.3f}px at 180x320. This narrows V19 assembly "
        "risk but does not clear inherited V18C subjective comfort or the uninterrupted full-runtime watch."
    )
    next_action = (
        "Extend native-rate motion attribution from the eight worst hotspots to the remaining V19 timeline, "
        "then use the full-speed reels for uninterrupted human audiovisual review; in parallel continue "
        "zero-credit recovery for lines4/5/11/12/23/24/27/28 and U08 while V19 remains unpromoted."
    )
    queue = load(QUEUE)
    queue.update({
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "updated_at": now,
        "status": "E36_V19_NATIVE24_HOTSPOT_ATTRIBUTION_PASS_FULL_WATCH_ACTIVE",
        "latest_v19_native24_hotspot_motion_audit": str(AUDIT.relative_to(ROOT)),
        "latest_v19_native24_hotspot_motion_audit_sha256": sha256(AUDIT),
        "blocked_by": BLOCKED,
        "next_action": next_action,
    })
    dump(QUEUE, queue)
    dispatch = load(DISPATCH)
    dispatch.update({
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "generated_at": now,
        "blocked_by": BLOCKED,
        "workaround_executed": workaround,
        "next_action": next_action,
    })
    dispatch.setdefault("execution", {})["latest_v19_native24_hotspot_motion_audit"] = {
        "path": str(AUDIT.relative_to(ROOT)),
        "sha256": sha256(AUDIT),
        "status": "PASS_751_OF_760_RELIABLE_FULL_WATCH_HOLD",
    }
    dispatch["execution"]["last_real_progress"] = workaround
    dispatch["execution"]["status"] = "CL2X-913_V19_NATIVE24_HOTSPOT_ATTRIBUTION_PASS_REVERSIBLE_NOT_PROMOTED"
    dump(DISPATCH, dispatch)
    queue_sha, dispatch_sha = sha256(QUEUE), sha256(DISPATCH)
    receipt = f"""

# [X2CL-20260731-2229] E36 V19 native-24fps hotspot motion attribution
- source_cl2x: `{SOURCE_CL2X}`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{BLOCKED}`
- workaround_executed: `{workaround}`
- artifacts: `{AUDIT.relative_to(ROOT)}` sha256=`{sha256(AUDIT)}`; `{REEL_QA.relative_to(ROOT)}` sha256=`{sha256(REEL_QA)}`; `tools/audit_e36_v19_hotspot_native_rate_motion.py` sha256=`{sha256(ROOT / 'tools/audit_e36_v19_hotspot_native_rate_motion.py')}`; `workflow/work_queue.json` sha256=`{queue_sha}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{dispatch_sha}`
- gate_results: `canonical:PASS_EXACT;native_rate:PASS_24FPS_760_PAIRS;reliable_attribution:PASS_751_OF_760;quarter_second_aliasing:BYPASSED_AT_1_OVER_24_SECOND;V19_minus_mapped_V18C_residual_p95:0P714PX_AT_180X320;inherited_V18C_subjective_comfort:HOLD;continuous_full_runtime_watch:NOT_COMPLETE;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;promotion:NOT_YET;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
    with RECEIPTS.open("a", encoding="utf-8") as f:
        f.write(receipt)
    print(json.dumps({"queue_sha256": queue_sha, "dispatch_sha256": dispatch_sha, "receipt_file_sha256": sha256(RECEIPTS)}))


if __name__ == "__main__":
    main()
