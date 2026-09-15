#!/usr/bin/env python3
"""Fail closed when an episode is blocked by the producer schedule gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_QUEUE = ROOT / "workflow/work_queue.json"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _resolve_evidence_path(value: str | None, root: Path) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_final_lock(line: dict, root: Path) -> dict:
    lock_path = _resolve_evidence_path(
        line.get("final_lock") or line.get("active_evidence"), root
    )
    result = {
        "valid": False,
        "final_lock": str(lock_path) if lock_path else None,
        "qa_freeze": None,
        "final": None,
        "sha256": None,
        "reason": None,
    }
    if not lock_path or not lock_path.is_file():
        result["reason"] = "final_lock_missing"
        return result

    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result["reason"] = "final_lock_invalid"
        return result
    if not str(lock.get("status") or "").startswith("FINAL_LOCKED"):
        result["reason"] = "final_lock_status_invalid"
        return result

    qa_path = _resolve_evidence_path(line.get("qa_freeze") or lock.get("qa_freeze"), root)
    final_path = _resolve_evidence_path(line.get("final") or lock.get("final"), root)
    result["qa_freeze"] = str(qa_path) if qa_path else None
    result["final"] = str(final_path) if final_path else None
    if not qa_path or not qa_path.is_file():
        result["reason"] = "qa_freeze_missing"
        return result
    if not final_path or not final_path.is_file():
        result["reason"] = "final_media_missing"
        return result

    try:
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result["reason"] = "qa_freeze_invalid"
        return result
    if qa.get("status") != "PASS_FINAL_LOCK":
        result["reason"] = "qa_freeze_status_invalid"
        return result

    expected_sha = str(lock.get("sha256") or "").lower()
    if not expected_sha or str(qa.get("final_sha256") or "").lower() != expected_sha:
        result["reason"] = "lock_qa_sha_mismatch"
        return result
    actual_sha = _sha256(final_path)
    result["sha256"] = actual_sha
    if actual_sha != expected_sha:
        result["reason"] = "final_media_sha_mismatch"
        return result

    result["valid"] = True
    result["reason"] = "verified_final_lock"
    return result


def _episode_number(episode: str) -> int | None:
    value = episode.strip().upper()
    if not value.startswith("E") or not value[1:].isdigit():
        return None
    return int(value[1:])


def validate_release_branding(line: dict, root: Path) -> dict:
    gate_path = _resolve_evidence_path(
        line.get("latest_release_branding_render_gate")
        or line.get("release_branding_render_gate"),
        root,
    )
    result = {
        "valid": False,
        "gate": str(gate_path) if gate_path else None,
        "final": None,
        "sha256": None,
        "reason": None,
    }
    if not gate_path or not gate_path.is_file():
        result["reason"] = "release_branding_render_gate_missing"
        return result
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result["reason"] = "release_branding_render_gate_invalid"
        return result
    if gate.get("status") != "PASS" or gate.get("hard_gate_passed") is not True:
        result["reason"] = "release_branding_render_gate_not_pass"
        return result
    final_path = _resolve_evidence_path(
        line.get("replacement_production_master") or line.get("production_master"), root
    )
    result["final"] = str(final_path) if final_path else None
    if not final_path or not final_path.is_file():
        result["reason"] = "release_branding_final_media_missing"
        return result
    actual_sha = _sha256(final_path)
    result["sha256"] = actual_sha
    if str(gate.get("final_sha256") or "").lower() != actual_sha:
        result["reason"] = "release_branding_final_sha_mismatch"
        return result
    result["valid"] = True
    result["reason"] = "verified_release_branding_render_gate"
    return result


def validate_media_boundary_acceptance(line: dict, root: Path) -> dict:
    report_path = _resolve_evidence_path(
        line.get("media_boundary_acceptance")
        or line.get("media_boundary_acceptance_report"),
        root,
    )
    result = {
        "valid": False,
        "report": str(report_path) if report_path else None,
        "boundary_count": None,
        "reason": None,
    }
    if not report_path or not report_path.is_file():
        result["reason"] = "media_boundary_acceptance_missing"
        return result
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result["reason"] = "media_boundary_acceptance_invalid"
        return result
    if (
        report.get("schema") != "qingshan.media_boundary_acceptance.v1_safe_cut_and_real_transition"
        or report.get("status") != "PASS"
        or report.get("failures")
    ):
        result["reason"] = "media_boundary_acceptance_not_pass"
        return result
    rows = report.get("rows") or []
    if type(report.get("boundary_count")) is not int or report["boundary_count"] != len(rows) or any(
        not isinstance(row, dict) or row.get("status") != "PASS" for row in rows
    ):
        result["reason"] = "media_boundary_rows_incomplete"
        return result
    result["valid"] = True
    result["boundary_count"] = len(rows)
    result["reason"] = "verified_media_boundary_acceptance"
    return result


def validate_speaker_identity_voice_release(line: dict, root: Path) -> dict:
    """Verify the persisted face/lip-owner/voice report, not a copied PASS label."""
    report_path = _resolve_evidence_path(
        line.get("latest_speaker_identity_voice_release_gate")
        or line.get("speaker_identity_voice_release_gate"),
        root,
    )
    result = {
        "valid": False,
        "report": str(report_path) if report_path else None,
        "required_dialogue_count": None,
        "evidence_count": None,
        "reason": None,
    }
    if not report_path or not report_path.is_file():
        result["reason"] = "speaker_identity_voice_release_gate_missing"
        return result
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result["reason"] = "speaker_identity_voice_release_gate_invalid"
        return result
    if (
        report.get("schema")
        != "qingshan.speaker_identity_voice_release_gate.v2_diarization_lip_owner_voice_similarity"
        or report.get("status") != "PASS"
        or report.get("failures")
    ):
        result["reason"] = "speaker_identity_voice_release_gate_not_pass"
        return result
    required_count = report.get("required_dialogue_count")
    evidence_count = report.get("evidence_count")
    if (
        type(required_count) is not int
        or type(evidence_count) is not int
        or required_count <= 0
        or evidence_count != required_count
    ):
        result["reason"] = "speaker_identity_voice_release_evidence_incomplete"
        return result
    if line.get("episode") and report.get("episode") != line["episode"]:
        result["reason"] = "speaker_identity_voice_release_episode_mismatch"
        return result
    final_path = _resolve_evidence_path(
        line.get("replacement_production_master") or line.get("production_master") or line.get("final"), root
    )
    if not final_path or not final_path.is_file() or report.get("final_sha256") != _sha256(final_path):
        result["reason"] = "speaker_identity_voice_release_final_sha_mismatch"
        return result
    result.update({
        "valid": True,
        "required_dialogue_count": required_count,
        "evidence_count": evidence_count,
        "reason": "verified_speaker_identity_voice_release_gate",
    })
    return result


def validate_release_automation_policy(
    episode: str, work_queue: dict, root: Path = ROOT
) -> dict:
    """Verify persistent owner authority without inventing a content-review gate.

    Browser runtimes may still require a final action-time confirmation.  That is
    represented as one combined YouTube+Douyin commit boundary, never as a new
    episode-level editorial approval and never once per platform.
    """
    policy_path = root / "configs/PLATFORM_RELEASE_AUTOMATION_POLICY_V1.json"
    rules = work_queue.get("rules") or {}
    authority_path = _resolve_evidence_path(
        rules.get("auto_publish_owner_authority_ref"), root
    )
    result = {
        "valid": False,
        "policy": str(policy_path),
        "owner_authority": str(authority_path) if authority_path else None,
        "additional_owner_content_review_required": True,
        "confirmation_strategy": None,
        "auto_start_next_episode": False,
        "reason": None,
    }

    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result["reason"] = "release_automation_policy_missing_or_invalid"
        return result
    if (
        policy.get("schema")
        != "qingshan.platform_release_automation_policy.v1"
        or policy.get("status") != "ACTIVE"
    ):
        result["reason"] = "release_automation_policy_not_active"
        return result
    for exclusion in policy.get("permanent_exclusions") or []:
        if str(exclusion.get("episode") or "").upper() == episode.upper():
            result["reason"] = "episode_permanently_excluded_from_publication"
            return result

    if not authority_path or not authority_path.is_file():
        result["reason"] = "persistent_owner_publish_authority_missing"
        return result
    try:
        authority = json.loads(authority_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result["reason"] = "persistent_owner_publish_authority_invalid"
        return result
    authority_policy = authority.get("policy") or {}
    required_false = (
        rules.get("additional_owner_content_review_before_release_required") is False
        and authority_policy.get(
            "additional_owner_content_review_before_release_required"
        )
        is False
    )
    expected_strategy = (
        "ONE_COMBINED_CONFIRMATION_FOR_YOUTUBE_AND_DOUYIN_AT_FINAL_COMMIT"
    )
    strategy = rules.get("browser_action_confirmation_strategy")
    if (
        authority.get("status") != "ACTIVE"
        or not required_false
        or strategy != expected_strategy
        or authority_policy.get("browser_action_confirmation_strategy")
        != expected_strategy
    ):
        result["reason"] = "persistent_owner_publish_authority_policy_mismatch"
        return result

    result.update(
        {
            "valid": True,
            "additional_owner_content_review_required": False,
            "confirmation_strategy": expected_strategy,
            "auto_start_next_episode": bool(
                rules.get(
                    "auto_start_next_episode_after_both_terminal_publication_receipts"
                )
                and authority_policy.get(
                    "auto_start_next_episode_after_both_terminal_publication_receipts"
                )
            ),
            "reason": "persistent_owner_authority_verified_no_editorial_reapproval",
        }
    )
    return result


def evaluate_release_preflight(episode: str, work_queue: dict, root: Path = ROOT) -> dict:
    episode_upper = episode.strip().upper()
    gate = work_queue.get("schedule_gate") or {}
    blocked_entries = [str(item).upper() for item in gate.get("release_blocked_episodes", [])]
    matching_blocks = [
        item
        for item in blocked_entries
        if item == episode_upper or item.startswith(f"{episode_upper}_")
    ]

    line_holds = []
    verified_final_locks = []
    branding_checks = []
    boundary_checks = []
    speaker_identity_voice_checks = []
    publication_automation = validate_release_automation_policy(episode_upper, work_queue, root)
    coherent_candidates = []
    matched_lines = 0
    for line in (work_queue.get("lines") or {}).values():
        if str(line.get("episode") or "").upper() != episode_upper:
            if not re.search(r"(?:^|/)" + re.escape(episode_upper) + r"(?:[^0-9]|$)", str(line.get("canonical_script") or "")):
                continue
        matched_lines += 1
        candidate_valid = True
        if (_episode_number(episode_upper) or 0) >= 37:
            branding_checks.append(validate_release_branding(line, root))
            candidate_valid = candidate_valid and branding_checks[-1]["valid"]
        if (_episode_number(episode_upper) or 0) >= 45:
            boundary_checks.append(validate_media_boundary_acceptance(line, root))
            candidate_valid = candidate_valid and boundary_checks[-1]["valid"]
        if (_episode_number(episode_upper) or 0) >= 56:
            speaker_identity_voice_checks.append(
                validate_speaker_identity_voice_release(line, root)
            )
            candidate_valid = candidate_valid and speaker_identity_voice_checks[-1]["valid"]
        coherent_candidates.append(candidate_valid)
        status = str(line.get("status") or "").upper()
        stage = str(line.get("stage") or "").upper()
        if stage.startswith("FINAL_LOCKED_"):
            verification = validate_final_lock(line, root)
            if verification["valid"] and (_episode_number(episode_upper) or 0) >= 37:
                coherent_candidates[-1] = candidate_valid and verification["sha256"] == branding_checks[-1].get("sha256")
            if verification["valid"]:
                verified_final_locks.append(verification)
                continue
        if status.startswith("HOLD_") or status.startswith("STOPPED_"):
            line_holds.append(status)

    reasons = []
    if not matched_lines:
        reasons.append("episode_not_found_in_work_queue")
    elif not any(coherent_candidates):
        reasons.append("release_evidence_not_coherent_on_single_candidate")
    if matching_blocks:
        reasons.append("episode_listed_in_release_blocked_episodes")
    if line_holds:
        reasons.append("episode_line_is_held_or_stopped")
    if (_episode_number(episode_upper) or 0) >= 37:
        if not branding_checks or not any(row["valid"] for row in branding_checks):
            reasons.append("release_branding_render_gate_not_verified")
    if (_episode_number(episode_upper) or 0) >= 45:
        if not boundary_checks or not any(row["valid"] for row in boundary_checks):
            reasons.append("media_boundary_acceptance_not_verified")
    if (_episode_number(episode_upper) or 0) >= 56:
        if (
            not speaker_identity_voice_checks
            or not any(row["valid"] for row in speaker_identity_voice_checks)
        ):
            reasons.append("speaker_identity_voice_release_gate_not_verified")

    if (_episode_number(episode_upper) or 0) >= 51 and not publication_automation["valid"]:
        reasons.append("persistent_publication_automation_not_verified")
    allowed = not reasons
    return {
        "schema": "qingshan.platform_release_preflight.v1",
        "episode": episode_upper,
        "status": "PASS" if allowed else "HARD_HOLD",
        "release_allowed": allowed,
        "schedule_directive": gate.get("directive"),
        "matching_block_entries": matching_blocks,
        "line_hold_states": line_holds,
        "verified_final_locks": verified_final_locks,
        "release_branding_checks": branding_checks,
        "media_boundary_acceptance_checks": boundary_checks,
        "speaker_identity_voice_release_checks": speaker_identity_voice_checks,
        "publication_automation": publication_automation,
        "reasons": reasons,
        "checked_at": now_iso(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the producer work queue before any platform upload, publish, replace, or delete action."
    )
    parser.add_argument("--episode", required=True)
    parser.add_argument("--work-queue", default=str(DEFAULT_WORK_QUEUE))
    parser.add_argument("--receipt")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    args = parser.parse_args()

    queue_path = Path(args.work_queue).expanduser().resolve()
    try:
        work_queue = json.loads(queue_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result = {
            "schema": "qingshan.platform_release_preflight.v1",
            "episode": args.episode.strip().upper(),
            "status": "HARD_HOLD_INVALID_WORK_QUEUE",
            "release_allowed": False,
            "work_queue": str(queue_path),
            "error": str(exc),
            "checked_at": now_iso(),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    result = evaluate_release_preflight(args.episode, work_queue, root=args.project_root.expanduser().resolve())
    result["work_queue"] = str(queue_path)
    if args.receipt:
        receipt = Path(args.receipt).expanduser().resolve()
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["receipt"] = str(receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["release_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
