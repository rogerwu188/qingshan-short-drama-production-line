#!/usr/bin/env python3
"""Independently verify the zero-credit E36 Roger escalation packet."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
MAILBOX = ROOT / "codex_docs/CLAUDE_TO_CODEX.md"
QUEUE = ROOT / "workflow/work_queue.json"
PACKET = ROOT / "workflow/tasks/E36_ROGER_ESCALATION_DECISION_PACKET_V1.json"
TERMINAL = ROOT / "qa/e36_agentcut_20260730/E36_TERMINAL_COVERAGE_FIVE_CATEGORY_POLICY_AND_INTEGRITY_V7.json"
RIGHTS = ROOT / "qa/e36_agentcut_20260730/voice_rights_runtime/E36_JIAOTU_VOICE_RIGHTS_PREFLIGHT_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
OUTPUT = ROOT / "qa/e36_agentcut_20260730/E36_ROGER_ESCALATION_PACKET_INTEGRITY_AUDIT_V1.json"

EXPECTED = {
    "mailbox": "c7bbeef8ddf07585d3896afc3a1a45bd010f3e48f2c72c1c4114a9c5224d74dd",
    "packet": "d6def8ff24cc75bb67b5105c4399532edb2626d0b13998039044329417ed5fce",
    "terminal": "65a9245b247be6b07c609211783bd52d14be84bf05ca8c383e1f8854be72b3f7",
    "rights": "733904a0b2c822b734d1fab70eb63212fcc5bad4ce7a53504a28201661afbcf7",
    "script": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    queue = load(QUEUE)
    packet = load(PACKET)
    terminal = load(TERMINAL)
    rights = load(RIGHTS)
    manifest = load(MANIFEST)

    actual_sha = {
        "mailbox": sha256(MAILBOX),
        "work_queue": sha256(QUEUE),
        "packet": sha256(PACKET),
        "terminal": sha256(TERMINAL),
        "rights": sha256(RIGHTS),
        "script": sha256(SCRIPT),
        "manifest": sha256(MANIFEST),
    }
    for key, expected in EXPECTED.items():
        require(actual_sha[key] == expected, f"{key} SHA mismatch")
    require(manifest["sha256"] == actual_sha["script"], "manifest/script SHA mismatch")

    policy = queue["rules"]["pronunciation_hard_policy"]
    e36 = queue["lines"]["E36"]
    require(policy["all_remaining_terminal"] is True, "queue terminal flag false")
    require(policy["escalate_to_roger"] is True, "queue escalation flag false")
    require(policy["terminal_covered_line_count"] == 17, "queue terminal count mismatch")
    require(policy["current_unproven_line_count"] == 17, "queue unproven count mismatch")
    require(e36["running_or_pending_task_ids"] == [], "queue has active E36 tasks")
    require(queue["generation_credits"] == 7968, "queue exact credit mismatch")
    require(queue["generation_calls"] == 102, "queue call count mismatch")

    integrity = terminal["integrity_math"]
    categories = terminal["terminal_categories"]
    terminal_lines = [line for category in categories.values() for line in category["lines"]]
    require(integrity["accepted_transcript_lines"] == 30, "transcript count mismatch")
    require(integrity["terminal_covered_lines"] == 17, "terminal evidence count mismatch")
    require(len(terminal_lines) == 17, "terminal category sum mismatch")
    require(len(set(terminal_lines)) == 17, "terminal categories overlap")
    require(integrity["all_remaining_terminal"] is True, "terminal evidence flag false")
    require(integrity["escalate_to_roger"] is True, "terminal escalation flag false")

    accounting = terminal["accounting"]
    require(accounting["images"] + accounting["videos"] + accounting["audio"] == 7968, "credit arithmetic mismatch")
    require(accounting["exact_source_attributable_net"] == 7968, "terminal net mismatch")
    require(accounting["episode_cap"] == 10000, "episode cap mismatch")
    require(accounting["active_remote_tasks"] == 0, "terminal evidence has active tasks")
    require(accounting["shared_api_non_source_consumption_excluded"] is True, "shared API exclusion missing")

    current = packet["current_state"]
    require(current["accepted_transcript_lines"] == "30/47", "packet transcript mismatch")
    require(current["motion_units"] == "29/30", "packet motion mismatch")
    require(current["terminal_coverage"] == "17/17", "packet terminal mismatch")
    require(current["active_remote_tasks"] == 0, "packet has active tasks")
    require(current["exact_source_attributable_credits"] == "7968/10000", "packet credit mismatch")
    require(packet["status"] == "AWAITING_ROGER_DISPOSITION", "packet status mismatch")
    require(packet["gate_results"]["irreversible_action"] == "NONE_TAKEN", "irreversible action recorded")
    require(packet["gate_results"]["new_generation_credits"] == 0, "packet generated new credits")

    rights_meta = rights["voice_authority"]["commercial_use_metadata"]
    require(rights_meta["present"] is False, "rights evidence unexpectedly present")
    require(rights_meta["releaseBlocked"] is True, "rights release block missing")
    require(rights["voice_authority"]["release_eligible"] is False, "rights release eligible unexpectedly true")

    audit = {
        "schema": "qingshan.e36.roger_escalation_packet_integrity_audit.v1",
        "episode": "E36",
        "generated_at": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(timespec="seconds"),
        "source_cl2x": "CL2X-858",
        "source_mailbox_sha256": actual_sha["mailbox"],
        "status": "PASS_AWAITING_ROGER_DISPOSITION",
        "bound_artifacts": {
            "work_queue": {"path": str(QUEUE.relative_to(ROOT)), "sha256": actual_sha["work_queue"]},
            "decision_packet": {"path": str(PACKET.relative_to(ROOT)), "sha256": actual_sha["packet"]},
            "terminal_integrity": {"path": str(TERMINAL.relative_to(ROOT)), "sha256": actual_sha["terminal"]},
            "rights_preflight": {"path": str(RIGHTS.relative_to(ROOT)), "sha256": actual_sha["rights"]},
            "canonical_script": {"path": str(SCRIPT.relative_to(ROOT)), "sha256": actual_sha["script"]},
            "manifest": {"path": str(MANIFEST.relative_to(ROOT)), "sha256": actual_sha["manifest"]},
        },
        "verified_state": {
            "transcript": "30/47",
            "motion": "29/30",
            "terminal_coverage": "17/17_distinct_non_overlapping",
            "terminal_breakdown": {
                "pronunciation_hard": 10,
                "provider_blocked_no_changed_input_path": 2,
                "changed_input_budget_exhausted": 2,
                "rights_blocked_pending_commercial_evidence": 3,
            },
            "all_remaining_terminal": True,
            "escalate_to_roger": True,
            "AgentCut": "HOLD",
            "active_remote_tasks": 0,
            "exact_source_attributable_credits": 7968,
            "episode_cap": 10000,
            "attributable_headroom": 2032,
            "generation_calls": 102,
            "shared_api_non_source_consumption_excluded": True,
        },
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "packet_sha_binding": "PASS",
            "terminal_category_integrity": "PASS_17_DISTINCT_OF_17",
            "accounting": "PASS_704_PLUS_7164_PLUS_100_EQUALS_7968_LE_10000",
            "remote_activity": "PASS_ZERO_ACTIVE",
            "commercial_rights": "BLOCKED_METADATA_ABSENT",
            "user_disposition": "REQUIRED",
            "new_generation_credits": 0,
            "new_qa_credits": 0,
            "irreversible_action": "NONE_TAKEN",
        },
        "blocked_by": "Roger disposition is required for any exact-source waiver, extra U08/provider input, changed-input reauthorization, JiaoTu rights replacement, or AgentCut release.",
        "next_action": "Keep every FAIL, AgentCut and E37 held with zero further spend until Roger gives an explicit option or custom line-by-line disposition.",
    }
    OUTPUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
