#!/usr/bin/env python3
"""Register the V18C native-rate motion spectrum diagnostic without promotion."""

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
    assert sha256(CANONICAL) == load(SCRIPT_MANIFEST)["sha256"] == CANONICAL_SHA
    audit = load(AUDIT)
    sampling = audit["sampling"]
    spectrum = audit["aggregate_spectrum"]
    assert sampling["frame_pairs"] == 6750 and sampling["reliable_pairs"] == 6699
    assert sampling["accepted_windows"] == 139 and sampling["rejected_windows"] == 0
    assert spectrum["target_frequency_hz"] == 4.0 and spectrum["distinct_4hz_resonance"] is False
    now = datetime.now(timezone.utc).isoformat()
    workaround = (
        "Continued under CL2X-914 with a full-runtime native-rate spectral test instead of treating the 0.25-second "
        "sampling concern as a reason to stop. Across 139 overlapping four-second Hann windows built from 6699 "
        "reliable frame pairs, 4Hz ranks 36th of 39 bins in the 0.5-10Hz band, at the 10.256th power percentile "
        f"and {spectrum['target_to_local_neighbor_median_ratio']:.3f}x its local-neighbor median. This rejects a "
        "distinct 0.25-second resonance mechanism; the remaining comfort question is broader drift/reframe behavior "
        "and still requires uninterrupted native-speed audiovisual review."
    )
    next_action = (
        "Use the ready fullscreen V19 reels for uninterrupted native-speed review with attention shifted from an "
        "unsupported exact 4Hz oscillation to low-frequency pan/drift, fatigue, face cutoff, lipsync and causal "
        "continuity; concurrently continue zero-credit recovery for lines4/5/11/12/23/24/27/28 and U08 while "
        "V19 stays reversible and unpromoted."
    )
    status = "E36_V18C_NATIVE24_SPECTRUM_NO_4HZ_RESONANCE_FULL_WATCH_ACTIVE"

    queue = load(QUEUE)
    queue.update({
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "updated_at": now,
        "updated_note_latest": workaround,
        "updated_note": workaround,
        "status": status,
        "latest_v18c_native24_motion_spectrum_diagnostic": str(AUDIT.relative_to(ROOT)),
        "latest_v18c_native24_motion_spectrum_diagnostic_sha256": sha256(AUDIT),
        "blocked_by": BLOCKED,
        "next_action": next_action,
    })
    queue["lines"]["E36"].update({"status": status, "current_phase": workaround, "blocked_by": BLOCKED, "next_action": next_action, "latest_cl2x914_motion_spectrum": workaround})
    dump(QUEUE, queue)

    dispatch = load(DISPATCH)
    dispatch.update({"source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA, "generated_at": now, "blocked_by": BLOCKED, "workaround_executed": workaround, "next_action": next_action})
    dispatch["execution"]["latest_v18c_native24_motion_spectrum_diagnostic"] = {
        "path": str(AUDIT.relative_to(ROOT)), "sha256": sha256(AUDIT),
        "status": "PASS_DISTINCT_4HZ_RESONANCE_NOT_SUPPORTED_SUBJECTIVE_HOLD",
        "accepted_windows": sampling["accepted_windows"], "rejected_windows": sampling["rejected_windows"],
        "target_rank": spectrum["target_rank_in_band"], "band_bins": spectrum["frequency_bin_count_in_band"],
        "target_percentile": spectrum["target_power_percentile_in_band"],
        "target_neighbor_ratio": spectrum["target_to_local_neighbor_median_ratio"],
    }
    dispatch["execution"]["last_real_progress"] = workaround
    dispatch["execution"]["status"] = "CL2X-914_NATIVE24_SPECTRUM_PASS_REVERSIBLE_NOT_PROMOTED"
    dump(DISPATCH, dispatch)

    queue_sha, dispatch_sha = sha256(QUEUE), sha256(DISPATCH)
    receipt = f"""

# [X2CL-20260731-2252] E36 V18C native-24fps motion spectrum diagnostic
- source_cl2x: `{SOURCE_CL2X}`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{BLOCKED}`
- workaround_executed: `{workaround}`
- artifacts: `{AUDIT.relative_to(ROOT)}` sha256=`{sha256(AUDIT)}`; `{AUDIT_TOOL.relative_to(ROOT)}` sha256=`{sha256(AUDIT_TOOL)}`; `{REEL_QA.relative_to(ROOT)}` sha256=`{sha256(REEL_QA)}`; `workflow/work_queue.json` sha256=`{queue_sha}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{dispatch_sha}`
- gate_results: `canonical_script_manifest:PASS_EXACT;native24_spectrum:PASS_6750_PAIRS_6699_RELIABLE;four_second_hann_windows:PASS_139_REJECTED_0;frequency_resolution:0P25HZ;4Hz_rank:36_OF_39;4Hz_power_percentile:10P256;4Hz_neighbor_ratio:{spectrum['target_to_local_neighbor_median_ratio']:.3f};distinct_0P25S_resonance:NOT_SUPPORTED;subjective_comfort:NOT_CLEARED;continuous_full_runtime_watch:NOT_COMPLETE;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;promotion:NOT_YET;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
    with RECEIPTS.open("a", encoding="utf-8") as f:
        f.write(receipt)
    print(json.dumps({"audit_sha256": sha256(AUDIT), "queue_sha256": queue_sha, "dispatch_sha256": dispatch_sha, "receipt_sha256": sha256(RECEIPTS)}))


if __name__ == "__main__":
    main()
