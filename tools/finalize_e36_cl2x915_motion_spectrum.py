#!/usr/bin/env python3
"""Consume CL2X-915 and register the native-rate spectral follow-through."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
SCRIPT_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
AUDIT = ROOT / "qa/e36_agentcut_20260730/E36_V18C_NATIVE24_MOTION_SPECTRUM_DIAGNOSTIC_V1.json"
AUDIT_TOOL = ROOT / "tools/audit_e36_v18c_native24_motion_spectrum.py"
REEL_QA = ROOT / "qa/e36_agentcut_20260730/E36_V19_NATIVE24_WORST_CLUSTER_FULLSCREEN_REEL_QA_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPTS = ROOT / "workflow/CODEX_TO_CLAUDE.md"
SOURCE_CL2X = "CL2X-915"
MAILBOX_SHA = "e62dade34f0da40e44d35d0cf3d58099af66454180f169b6dc020f91a583d620"
CANONICAL_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
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
    assert sha256(CANONICAL) == load(SCRIPT_MANIFEST)["sha256"] == CANONICAL_SHA
    audit = load(AUDIT)
    sampling = audit["sampling"]
    spectrum = audit["aggregate_spectrum"]
    now = datetime.now(timezone.utc).isoformat()
    workaround = (
        "Consumed CL2X-915, preserved its independent PASS on the fullscreen worst-cluster reel, and continued "
        "the exact comfort investigation with a zero-credit full-runtime spectral diagnostic. All 139 overlapping "
        "four-second windows passed reliability admission. The suspected 4Hz/0.25-second component ranks 36th of "
        f"39 bins, at {spectrum['target_power_percentile_in_band']:.3f} power percentile and "
        f"{spectrum['target_to_local_neighbor_median_ratio']:.3f}x local-neighbor median, so a distinct 0.25-second "
        "resonance is not supported. Fullscreen native-speed review remains required for broader low-frequency "
        "drift, fatigue, lipsync and causal continuity."
    )
    next_action = (
        "Perform uninterrupted native-speed review using the verified fullscreen V19 reels, focusing on the "
        "observed low-frequency pan/drift rather than an unsupported exact 4Hz oscillation; concurrently continue "
        "zero-credit recovery for lines4/5/11/12/23/24/27/28 and U08 while V19 remains unpromoted."
    )
    status = "E36_CL2X915_NATIVE24_SPECTRUM_NO_4HZ_RESONANCE_FULL_WATCH_ACTIVE"
    queue = load(QUEUE)
    queue.update({"source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA, "updated_at": now, "updated_note_latest": workaround, "updated_note": workaround, "status": status, "blocked_by": BLOCKED, "next_action": next_action})
    queue["lines"]["E36"].update({"status": status, "current_phase": workaround, "blocked_by": BLOCKED, "next_action": next_action, "latest_cl2x915_motion_spectrum_followthrough": workaround})
    dump(QUEUE, queue)
    dispatch = load(DISPATCH)
    dispatch.update({"source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA, "generated_at": now, "blocked_by": BLOCKED, "workaround_executed": workaround, "next_action": next_action})
    dispatch["execution"]["latest_v18c_native24_motion_spectrum_diagnostic"].update({"source_cl2x_consumed": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA})
    dispatch["execution"]["last_real_progress"] = workaround
    dispatch["execution"]["status"] = "CL2X-915_NATIVE24_SPECTRUM_PASS_REVERSIBLE_NOT_PROMOTED"
    dump(DISPATCH, dispatch)
    queue_sha, dispatch_sha = sha256(QUEUE), sha256(DISPATCH)
    receipt = f"""

# [X2CL-20260731-2255] CL2X-915 consumed; E36 native-rate spectral follow-through
- source_cl2x: `{SOURCE_CL2X}`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{BLOCKED}`
- workaround_executed: `{workaround}`
- artifacts: `{AUDIT.relative_to(ROOT)}` sha256=`{sha256(AUDIT)}`; `{AUDIT_TOOL.relative_to(ROOT)}` sha256=`{sha256(AUDIT_TOOL)}`; `{REEL_QA.relative_to(ROOT)}` sha256=`{sha256(REEL_QA)}`; `workflow/work_queue.json` sha256=`{queue_sha}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{dispatch_sha}`
- gate_results: `canonical_script_manifest:PASS_EXACT;CL2X915_consumed:PASS;fullscreen_worst_cluster_reel:PASS_INDEPENDENTLY_ENDORSED;native24_spectrum:PASS_{sampling['accepted_windows']}_WINDOWS_ZERO_REJECTED;4Hz_rank:{spectrum['target_rank_in_band']}_OF_{spectrum['frequency_bin_count_in_band']};4Hz_power_percentile:{spectrum['target_power_percentile_in_band']:.3f};4Hz_neighbor_ratio:{spectrum['target_to_local_neighbor_median_ratio']:.3f};distinct_0P25S_resonance:NOT_SUPPORTED;subjective_comfort:NOT_CLEARED;continuous_full_runtime_watch:NOT_COMPLETE;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;promotion:NOT_YET;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
    with RECEIPTS.open("a", encoding="utf-8") as f:
        f.write(receipt)
    print(json.dumps({"queue_sha256": queue_sha, "dispatch_sha256": dispatch_sha, "receipt_sha256": sha256(RECEIPTS)}))


if __name__ == "__main__":
    main()
