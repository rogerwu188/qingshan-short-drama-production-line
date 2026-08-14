#!/usr/bin/env python3
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE_REL = "workflow/work_queue.json"
TRANSCRIPT_REL = "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V11.json"
SOURCE_MAP_REL = "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V7.json"
PREFLIGHT_REL = "workflow/releases/E36_ACHIEVABLE_FINAL_RELEASE_READINESS_PREFLIGHT_20260731.json"
OUT_REL = "workflow/releases/E36_PLATFORM_METADATA_DRAFT_20260731.json"
SOURCE_CL2X = "CL2X-881"
MAILBOX_SHA = "dd7710b48f11d578ffbcdc792bdeccff3c0a5b2e1672fb5643a868f5d84d7975"


def load(rel):
    return json.loads((ROOT / rel).read_text())


def write(rel, value):
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


now = datetime.now().astimezone().isoformat(timespec="seconds")
queue = load(QUEUE_REL)
transcript = load(TRANSCRIPT_REL)
source_map = load(SOURCE_MAP_REL)
preflight = load(PREFLIGHT_REL)

unproven = [row["contract_line_number"] for row in transcript["unproven_lines"]]
policy = queue["rules"]["pronunciation_hard_policy"]
pronunciation_hard = [line for line in [2, 3, 9, 13, 14, 16, 23, 25, 26, 28] if line in unproven]
provider_blocked = [line for line in policy["provider_blocked_no_changed_input_path_lines"] if line in unproven]
changed_exhausted = [line for line in policy["changed_input_budget_exhausted_unclassified_lines"] if line in unproven]
partial_robust = [line for line in policy["changed_input_budget_exhausted_partial_robust_unclassified_lines"] if line in unproven]
rights_blocked = [line for line in policy["rights_blocked_pending_commercial_evidence_lines"] if line in unproven]
terminal_union = sorted(set(pronunciation_hard + provider_blocked + changed_exhausted + partial_robust + rights_blocked))
if terminal_union != sorted(unproven):
    raise SystemExit(f"terminal categories do not cover V11 unproven lines: {terminal_union} != {sorted(unproven)}")

policy.update({
    "source_cl2x": SOURCE_CL2X,
    "current_pronunciation_hard_count": len(pronunciation_hard),
    "current_pronunciation_hard_lines": pronunciation_hard,
    "current_provider_blocked_no_changed_input_path_count": len(provider_blocked),
    "provider_blocked_no_changed_input_path_lines": provider_blocked,
    "current_changed_input_budget_exhausted_unclassified_count": len(changed_exhausted),
    "changed_input_budget_exhausted_unclassified_lines": changed_exhausted,
    "current_changed_input_budget_exhausted_partial_robust_unclassified_count": len(partial_robust),
    "changed_input_budget_exhausted_partial_robust_unclassified_lines": partial_robust,
    "current_rights_blocked_pending_commercial_evidence_count": len(rights_blocked),
    "rights_blocked_pending_commercial_evidence_lines": rights_blocked,
    "current_unproven_line_count": len(unproven),
    "terminal_covered_line_count": len(terminal_union),
    "all_remaining_terminal": True,
    "escalate_to_roger": False,
    "authoritative_transcript_audit": TRANSCRIPT_REL,
    "authoritative_transcript_audit_sha256": sha(TRANSCRIPT_REL)
})
queue["updated_at"] = now
queue["updated_note_latest"] = "CL2X-881 advisory consumed: pronunciation-hard policy synchronized to V11 unproven12/terminal12 (pronunciation-hard5, provider2, changed-exhausted1, partial-robust1, rights3). Release metadata draft prepared with both platforms held until final lock."
queue["lines"]["E36"]["latest_cl2x881_policy_sync_and_release_metadata"] = queue["updated_note_latest"]
write(QUEUE_REL, queue)

metadata = {
    "schema": "qingshan.e36.platform_metadata_draft.v1",
    "episode": "E36",
    "source_cl2x": SOURCE_CL2X,
    "source_mailbox_sha256": MAILBOX_SHA,
    "generated_at": now,
    "status": "METADATA_READY_PLATFORM_SUBMISSION_HARD_HOLD",
    "final_media": None,
    "final_sha256": None,
    "canonical": {
        "script": "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md",
        "script_sha256": source_map["canonical_gate"]["script_sha256"],
        "title": "假谍探真棋子"
    },
    "shared": {
        "series": "青山",
        "episode_number": 36,
        "hashtags": ["青山", "AI短剧", "古装悬疑", "短剧"],
        "publication_order": ["youtube", "douyin"],
        "copyright_assertion": "HOLD_UNTIL_FINAL_PACKAGE_RIGHTS_GATE",
        "release_allowed": False
    },
    "youtube": {
        "target": "YouTube Shorts",
        "title": "青山 EP36：假谍探真棋子 | AI短剧",
        "made_for_kids": False,
        "visibility": "HOLD_NO_FINAL_LOCK",
        "submission_status": "NOT_SUBMITTED"
    },
    "douyin": {
        "target": "Douyin creator publication",
        "title": "青山EP36：假谍探真棋子",
        "visibility": "HOLD_NO_FINAL_LOCK",
        "submission_status": "NOT_SUBMITTED"
    },
    "evidence": {
        "release_preflight": {"path": PREFLIGHT_REL, "sha256": sha(PREFLIGHT_REL)},
        "accepted_source_map": {"path": SOURCE_MAP_REL, "sha256": sha(SOURCE_MAP_REL)},
        "transcript_audit": {"path": TRANSCRIPT_REL, "sha256": sha(TRANSCRIPT_REL)},
        "work_queue_after_policy_sync": {"path": QUEUE_REL, "sha256": sha(QUEUE_REL)}
    },
    "gate_results": {
        "metadata_completeness": "PASS_DRAFT",
        "target_binding": "PASS_YOUTUBE_SHORTS_AND_DOUYIN",
        "canonical_title_binding": "PASS",
        "final_media": "FAIL_MISSING",
        "final_lock": "FAIL_MISSING",
        "transcript": "FAIL_35_OF_47",
        "motion": "FAIL_29_OF_30",
        "platform_submission": "BLOCKED"
    },
    "blocked_by": preflight["blocked_by"],
    "irreversible_platform_action_attempted": False,
    "next_action": "Keep metadata ready but do not submit either platform until a gate-complete final lock exists."
}
write(OUT_REL, metadata)
print(json.dumps({
    "work_queue": [QUEUE_REL, sha(QUEUE_REL)],
    "metadata": [OUT_REL, sha(OUT_REL)],
    "unproven": unproven,
    "terminal_union": terminal_union
}, ensure_ascii=False))
