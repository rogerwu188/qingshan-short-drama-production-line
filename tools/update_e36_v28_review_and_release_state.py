#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"

CANDIDATE = "working_assets/e36_agentcut_20260801/accepted_only_v28_full_dialogue_targeted_reframe_av_aligned/E36_ACCEPTED_ONLY_AGENTCUT_V28_FULL_DIALOGUE_TARGETED_REFRAME_AV_ALIGNED.mp4"
CANDIDATE_SHA = "1f014559b4e4768e22d601e9cbf78b708cdfad8e38d43aad54b2e796141c5eca"
OBJECTIVE_QA = "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V28_OBJECTIVE_QA_V1.json"
PAYLOAD_QA = "qa/e36_agentcut_20260730/E36_V28_PLATFORM_PAYLOAD_STAGING_QA_V1.json"
RELEASE = "workflow/releases/E36_RELEASE_PACKAGE_PREP_V8_20260801.json"
SOURCE_MAP = "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V13.json"
SOURCE_MAP_SHA = "215029b2b260a3dad050cd2cdb2903d56a261edcfac464991a995443469acb3a"
TRANSCRIPT = "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V17.json"
TRANSCRIPT_SHA = "d3df0551cc89d30337030ea83ba008e7e67f6a0a6fcc6488af582338ebe51789"
REVIEW_AUTHORITY = "workflow/approvals/ROGER_TEMPORARY_CODEX_SELF_REVIEW_AUTHORITY_20260801.json"
REVIEW_AUTHORITY_SHA = "9efba27e44a01dd2221a041cf0b76e51e884ebf9c16d409cb927ecbb81a3cf7d"
STATUS = "E36_V28_OBJECTIVE_DIRECT_AND_PLATFORM_STAGING_PASS_CODEX_SELF_REVIEW_CONTINUOUS_WATCH_ACTIVE"
BLOCKED = "PROMOTION_ONLY:V28_CONTINUOUS_AUDIOVISUAL_WATCH_INCOMPLETE;PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
NEXT = "Codex owns temporary first-line and supervisory review while Claude is unavailable. Do not generate again. Complete the uninterrupted native-speed audiovisual watch of V28; all reversible platform payload QA is complete. Keep actual platform submission closed until the target account and credentials are locally declared."
WORKAROUND = "Removed independent Claude review as a blocker under Roger's temporary delegation; retained machine, direct visual, tiered scoring and hard-fact gates; staged and verified three V28 platform payloads without further generation."


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text())


def write(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def update_queue():
    data = load(QUEUE)
    objective_sha = sha(OBJECTIVE_QA)
    payload_sha = sha(PAYLOAD_QA)
    release_sha = sha(RELEASE)
    data.update({
        "updated_at": "2026-08-01T21:40:00Z",
        "source_cl2x": "CL2X-924",
        "status": STATUS,
        "blocked_by": BLOCKED,
        "next_action": NEXT,
        "workaround_executed": WORKAROUND,
        "generation_credits": 10900,
        "generation_calls": 142,
        "real_active_handle_count": 0,
        "latest_reversible_agentcut_candidate": CANDIDATE,
        "latest_reversible_agentcut_candidate_sha256": CANDIDATE_SHA,
        "latest_reversible_agentcut_qa": OBJECTIVE_QA,
        "latest_reversible_agentcut_qa_sha256": objective_sha,
        "latest_v28_objective_qa": OBJECTIVE_QA,
        "latest_v28_objective_qa_sha256": objective_sha,
        "latest_v28_platform_payload_staging": PAYLOAD_QA,
        "latest_v28_platform_payload_staging_sha256": payload_sha,
        "latest_release_package_prep": RELEASE,
        "latest_release_package_prep_sha256": release_sha,
        "latest_temporary_codex_review_authority": REVIEW_AUTHORITY,
        "latest_temporary_codex_review_authority_sha256": REVIEW_AUTHORITY_SHA,
        "updated_note_latest": "Roger temporarily assigned review to Codex because Claude is unavailable. V28 objective and direct sampled QA pass; transcript47/47 and motion30/30 pass; platform payload staging passes. Continuous audiovisual watch and irreversible platform action remain closed."
    })
    e36 = data["lines"]["E36"]
    e36.update({
        "status": STATUS,
        "current_phase": "V28 is the current reversible candidate. Codex temporary self-review passes objective gates and direct sampled tiered visual review. Accepted transcript is47/47 and motion is30/30. Three platform payloads are staged and integrity-verified. No generation is active or allowed by the remaining100-credit runway.",
        "blocked_by": BLOCKED,
        "e36_paid_credits": "10900/11000 exact source-attributable episode net; generation calls142; active tasks0; attributable headroom100",
        "local_pid": None,
        "running_or_pending_task_ids": [],
        "next_action": NEXT,
        "latest_reversible_agentcut_candidate": CANDIDATE,
        "latest_reversible_agentcut_candidate_sha256": CANDIDATE_SHA,
        "latest_reversible_agentcut_qa": OBJECTIVE_QA,
        "latest_reversible_agentcut_qa_sha256": objective_sha,
        "latest_accepted_only_source_map": SOURCE_MAP,
        "latest_accepted_only_source_map_sha256": SOURCE_MAP_SHA,
        "latest_transcript_binding_audit": TRANSCRIPT,
        "latest_transcript_binding_audit_sha256": TRANSCRIPT_SHA,
        "accepted_transcript_coverage": "47/47",
        "accepted_motion_coverage": "30/30",
        "latest_v28_platform_payload_staging": PAYLOAD_QA,
        "latest_v28_platform_payload_staging_sha256": payload_sha,
        "latest_release_package_prep": RELEASE,
        "latest_release_package_prep_sha256": release_sha,
        "review_authority": "CODEX_TEMPORARY_FIRST_LINE_AND_SUPERVISORY_REVIEW",
        "review_authority_path": REVIEW_AUTHORITY,
        "review_authority_sha256": REVIEW_AUTHORITY_SHA,
        "independent_local_claude_review": "TEMPORARILY_NOT_REQUIRED_CLAUDE_UNAVAILABLE",
        "workaround_executed": WORKAROUND
    })
    write(QUEUE, data)


def update_dispatch():
    data = load(DISPATCH)
    objective_sha = sha(OBJECTIVE_QA)
    payload_sha = sha(PAYLOAD_QA)
    release_sha = sha(RELEASE)
    data.update({
        "updated_at": "2026-08-01T21:40:00Z",
        "status": STATUS,
        "blocked_by": BLOCKED,
        "next_action": NEXT,
        "workaround_executed": WORKAROUND,
        "latest_reversible_agentcut_candidate": CANDIDATE,
        "latest_reversible_agentcut_candidate_sha256": CANDIDATE_SHA,
        "latest_reversible_agentcut_qa": OBJECTIVE_QA,
        "latest_reversible_agentcut_qa_sha256": objective_sha,
        "latest_v28_platform_payload_staging": {
            "path": PAYLOAD_QA,
            "sha256": payload_sha,
            "status": "PASS_REVERSIBLE_PLATFORM_PAYLOAD_STAGING_PLATFORM_ACTION_NONE"
        },
        "latest_release_package_prep": {
            "path": RELEASE,
            "sha256": release_sha,
            "status": "V28_PLATFORM_PAYLOADS_QA_PASS_CONTINUOUS_WATCH_AND_PLATFORM_ACTION_CLOSED"
        },
        "review_authority": {
            "owner": "CODEX",
            "scope": "TEMPORARY_FIRST_LINE_AND_SUPERVISORY_REVIEW_WHILE_CLAUDE_UNAVAILABLE",
            "path": REVIEW_AUTHORITY,
            "sha256": REVIEW_AUTHORITY_SHA,
            "local_claude_review": "TEMPORARILY_NOT_REQUIRED"
        },
        "updated_note_latest": "All remote tasks are terminal and harvested. V28 binds accepted transcript47/47 and motion30/30. Codex temporary review and reversible platform staging pass; no generation remains active."
    })
    data["accounting"].update({
        "current_source_attributable_credits": 10900,
        "episode_cap": 11000,
        "headroom_before_dispatch": 100,
        "focused_video_projection_remaining": 0,
        "projected_total_after_success": 10900,
        "projected_headroom_after_success": 100,
        "generation_calls": 142,
        "active_generation_tasks": 0
    })
    execution = data["execution"]
    execution.update({
        "status": STATUS,
        "active_task_count": 0,
        "active_task_ids": [],
        "accepted_transcript_coverage": "47/47",
        "accepted_motion_coverage": "30/30",
        "accepted_source_count": 55,
        "latest_accepted_only_source_map": SOURCE_MAP,
        "latest_accepted_only_source_map_sha256": SOURCE_MAP_SHA,
        "latest_transcript_audit": TRANSCRIPT,
        "latest_transcript_audit_sha256": TRANSCRIPT_SHA,
        "last_real_progress": "Line28's invalid interpolated binding was removed. A materially changed native generation was cadence-repaired with source-timestamp-preserving mpdecimate, admitted without interpolation, and bound into V28. V28 passes objective/direct sampled QA, transcript47/47, motion30/30, and platform payload staging. Pay132/Refund0/Net132 raised episode net to10900/11000; no active generation remains.",
        "review_authority": "CODEX_TEMPORARY_FIRST_LINE_AND_SUPERVISORY_REVIEW",
        "independent_local_claude_review": "TEMPORARILY_NOT_REQUIRED_CLAUDE_UNAVAILABLE"
    })
    write(DISPATCH, data)


if __name__ == "__main__":
    update_queue()
    update_dispatch()
