#!/usr/bin/env python3
"""Fail closed when an episode is blocked by the producer schedule gate."""

from __future__ import annotations

import argparse
import hashlib
import json
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
    if int(report.get("boundary_count") or -1) != len(rows) or any(
        row.get("status") != "PASS" for row in rows
    ):
        result["reason"] = "media_boundary_rows_incomplete"
        return result
    result["valid"] = True
    result["boundary_count"] = len(rows)
    result["reason"] = "verified_media_boundary_acceptance"
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
    for line in (work_queue.get("lines") or {}).values():
        if str(line.get("episode") or "").upper() != episode_upper:
            if str(line.get("canonical_script") or "").find(f"/{episode_upper}") < 0:
                continue
        if (_episode_number(episode_upper) or 0) >= 37:
            branding_checks.append(validate_release_branding(line, root))
        if (_episode_number(episode_upper) or 0) >= 45:
            boundary_checks.append(validate_media_boundary_acceptance(line, root))
        status = str(line.get("status") or "").upper()
        stage = str(line.get("stage") or "").upper()
        if stage.startswith("FINAL_LOCKED_"):
            verification = validate_final_lock(line, root)
            if verification["valid"]:
                verified_final_locks.append(verification)
                continue
        if status.startswith("HOLD_") or status.startswith("STOPPED_"):
            line_holds.append(status)

    reasons = []
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

    result = evaluate_release_preflight(args.episode, work_queue)
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
