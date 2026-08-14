#!/usr/bin/env python3
"""Register the full-runtime native-rate phase diagnostic without promoting V19."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
AUDIT = ROOT / "qa/e36_agentcut_20260730/E36_V18C_FULL_NATIVE24_PHASE_MOTION_DIAGNOSTIC_V1.json"
AUDIT_TOOL = ROOT / "tools/audit_e36_v18c_full_native24_phase_motion.py"
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPTS = ROOT / "workflow/CODEX_TO_CLAUDE.md"
SOURCE_CL2X = "CL2X-914"
MAILBOX_SHA = "fea59b5aa15786cd2e1224d9c4e5fca57f6d07f80a2e8c132495d43e6f4050b0"
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
    manifest = load(MANIFEST)
    assert sha256(CANONICAL) == CANONICAL_SHA
    assert manifest["sha256"] == CANONICAL_SHA

    audit = load(AUDIT)
    sampling = audit["sampling"]
    aggregate = audit["aggregate"]
    total_pairs = sampling["pair_count"]
    reliable_pairs = aggregate["reliable_pair_count"]
    lag6 = aggregate["quarter_second_lag6"]["vector_autocorrelation"]
    now = datetime.now(timezone.utc).isoformat()
    workaround = (
        "Consumed CL2X-914 and repaired the stale narrative status fields while continuing the underlying "
        "CL2X-913 motion investigation. Completed a full-runtime native-24fps phase-correlation diagnostic "
        f"over {total_pairs} frame pairs, with {reliable_pairs} reliable "
        f"({aggregate['reliable_pair_ratio']:.3%}). Excess translation p95 is "
        f"{aggregate['excess_translation_px_at_180x320']['p95']:.3f}px at 180x320. The lag profile does not "
        "isolate a unique 0.25-second resonance: lag2 exceeds lag6 and correlation decays broadly. Native-rate "
        "sampling bypasses the contact-sheet aliasing risk and localizes worst windows, but it does not clear "
        "subjective comfort or the uninterrupted audiovisual watch."
    )
    next_action = (
        "Render and directly review full-speed audiovisual reels centered on the newly localized worst V18C "
        "clusters at 97.5-99.5s and 162-167s plus the 136.542s outlier, mapped by +6.082993s into V19 after "
        "the line10 insertion; in parallel continue zero-credit recovery for lines4/5/11/12/23/24/27/28 and "
        "U08 while V19 remains unpromoted."
    )
    status = "E36_V18C_FULL_NATIVE24_PHASE_DIAGNOSTIC_PASS_FULL_WATCH_ACTIVE"

    queue = load(QUEUE)
    queue.update({
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "updated_at": now,
        "updated_note_latest": workaround,
        "updated_note": workaround,
        "status": status,
        "latest_v18c_full_native24_phase_motion_diagnostic": str(AUDIT.relative_to(ROOT)),
        "latest_v18c_full_native24_phase_motion_diagnostic_sha256": sha256(AUDIT),
        "blocked_by": BLOCKED,
        "next_action": next_action,
    })
    line = queue.setdefault("lines", {}).setdefault("E36", {})
    line.update({
        "status": status,
        "current_phase": workaround,
        "blocked_by": BLOCKED,
        "next_action": next_action,
        "latest_cl2x914_full_native24_phase_diagnostic": workaround,
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
    execution = dispatch.setdefault("execution", {})
    execution["latest_v18c_full_native24_phase_motion_diagnostic"] = {
        "path": str(AUDIT.relative_to(ROOT)),
        "sha256": sha256(AUDIT),
        "status": "PASS_NATIVE24_FULL_RUNTIME_DIAGNOSTIC_SUBJECTIVE_HOLD",
        "frame_pairs": total_pairs,
        "reliable_frame_pairs": reliable_pairs,
        "reliable_pair_ratio": aggregate["reliable_pair_ratio"],
        "excess_translation_p95_px_at_180x320": aggregate["excess_translation_px_at_180x320"]["p95"],
        "lag6_vector_autocorrelation": lag6,
        "quarter_second_resonance": "NOT_ISOLATED_BROAD_CORRELATION_DECAY",
    }
    execution["last_real_progress"] = workaround
    execution["status"] = "CL2X-914_FULL_NATIVE24_PHASE_DIAGNOSTIC_PASS_REVERSIBLE_NOT_PROMOTED"
    dump(DISPATCH, dispatch)

    queue_sha, dispatch_sha = sha256(QUEUE), sha256(DISPATCH)
    receipt = f"""

# [X2CL-20260731-2235] CL2X-914 consumed; E36 full-runtime native-24fps phase diagnostic and narrative-state repair
- source_cl2x: `{SOURCE_CL2X}`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{BLOCKED}`
- workaround_executed: `{workaround}`
- artifacts: `{AUDIT.relative_to(ROOT)}` sha256=`{sha256(AUDIT)}`; `{AUDIT_TOOL.relative_to(ROOT)}` sha256=`{sha256(AUDIT_TOOL)}`; `workflow/work_queue.json` sha256=`{queue_sha}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{dispatch_sha}`
- gate_results: `canonical_script_manifest:PASS_EXACT;full_runtime_native_rate:PASS_24FPS_{total_pairs}_PAIRS;reliable_pairs:PASS_{reliable_pairs}_OF_{total_pairs};quarter_second_visual_aliasing:BYPASSED_WITH_SIX_SAMPLES_PER_PERIOD;excess_translation_p95:{aggregate['excess_translation_px_at_180x320']['p95']:.3f}PX_AT_180X320;lag6_autocorrelation:{lag6:.4f};quarter_second_resonance:NOT_ISOLATED_LAG2_EXCEEDS_LAG6;subjective_comfort:HOLD;continuous_realtime_human_watch:NOT_COMPLETE;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;promotion:NOT_YET;release:HOLD;narrative_state_fields:PASS_SYNCHRONIZED_TO_CL2X914`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
    with RECEIPTS.open("a", encoding="utf-8") as f:
        f.write(receipt)
    print(json.dumps({
        "queue_sha256": queue_sha,
        "dispatch_sha256": dispatch_sha,
        "receipt_file_sha256": sha256(RECEIPTS),
    }))


if __name__ == "__main__":
    main()
