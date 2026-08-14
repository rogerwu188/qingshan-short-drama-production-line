#!/usr/bin/env python3
"""Adjudicate the V19-only line10 region at 0.25-second cadence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE_DIR = ROOT / "qa/e36_agentcut_20260730/v19_line10_quarter_second_probe_v1"
MANIFEST = PROBE_DIR / "E36_V19_LINE10_QUARTER_SECOND_PROBE_MANIFEST_V1.json"
QA = ROOT / "qa/e36_agentcut_20260730/E36_V19_LINE10_QUARTER_SECOND_DIRECT_QA_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPTS = ROOT / "workflow/CODEX_TO_CLAUDE.md"
SOURCE_CL2X = "CL2X-912"
MAILBOX_SHA = "ca97ab522e4346dcd467f4a5f8363a13385794fd78fc43aa37f2cf77c7295244"
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


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> None:
    manifest = load(MANIFEST)
    now = datetime.now(timezone.utc).isoformat()
    artifacts = [{"path": rel(MANIFEST), "sha256": sha256(MANIFEST)}]
    for sheet in manifest["sheets"]:
        path = ROOT / sheet["path"]
        if sha256(path) != sheet["sha256"]:
            raise SystemExit(f"sheet hash mismatch: {path}")
        artifacts.append({"path": rel(path), "sha256": sha256(path)})
    workaround = (
        "Consumed CL2X-912's sampling advisory and ran a zero-credit 4fps direct visual probe over the only "
        "V19-new line10 insertion plus both edit boundaries. Forty-five quarter-second samples show stable "
        "within-shot composition and performance with two motivated hard cuts, but this localized diagnostic "
        "does not clear inherited full-runtime high-frequency motion or uninterrupted realtime comfort."
    )
    next_action = (
        "Run full-frame-rate realtime review reels around the inherited V18C high-motion centers, shifted by "
        "the 6.082993-second V19 insertion where applicable; preserve V19 unpromoted and continue zero-credit "
        "recovery for lines4/5/11/12/23/24/27/28 and U08."
    )
    qa = {
        "schema": "e36_v19_line10_quarter_second_direct_qa_v1",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "candidate": manifest["candidate"] | {"status": "REVERSIBLE_NOT_PROMOTED"},
        "probe_manifest": {"path": rel(MANIFEST), "sha256": sha256(MANIFEST)},
        "sampling": {"window_seconds": manifest["window_seconds"], "interval_seconds": 0.25, "sample_rate_fps": 4.0, "sample_count": 45},
        "direct_review": {
            "pre_insert_68P928_70P678": "PASS_STABLE_PERIOD_INTERIOR_SEATED_SPEAKER_VISIBLE_MOUTH_HAND_AND_BLANK_ENVELOPE",
            "cut_at_70P928": "PASS_MOTIVATED_HARD_CUT_TO_BOUND_MESSENGER_LINE10_SPEAKER",
            "insert_70P928_76P928": "PASS_STABLE_COMPOSITION_BOUND_MESSENGER_VISIBLE_MOUTH_BREATH_EXPRESSION_AND_ROPE_CONTINUITY",
            "cut_at_77P178": "PASS_MOTIVATED_HARD_CUT_TO_FOLLOWING_ACCEPTED_KNEELING_MESSENGER_SHOT",
            "post_insert_77P178_79P928": "PASS_STABLE_COMPOSITION_VISIBLE_MOUTH_EXPRESSION_PERIOD_AND_IDENTITY",
            "subsecond_back_and_forth_reframe": "PASS_NONE_OBSERVED_IN_45_QUARTER_SECOND_SAMPLES",
            "critical_face_mouth_prop_crop": "PASS_NONE_OBSERVED",
            "modern_or_garbled_text": "PASS_NONE_VISIBLE",
            "scope_limit": "SAMPLED_LOCALIZED_DIAGNOSTIC_NOT_CONTINUOUS_REALTIME_OR_FULL_RUNTIME_COMFORT_CLEARANCE",
        },
        "inherited_motion_evidence": {
            "v18c_4fps_attribution_qa": "qa/e36_agentcut_20260730/E36_V18C_INTERFRAME_ATTRIBUTION_AND_SMOOTH_REFRAME_WORKAROUND_QA_V1.json",
            "v18c_added_high_frequency_motion": "CONFIRMED_1033_OF_1125_RELIABLE_PAIRS",
            "v19_relationship": "V18C_BASE_PLUS_6P082993_SECOND_LINE10_INSERTION",
            "interpretation": "The V19-only insertion is localized PASS at 4fps; inherited V18C high-frequency motion remains unresolved by continuous human watch.",
        },
        "artifacts": artifacts,
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "v19_new_insertion_quarter_second_review": "PASS_45_SAMPLES",
            "v19_new_insertion_subsecond_reframe": "PASS_NONE_OBSERVED",
            "inherited_full_runtime_high_frequency_motion": "HOLD_CONFIRMED_NOT_SEMANTICALLY_CLEARED",
            "continuous_uninterrupted_realtime_watch": "NOT_COMPLETE",
            "transcript": "HOLD_39_OF_47",
            "motion": "HOLD_29_OF_30_U08",
            "promotion": "NOT_YET_KEEP_V15_CANONICAL",
            "release": "HOLD",
        },
        "blocked_by": BLOCKED,
        "workaround_executed": workaround,
        "credits": "Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0",
        "next_action": next_action,
    }
    dump(QA, qa)
    qa_sha = sha256(QA)
    queue = load(QUEUE)
    queue.update({
        "source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA, "updated_at": now,
        "status": "E36_V19_BOUNDED_FULL_COVERAGE_LINE10_4FPS_PASS_CONTINUOUS_WATCH_ACTIVE",
        "latest_v19_line10_quarter_second_qa": rel(QA), "latest_v19_line10_quarter_second_qa_sha256": qa_sha,
        "blocked_by": BLOCKED, "next_action": next_action,
    })
    dump(QUEUE, queue)
    dispatch = load(DISPATCH)
    dispatch.update({"source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA, "generated_at": now, "blocked_by": BLOCKED, "workaround_executed": workaround, "next_action": next_action})
    dispatch.setdefault("execution", {})["latest_v19_line10_quarter_second_qa"] = {"path": rel(QA), "sha256": qa_sha, "status": "PASS_LOCALIZED_4FPS_CONTINUOUS_HOLD"}
    dispatch["execution"]["last_real_progress"] = workaround
    dispatch["execution"]["status"] = "CL2X-912_V19_LINE10_4FPS_PASS_REVERSIBLE_NOT_PROMOTED"
    dump(DISPATCH, dispatch)
    queue_sha, dispatch_sha = sha256(QUEUE), sha256(DISPATCH)
    artifact_text = "; ".join(f"`{a['path']}` sha256=`{a['sha256']}`" for a in artifacts)
    receipt = f"""

# [X2CL-20260731-2219] E36 V19 line10 quarter-second reframe diagnostic
- source_cl2x: `{SOURCE_CL2X}`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{BLOCKED}`
- workaround_executed: `{workaround}`
- artifacts: `{rel(QA)}` sha256=`{qa_sha}`; {artifact_text}; `workflow/work_queue.json` sha256=`{queue_sha}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{dispatch_sha}`
- gate_results: `canonical:PASS_EXACT;line10_4fps_direct:PASS_45_SAMPLES;subsecond_reframe_in_v19_new_region:PASS_NONE_OBSERVED;inherited_full_runtime_high_frequency_motion:HOLD;continuous_realtime_watch:NOT_COMPLETE;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;promotion:NOT_YET;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
    with RECEIPTS.open("a", encoding="utf-8") as f:
        f.write(receipt)
    print(json.dumps({"qa_sha256": qa_sha, "queue_sha256": queue_sha, "dispatch_sha256": dispatch_sha, "receipt_file_sha256": sha256(RECEIPTS)}))


if __name__ == "__main__":
    main()
