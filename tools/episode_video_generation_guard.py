#!/usr/bin/env python3
"""Episode-level duplicate and credit guards for paid video generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIDEO_CREDIT_LIMIT = 6000
ALLOWED_APPROVERS = {"roger", "roger wu"}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def submission_authority_path(episode: str) -> Path:
    return ROOT / "workflow" / "submission_authority" / f"{episode.upper()}_VIDEO_SUBMISSION_AUTHORITY.json"


def evaluate_episode_submission_authority(
    episode: str,
    authority_path: str | Path | None = None,
) -> dict:
    """Honor an explicit episode hold before any paid video request can start."""
    path = Path(authority_path) if authority_path else submission_authority_path(episode)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        return {
            "schema": "qingshan.episode_video_submission_authority_gate.v1",
            "episode": episode.upper(),
            "status": "PASS",
            "video_submission_allowed": True,
            "authority_path": str(path),
            "authority_status": "NO_EXPLICIT_EPISODE_HOLD",
            "failures": [],
        }

    authority = _read_json(path)
    requested_allowed = authority.get("video_submission_allowed") is True
    failures = [] if requested_allowed else ["EPISODE_VIDEO_SUBMISSION_NOT_AUTHORIZED"]
    required_gate_path = authority.get("canonical_script_activation_gate")
    required_gate: dict = {}
    resolved_gate_path: Path | None = None
    if required_gate_path:
        resolved_gate_path = Path(str(required_gate_path))
        if not resolved_gate_path.is_absolute():
            resolved_gate_path = ROOT / resolved_gate_path
        required_gate = _read_json(resolved_gate_path)
        if requested_allowed:
            if not required_gate:
                failures.append("CANONICAL_SCRIPT_ACTIVATION_GATE_MISSING_OR_INVALID")
            elif (
                required_gate.get("status") != "PASS"
                or required_gate.get("canonical_activation_allowed") is not True
            ):
                failures.append("CANONICAL_SCRIPT_ACTIVATION_GATE_NOT_PASS")
    allowed = requested_allowed and not failures
    return {
        "schema": "qingshan.episode_video_submission_authority_gate.v1",
        "episode": episode.upper(),
        "status": "PASS" if allowed else "BLOCKED_EPISODE_VIDEO_SUBMISSION_AUTHORITY",
        "video_submission_allowed": allowed,
        "authority_path": str(path),
        "authority_sha256": _sha(path),
        "authority_status": authority.get("status"),
        "authorized_by": authority.get("authorized_by"),
        "reason": authority.get("reason"),
        "resume_policy": authority.get("resume_policy"),
        "canonical_script_activation_gate": str(resolved_gate_path) if resolved_gate_path else required_gate_path,
        "canonical_script_activation_gate_status": required_gate.get("status") if required_gate else None,
        "failures": failures,
    }


def _sha(path_value: str | Path) -> str | None:
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _prompt_sha(task: dict) -> str:
    if task.get("prompt_sha256"):
        return str(task["prompt_sha256"])
    if task.get("prompt_file"):
        value = _sha(task["prompt_file"])
        if value:
            return value
    return hashlib.sha256(str(task.get("prompt") or "").encode("utf-8")).hexdigest()


def generation_fingerprint(task: dict) -> str:
    """Hash only generation-affecting inputs, independent of task/version labels."""
    image_shas = []
    for value in task.get("reference_images", []):
        image_shas.append(_sha(value) or f"missing:{value}")
    audio_shas = []
    for value in task.get("reference_audios", []):
        audio_shas.append(_sha(value) or f"missing:{value}")
    bound_asset_shas = sorted(
        str(asset.get("sha256"))
        for asset in task.get("reference_assets", [])
        if asset.get("sha256")
    )
    payload = {
        "prompt_sha256": _prompt_sha(task),
        "model": task.get("model", "seedance-2.0-pro"),
        "duration": task.get("duration_seconds", task.get("duration", 4)),
        "aspect_ratio": task.get("aspect_ratio", "9:16"),
        "resolution": task.get("resolution", "720p"),
        "generation_mode": task.get("generation_mode", "shot_video"),
        "reference_image_shas": sorted(image_shas),
        "reference_audio_shas": sorted(audio_shas),
        "reference_audio_asset_ids": sorted(
            str(value)
            for value in [
                *task.get("reference_audio_asset_ids", []),
                *task.get("resolved_reference_audio_asset_ids", []),
            ]
        ),
        "reference_video_asset_ids": sorted(
            str(value)
            for value in [
                *task.get("reference_video_asset_ids", []),
                *task.get("resolved_reference_video_asset_ids", []),
            ]
        ),
        "reference_asset_shas": bound_asset_shas,
    }
    video_shas = [
        _sha(value) or f"missing:{value}"
        for value in task.get("reference_videos", [])
    ]
    if video_shas:
        payload["reference_video_shas"] = sorted(video_shas)
    # Transport revisions are generation-affecting only when explicitly set.
    # This preserves historical fingerprints while preventing an unchanged
    # retry after a provider-specific asset transport failure.
    if task.get("generation_transport_revision"):
        payload["generation_transport_revision"] = str(task["generation_transport_revision"])
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _receipt_payloads(current_receipt: dict | None = None):
    task_root = ROOT / "workflow" / "tasks"
    for path in task_root.rglob("*.json") if task_root.is_dir() else ():
        payload = _read_json(path)
        if isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
            yield str(path), payload
            continue
        singleton = _singleton_video_task(payload)
        if singleton:
            yield str(path), {
                "episode": payload.get("episode"),
                "tasks": [singleton],
            }
    if current_receipt:
        yield "CURRENT_IN_MEMORY_RECEIPT", current_receipt


def _singleton_video_task(payload: dict) -> dict | None:
    """Normalize completed single-video receipts that do not contain tasks[]."""
    if not isinstance(payload, dict) or not payload.get("task_id") or not payload.get("episode"):
        return None
    schema = str(payload.get("schema") or "").lower()
    model = str(payload.get("model") or "").lower()
    if "video" not in schema and not model.startswith("seedance"):
        return None
    credit = payload.get("actual_charged_credits")
    status = str(payload.get("status") or "").upper()
    completed = bool(payload.get("completed_at") or payload.get("output_path") or "COMPLETED" in status)
    success = True if completed else None
    return {
        "task_key": payload.get("task_key") or f"{payload.get('unit_id') or payload['episode']}-SINGLETON-VIDEO",
        "source_id": payload.get("unit_id"),
        "tool_type": "video_generation",
        "task_id": payload.get("task_id"),
        "workflow_credit_scope": payload.get("workflow_credit_scope"),
        "prompt_file": payload.get("prompt_file"),
        "config_path": payload.get("config_path"),
        "state": status.lower(),
        "remote_status": "completed" if completed else None,
        "output_path": payload.get("output_path"),
        "credit_attempts": [{
            "attempt": 1,
            "task_id": payload.get("task_id"),
            "success": success,
            "actual_charged_credits": credit if isinstance(credit, (int, float)) else None,
            "charge_status": (
                "EXACT_TASK_ID_STATEMENT_MATCH"
                if success is True and isinstance(credit, (int, float))
                else "SUCCESS_CREDIT_UNKNOWN_API_FIELD_MISSING"
                if success is True
                else "PENDING_REMOTE_RESULT"
            ),
            "evidence": "normalized_single_video_receipt",
        }],
    }


def _task_episode(task: dict, receipt_episode: object) -> str:
    match = re.match(r"^(E\d+)(?:-|_)", str(task.get("task_key") or ""), re.IGNORECASE)
    return match.group(1).upper() if match else str(receipt_episode or "").upper()


def _workflow_scope_registry(episode: str) -> tuple[Path, dict]:
    path = ROOT / "workflow" / "credit_scopes" / f"{episode.upper()}_VIDEO_CREDIT_SCOPE.json"
    return path, _read_json(path)


def _infer_workflow_scope(payload: dict, task: dict | None = None) -> str | None:
    task = task or {}
    for source in (task, payload):
        explicit = source.get("workflow_credit_scope") or source.get("workflow_scope_id")
        if explicit:
            return str(explicit)
    for source in (task, payload):
        for key in (
            "prompt_file",
            "config",
            "config_path",
            "manifest",
            "production_manifest_ref",
        ):
            value = str(source.get(key) or "")
            match = re.search(
                r"(?:^|/)tenants/[^/]+/projects/([^/]+)(?:/|$)",
                value,
            )
            if match:
                return match.group(1)
            match = re.search(
                r"(?:^|/)production/([^/]+)(?:/|$)",
                value,
            )
            if match:
                return match.group(1)
    return None


def find_existing_paid_candidate(episode: str, task: dict, current_receipt: dict | None = None) -> dict | None:
    """Return an accepted, nonfailed candidate with exactly the same paid inputs."""
    expected = generation_fingerprint(task)
    current_task_id = task.get("task_id")
    own_match = next(
        (
            row for row in task.get("credit_attempts") or []
            if row.get("success") is True
            and row.get("generation_fingerprint") == expected
            and row.get("task_id")
        ),
        None,
    )
    if own_match:
        return {
            "task_id": own_match["task_id"],
            "task_key": task.get("task_key"),
            "source_id": task.get("source_id"),
            "state": task.get("state") or task.get("status"),
            "output_path": task.get("output_path"),
            "sha256": task.get("sha256"),
            "receipt": "CURRENT_TASK_CREDIT_HISTORY",
            "generation_fingerprint": expected,
        }
    for receipt_path, payload in _receipt_payloads(current_receipt):
        for previous in payload.get("tasks", []):
            if previous is task or previous.get("tool_type") != "video_generation":
                continue
            if _task_episode(previous, payload.get("episode")) != str(episode).upper():
                continue
            state = str(previous.get("state") or previous.get("status") or "")
            if state in {"remote_failed_terminal", "submit_failed_terminal"}:
                continue
            task_id = previous.get("task_id")
            if not task_id or task_id == current_task_id:
                continue
            attempts = previous.get("credit_attempts") or []
            matching_attempt = next(
                (row for row in attempts if row.get("task_id") == task_id), None
            )
            if matching_attempt and matching_attempt.get("success") is False:
                continue
            previous_fingerprint = previous.get("generation_fingerprint") or generation_fingerprint(previous)
            if previous_fingerprint == expected:
                return {
                    "task_id": task_id,
                    "task_key": previous.get("task_key"),
                    "source_id": previous.get("source_id"),
                    "state": state,
                    "output_path": previous.get("output_path"),
                    "sha256": previous.get("sha256"),
                    "receipt": receipt_path,
                    "generation_fingerprint": expected,
                }
    return None


def _episode_video_attempts(
    episode: str,
    current_receipt: dict | None = None,
    workflow_scope: str | None = None,
) -> list[dict]:
    attempts_by_id: dict[str, dict] = {}
    anonymous: dict[tuple, dict] = {}

    def evidence_rank(row: dict) -> tuple[int, int]:
        """Prefer reconciled billing evidence over stale lifecycle snapshots."""
        credit = row.get("actual_charged_credits")
        if row.get("success") is True and isinstance(credit, (int, float)):
            return (4, 1)
        if row.get("success") is False and credit == 0:
            return (3, 1)
        if row.get("success") is True:
            return (2, 0)
        return (1, 0)

    for receipt_path, payload in _receipt_payloads(current_receipt):
        for task in payload.get("tasks", []):
            if task.get("tool_type") != "video_generation":
                continue
            if _task_episode(task, payload.get("episode")) != str(episode).upper():
                continue
            task_scope = _infer_workflow_scope(payload, task)
            if workflow_scope and task_scope != workflow_scope:
                continue
            attempts = list(task.get("credit_attempts") or [])
            if not attempts and (task.get("task_id") or task.get("submit_response")):
                state = str(task.get("state") or task.get("status") or "")
                remote_status = str(task.get("remote_status") or "").lower()
                output_exists = bool(task.get("output_path"))
                observed_credit = task.get("returned_credit")
                if remote_status == "completed" or output_exists or state in {"qa_pass", "qa_failed_terminal", "complete"}:
                    success = True
                    actual = observed_credit if isinstance(observed_credit, (int, float)) else None
                    charge_status = "SUCCESS_ACTUAL_CHARGE_RECORDED" if actual is not None else "SUCCESS_CREDIT_UNKNOWN_API_FIELD_MISSING"
                elif state in {"remote_failed_terminal", "submit_failed_terminal"} or remote_status in {"failed", "error", "cancelled", "timeout"}:
                    success = False
                    actual = 0
                    charge_status = "FAILED_ZERO_CHARGE"
                else:
                    success = None
                    actual = None
                    charge_status = "PENDING_REMOTE_RESULT"
                attempts = [{
                    "attempt": 1,
                    "task_id": task.get("task_id"),
                    "submitted_at": task.get("submitted_at"),
                    "success": success,
                    "actual_charged_credits": actual,
                    "charge_status": charge_status,
                    "evidence": "legacy_receipt_backfill",
                }]
            for attempt in attempts:
                row = dict(attempt)
                state = str(task.get("state") or task.get("status") or "").lower()
                remote_status = str(task.get("remote_status") or "").lower()
                credit = row.get("actual_charged_credits")
                completed = (
                    remote_status == "completed"
                    or bool(task.get("output_path"))
                    or state.startswith("qa_")
                    or "completed" in state
                )
                if row.get("success") is None and completed:
                    row["success"] = True
                    row["charge_status"] = (
                        "EXACT_TASK_ID_STATEMENT_MATCH"
                        if isinstance(credit, (int, float))
                        else "SUCCESS_CREDIT_UNKNOWN_API_FIELD_MISSING"
                    )
                row.update({
                    "task_key": task.get("task_key"),
                    "source_id": task.get("source_id"),
                    "receipt": receipt_path,
                    "workflow_credit_scope": task_scope,
                })
                task_id = row.get("task_id")
                if task_id:
                    key = str(task_id)
                    existing = attempts_by_id.get(key)
                    if existing is None or evidence_rank(row) > evidence_rank(existing):
                        attempts_by_id[key] = row
                else:
                    key = (
                        row.get("task_key"),
                        row.get("submitted_at"),
                        row.get("attempt"),
                        row.get("charge_status"),
                    )
                    anonymous[key] = row
    return [*attempts_by_id.values(), *anonymous.values()]


def _approval(episode: str) -> tuple[Path, dict]:
    path = ROOT / "workflow" / "approvals" / f"{episode.upper()}_VIDEO_CREDIT_LIMIT_APPROVAL.json"
    return path, _read_json(path)


def _account_window_credit_correction(episode: str) -> dict | None:
    report_root = ROOT / "workflow" / "credit_reports"
    pattern = f"{episode.upper()}_VIDEO_CREDIT_LIMIT_GATE_ACCOUNT_WINDOW_CORRECTED_*.json"
    for path in sorted(report_root.glob(pattern), reverse=True) if report_root.is_dir() else ():
        payload = _read_json(path)
        actual = payload.get("actual_charged_video_credits")
        recovered = payload.get("newly_recovered_charged_credits")
        if (
            str(payload.get("episode") or "").upper() == episode.upper()
            and isinstance(actual, (int, float))
            and isinstance(recovered, (int, float))
            and actual >= recovered
        ):
            return {
                "path": str(path),
                "sha256": _sha(path),
                "authoritative_total_at_reconciliation": float(actual),
                "receipt_scan_baseline_credits": float(actual) - float(recovered),
                "account_window_correction_credits": float(recovered),
            }
    return None


def _approval_binding_valid(episode: str, approval: dict) -> bool:
    if str(approval.get("schema") or "").endswith(".v2"):
        authority_ref = approval.get("standing_authority")
        registry_ref = approval.get("scope_registry")
        if (
            not authority_ref
            or not registry_ref
            or _sha(authority_ref) != str(approval.get("standing_authority_sha256") or "")
            or _sha(registry_ref) != str(approval.get("scope_registry_sha256") or "")
        ):
            return False
        authority_path = Path(str(authority_ref))
        registry_path = Path(str(registry_ref))
        if not authority_path.is_absolute():
            authority_path = ROOT / authority_path
        if not registry_path.is_absolute():
            registry_path = ROOT / registry_path
        authority = _read_json(authority_path)
        registry = _read_json(registry_path)
        approved_limit = approval.get("approved_limit_credits")
        standing_limit = authority.get("approved_limit_credits_per_episode")
        registry_limit = registry.get("configured_limit_credits")
        return (
            str(authority.get("status") or "").upper() == "APPROVED"
            and str(authority.get("approved_by") or "").strip().casefold() in ALLOWED_APPROVERS
            and isinstance(approved_limit, (int, float))
            and isinstance(standing_limit, (int, float))
            and isinstance(registry_limit, (int, float))
            and float(approved_limit) <= float(standing_limit)
            and float(approved_limit) == float(registry_limit)
            and str(registry.get("episode") or "").upper() == episode.upper()
            and str(registry.get("status") or "").upper() == "ACTIVE"
            and str(registry.get("workflow_scope_id") or "") == str(approval.get("workflow_scope_id") or "")
            and str(registry.get("canonical_script_sha256") or "") == str(approval.get("canonical_script_sha256") or "")
            and str(registry.get("canonical_manifest_sha256") or "") == str(approval.get("canonical_manifest_sha256") or "")
        )
    report_ref = approval.get("gate_report")
    expected_sha = str(approval.get("gate_report_sha256") or "").strip()
    if not report_ref or not expected_sha or _sha(report_ref) != expected_sha:
        return False
    report_path = Path(str(report_ref))
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report = _read_json(report_path)
    return str(report.get("episode") or "").upper() == episode.upper()


def evaluate_episode_credit_gate(
    episode: str,
    current_receipt: dict | None = None,
    *,
    limit: int | float | None = None,
) -> dict:
    scope_path, scope_registry = _workflow_scope_registry(episode)
    env_limit = os.environ.get("QINGSHAN_EPISODE_VIDEO_CREDIT_LIMIT")
    registry_limit = scope_registry.get("configured_limit_credits")
    configured_limit = float(
        limit
        if limit is not None
        else env_limit
        if env_limit is not None
        else registry_limit
        if isinstance(registry_limit, (int, float)) and registry_limit > 0
        else DEFAULT_VIDEO_CREDIT_LIMIT
    )
    workflow_scope = str(scope_registry.get("workflow_scope_id") or "").strip() or None
    attempts = _episode_video_attempts(episode, current_receipt, workflow_scope)
    successful = [row for row in attempts if row.get("success") is True]
    failed = [row for row in attempts if row.get("success") is False]
    pending = [row for row in attempts if row.get("success") is None and row.get("task_id")]
    unknown = [
        row for row in successful
        if not isinstance(row.get("actual_charged_credits"), (int, float))
    ]
    receipt_scan_known_total = sum(
        float(row["actual_charged_credits"])
        for row in successful
        if isinstance(row.get("actual_charged_credits"), (int, float))
    )
    correction = _account_window_credit_correction(episode)
    known_total = receipt_scan_known_total

    approval_path, approval = _approval(episode)
    approved_by = str(approval.get("approved_by") or "").strip()
    approved_limit = approval.get("approved_limit_credits")
    approval_valid = (
        str(approval.get("status") or "").upper() == "APPROVED"
        and approved_by.casefold() in ALLOWED_APPROVERS
        and isinstance(approved_limit, (int, float))
        and float(approved_limit) >= configured_limit
        and bool(approval.get("approved_at"))
        and str(approval.get("workflow_scope_id") or "") == str(workflow_scope or "")
        and _approval_binding_valid(episode, approval)
    )
    effective_limit = float(approved_limit) if approval_valid else configured_limit

    failures = []
    if unknown:
        failures.append("SUCCESSFUL_VIDEO_CREDIT_FIELDS_MISSING")
    if known_total > effective_limit:
        failures.append("EPISODE_VIDEO_CREDIT_LIMIT_EXCEEDED")
    status = "PASS"
    if "SUCCESSFUL_VIDEO_CREDIT_FIELDS_MISSING" in failures:
        status = "BLOCKED_VIDEO_CREDIT_ACCOUNTING_INCOMPLETE"
    elif failures:
        status = "BLOCKED_VIDEO_CREDIT_LIMIT_EXCEEDED"

    return {
        "schema": "qingshan.episode_video_credit_gate.v1",
        "episode": episode.upper(),
        "status": status,
        "workflow_scope": {
            "id": workflow_scope,
            "registry": str(scope_path),
            "registry_status": scope_registry.get("status"),
            "historical_receipts_excluded_from_gate": bool(workflow_scope),
        },
        "configured_limit_credits": configured_limit,
        "effective_limit_credits": effective_limit,
        "actual_charged_credits_known_total": known_total,
        "receipt_scan_known_credits": receipt_scan_known_total,
        "historical_account_window_audit": correction,
        "actual_total_complete": not unknown and not pending,
        "successful_attempt_count": len(successful),
        "successful_unknown_credit_count": len(unknown),
        "failed_zero_charge_count": len(failed),
        "pending_attempt_count": len(pending),
        "approval": {
            "path": str(approval_path),
            "valid": approval_valid,
            "approved_by": approved_by or None,
            "approved_limit_credits": approved_limit,
            "gate_report": approval.get("gate_report"),
            "gate_report_sha256": approval.get("gate_report_sha256"),
            "workflow_scope_id": approval.get("workflow_scope_id"),
            "binding_valid": _approval_binding_valid(episode, approval),
        },
        "failures": failures,
        "required_action": (
            "Reconcile every successful video's explicit returned credit before further paid submission."
            if unknown
            else "Roger must approve a higher explicit credit ceiling against this report before further video generation."
            if failures
            else "Continue tracking every video generation result."
        ),
        "policy": f"Each episode's active workflow production round uses its registered {configured_limit:g}-credit video limit. Historical rounds and account-window totals are audit-only. Failed generation costs 0; successful generation uses only explicit API-returned credit values; incomplete successful accounting blocks submission.",
    }


def credit_report_path(episode: str) -> Path:
    return ROOT / "workflow" / "credit_reports" / f"{episode.upper()}_VIDEO_CREDIT_LIMIT_GATE.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--limit", type=float, default=None)
    parser.add_argument("--out")
    args = parser.parse_args()
    report = evaluate_episode_credit_gate(args.episode, limit=args.limit)
    report["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    output = Path(args.out) if args.out else credit_report_path(args.episode)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
