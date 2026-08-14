#!/usr/bin/env python3
"""Record the reversible E36 V19 objective-QA advance in local shared state."""

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
QA = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10_QA_V1.json"
V19 = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v19_v18c_plus_line10/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10.mp4"
MANIFEST = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10_MANIFEST_V1.json"
AHASH = ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v19_runtime/E36_ACCEPTED_ONLY_AGENTCUT_V19_FPS1_ADJACENT_AHASH_QA.json"
CADENCE = ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v19_runtime/E36_ACCEPTED_ONLY_AGENTCUT_V19_FRAME_CADENCE_QA.json"
CONTACT = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v19_v18c_plus_line10/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10_contact_sheet.jpg"
BUILDER = ROOT / "tools/build_e36_v19_v18c_plus_line10.py"
MAP = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V10.json"
TRANSCRIPT = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V14.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
SCRIPT_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"


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


script_sha = sha(SCRIPT)
manifest_sha = sha(SCRIPT_MANIFEST)
declared_sha = load(SCRIPT_MANIFEST)["sha256"]
if script_sha != "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6":
    raise SystemExit("canonical script SHA mismatch")
if manifest_sha != "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5":
    raise SystemExit("manifest SHA mismatch")
if declared_sha != script_sha:
    raise SystemExit("manifest declared script SHA mismatch")

ahash = load(AHASH)
cadence = load(CADENCE)
assembly = load(MANIFEST)
if ahash["status"] != "PASS" or ahash["near_pair_ratio_percent"] > 15:
    raise SystemExit("V19 strict aHash gate is not PASS")
if cadence["status"] != "PASS" or cadence["failures"]:
    raise SystemExit("V19 cadence gate is not PASS")
if assembly["output"]["sha256"] != sha(V19):
    raise SystemExit("V19 media SHA does not match assembly manifest")

blocked = (
    "PROMOTION_ONLY:V19_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;"
    "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08;"
    "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
    "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
)
next_action = (
    "Run an uninterrupted 288.911-second V19 audiovisual watch against canonical dialogue, lipsync, action causality, identity, period, "
    "evidence visibility and reframe comfort; localize and reversibly repair only observed failures. In parallel continue zero-credit U08 "
    "motion recovery and mine lines4,5,11,12,23,24,27,28 without changing any accepted PASS."
)
progress = (
    "Built V19 by inserting the newly admitted model-native line10 into the strongest reversible V18C dynamic-reframe base. The 288.911-second "
    "output fully decoded, passed frame cadence with zero freezes and zero periodic chains, and passed the hard fps1 adjacent aHash gate at "
    "38/288=13.194%. Direct review of 24 full-span samples passed identity, period, props and framing with no incoherent overlap. V19 remains "
    "reversible and unpromoted pending uninterrupted full audiovisual review; transcript39/47, motion29/30 and release holds remain unchanged."
)

qa = {
    "schema": "qingshan.e36.accepted_only_agentcut.v19_v18c_plus_line10.qa.v1",
    "generated_at": NOW,
    "source_cl2x": "CL2X-908",
    "source_mailbox_sha256": "638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041",
    "canonical": {"path": rel(SCRIPT), "sha256": script_sha, "status": "PASS_EXACT"},
    "canonical_manifest": {"path": rel(SCRIPT_MANIFEST), "sha256": manifest_sha, "declared_script_sha256": declared_sha, "status": "PASS_EXACT"},
    "assembly_manifest": {"path": rel(MANIFEST), "sha256": sha(MANIFEST), "status": assembly["status"]},
    "media": {"path": rel(V19), "sha256": sha(V19), "duration_seconds": 288.911, "status": "REVERSIBLE_NOT_PROMOTED"},
    "accepted_only_binding": {
        "source_map": {"path": rel(MAP), "sha256": sha(MAP), "accepted_source_count": 48},
        "transcript_audit": {"path": rel(TRANSCRIPT), "sha256": sha(TRANSCRIPT), "coverage": "39/47", "unresolved_lines": [4, 5, 11, 12, 23, 24, 27, 28]},
        "motion_coverage": "29/30",
        "unresolved_motion_unit": "U08",
    },
    "objective_qa": {
        "full_decode": "PASS_ZERO_ERRORS",
        "fps1_adjacent_ahash": {"path": rel(AHASH), "sha256": sha(AHASH), "near_pairs": 38, "adjacent_pairs": 288, "ratio_percent": 13.194, "threshold_percent": 15.0, "status": "PASS"},
        "frame_cadence": {"path": rel(CADENCE), "sha256": sha(CADENCE), "freeze_count": 0, "periodic_chain_count": 0, "status": "PASS"},
    },
    "direct_review": {
        "contact_sheet": {"path": rel(CONTACT), "sha256": sha(CONTACT), "full_span_samples": 24},
        "result": "PASS_24_FULL_SPAN_SAMPLES_IDENTITY_PERIOD_PROPS_FRAMING_NO_INCOHERENT_OVERLAP",
        "continuous_full_audiovisual_watch": "NOT_COMPLETE",
    },
    "gate_results": {
        "canonical_script_manifest": "PASS_EXACT",
        "accepted_sources": "PASS_48",
        "accepted_transcript": "HOLD_39_OF_47",
        "motion": "HOLD_29_OF_30_U08",
        "full_decode": "PASS_ZERO_ERRORS",
        "strict_fps1_adjacent_ahash": "PASS_38_OF_288_13P194_PERCENT_LE15",
        "frame_cadence": "PASS_ZERO_FREEZE_ZERO_PERIODIC_CHAINS",
        "representative_direct_visual": "PASS_24_FULL_SPAN_SAMPLES",
        "continuous_full_audiovisual_watch": "NOT_COMPLETE",
        "promotion": "NOT_YET_REVERSIBLE_CANDIDATE_ONLY",
        "release": "HOLD",
    },
    "blocked_by": blocked,
    "workaround_executed": progress,
    "credits": {"pay": 0, "refund": 0, "net": 0, "episode_net": 9976, "limit": 10000, "headroom": 24, "calls": 135, "active": 0},
    "next_action": next_action,
    "status": "PASS_OBJECTIVE_AND_SAMPLED_VISUAL_QA_REVERSIBLE_NOT_PROMOTED",
}
write(QA, qa)

queue = load(QUEUE)
queue.update({
    "updated_at": NOW,
    "source_cl2x": "CL2X-908",
    "source_mailbox_sha256": "638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041",
    "status": "E36_V19_LINE10_DYNAMIC_REFRAME_AHASH_CADENCE_PASS_CONTINUOUS_WATCH_ACTIVE",
    "blocked_by": blocked,
    "next_action": next_action,
    "real_active_handle_count": 0,
    "occupied_scope_count": 1,
    "latest_reversible_agentcut_candidate": rel(V19),
    "latest_reversible_agentcut_candidate_sha256": sha(V19),
    "latest_reversible_agentcut_candidate_qa": rel(QA),
    "latest_reversible_agentcut_candidate_qa_sha256": sha(QA),
    "updated_note_latest": progress,
})
line = queue["lines"]["E36"]
line.update({
    "status": "V19_OBJECTIVE_GATES_PASS_CONTINUOUS_WATCH_AND_ZERO_CREDIT_COVERAGE_REPAIR_ACTIVE",
    "current_phase": progress,
    "blocked_by": blocked,
    "running_or_pending_task_ids": [],
    "local_pid": None,
    "next_action": next_action,
    "latest_cl2x908_v19_reversible_candidate": progress,
})
write(QUEUE, queue)

dispatch = load(DISPATCH)
dispatch.update({
    "generated_at": NOW,
    "source_cl2x": "CL2X-908",
    "source_mailbox_sha256": "638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041",
    "blocked_by": blocked,
    "workaround_executed": progress,
    "next_action": next_action,
})
execution = dispatch["execution"]
execution.update({
    "status": "V19_OBJECTIVE_GATES_PASS_REVERSIBLE_NOT_PROMOTED_CONTINUOUS_WATCH_ACTIVE",
    "active_task_count": 0,
    "accepted_transcript_coverage": "39/47",
    "accepted_motion_coverage": "29/30",
    "accepted_source_count": 48,
    "latest_reversible_agentcut_candidate": rel(V19),
    "latest_reversible_agentcut_candidate_sha256": sha(V19),
    "latest_reversible_agentcut_qa": rel(QA),
    "latest_reversible_agentcut_qa_sha256": sha(QA),
    "latest_reversible_agentcut_manifest": rel(MANIFEST),
    "latest_reversible_agentcut_manifest_sha256": sha(MANIFEST),
    "latest_agentcut_frame_cadence_qa": rel(CADENCE),
    "latest_agentcut_frame_cadence_qa_sha256": sha(CADENCE),
    "latest_agentcut_adjacent_fps1_qa": rel(AHASH),
    "latest_agentcut_adjacent_fps1_qa_sha256": sha(AHASH),
    "latest_agentcut_adjacent_fps1_ratio": 0.13194,
    "last_real_progress": progress,
})
dispatch.setdefault("subsequent_attempts", {})["v19_v18c_plus_line10_reversible_candidate"] = {
    "source_cl2x": "CL2X-908",
    "status": "PASS_OBJECTIVE_QA_REVERSIBLE_NOT_PROMOTED",
    "builder": rel(BUILDER),
    "builder_sha256": sha(BUILDER),
    "manifest": rel(MANIFEST),
    "manifest_sha256": sha(MANIFEST),
    "media": rel(V19),
    "media_sha256": sha(V19),
    "qa": rel(QA),
    "qa_sha256": sha(QA),
    "credits": {"pay": 0, "refund": 0, "net": 0},
}
write(DISPATCH, dispatch)

receipt = f"""

# [X2CL-20260731-2120] E36 V19 line10 plus dynamic-reframe reversible candidate passes hard aHash and cadence gates
- source_cl2x: `CL2X-908`; source_mailbox_sha256=`638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041`
- blocked_by: `{blocked}`
- workaround_executed: `{progress}`
- artifacts: `{rel(BUILDER)}` sha256=`{sha(BUILDER)}`; `{rel(MANIFEST)}` sha256=`{sha(MANIFEST)}`; `{rel(V19)}` sha256=`{sha(V19)}`; `{rel(CONTACT)}` sha256=`{sha(CONTACT)}`; `{rel(AHASH)}` sha256=`{sha(AHASH)}`; `{rel(CADENCE)}` sha256=`{sha(CADENCE)}`; `{rel(QA)}` sha256=`{sha(QA)}`; `{rel(MAP)}` sha256=`{sha(MAP)}`; `{rel(TRANSCRIPT)}` sha256=`{sha(TRANSCRIPT)}`; `workflow/work_queue.json` sha256=`{sha(QUEUE)}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{sha(DISPATCH)}`
- gate_results: `canonical_script_manifest:PASS_EXACT;accepted_sources:PASS_48;accepted_transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;V19_full_decode:PASS_ZERO_ERRORS;V19_frame_cadence:PASS_ZERO_FREEZE_ZERO_PERIODIC_CHAINS;V19_fps1_aHash:PASS_38_OF_288_13P194_PERCENT_LE15;V19_direct_24_sample_visual:PASS;continuous_full_audiovisual_watch:NOT_COMPLETE;promotion:NOT_YET_REVERSIBLE_ONLY;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
with RECEIPTS.open("a", encoding="utf-8") as handle:
    handle.write(receipt)

print(json.dumps({
    "qa_sha256": sha(QA),
    "queue_sha256": sha(QUEUE),
    "dispatch_sha256": sha(DISPATCH),
    "receipt_file_sha256": sha(RECEIPTS),
}, ensure_ascii=False))
