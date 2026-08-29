#!/usr/bin/env python3
"""Fail closed when task-local waits are promoted into a global production wait.

This gate is intentionally independent from legacy episode queue refreshers.
Episode queues model episode slots rather than per-task dependency lanes.  A
heartbeat must materialize one supported task-lane state document and run this
gate before reporting or persisting any global-wait decision.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_STATES = frozenset(
    {"READY", "RUNNING", "WAITING_DEPENDENCY", "REMOTE_WAIT", "QA", "TERMINAL"}
)
SUPPORTED_INPUT_SCHEMAS = frozenset(
    {
        "backlotos.task_lane_scheduler_state.v1",
        "qingshan.task_lane_scheduler_state.v1",
    }
)
AUDIT_ONLY_DELIVERABLES = frozenset(
    {"AUDIT", "QA_REPORT", "QA_RECEIPT", "WATCHDOG", "PARITY_CHECK", "OBSERVATION", "PIPELINE_GATE"}
)
FABRICATED_ID_RE = re.compile(r".*(WATCHDOG|PARITY|OBSERVATION|AUDIT).*")
REMOTE_ID_KEYS = (
    "remote_task_id",
    "provider_task_id",
    "submission_task_id",
    "video_task_id",
    "external_task_id",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _failure(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _fabricated_successor_reasons(task: dict[str, Any]) -> list[str]:
    """Return the governance-v2 reasons an active successor is non-production work."""
    reasons: list[str] = []
    deliverable = task.get("deliverable_type")
    if not isinstance(deliverable, str) or not deliverable.strip():
        reasons.append("NO_DELIVERABLE_TYPE")
    elif deliverable.upper() in AUDIT_ONLY_DELIVERABLES:
        reasons.append("AUDIT_ONLY_DELIVERABLE")
    if task.get("observation_only") is True:
        reasons.append("OBSERVATION_ONLY")
    if FABRICATED_ID_RE.match(str(task.get("task_id") or "").upper()):
        reasons.append("WATCHDOG_STYLE_TASK_ID")
    return reasons


def _remote_task_id(task: dict[str, Any]) -> str | None:
    for key in REMOTE_ID_KEYS:
        value = task.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value)
    return None


def audit_scheduler_state(
    payload: dict[str, Any], *, observed_at: datetime | None = None
) -> dict[str, Any]:
    observed_at = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    failures: list[dict[str, Any]] = []
    if payload.get("schema") not in SUPPORTED_INPUT_SCHEMAS:
        failures.append(_failure("UNSUPPORTED_SCHEMA", actual=payload.get("schema")))

    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        failures.append(_failure("TASKS_MISSING_OR_EMPTY"))
        tasks = []

    scheduler = payload.get("scheduler_decision")
    if not isinstance(scheduler, dict) or not isinstance(scheduler.get("global_wait"), bool):
        failures.append(_failure("GLOBAL_WAIT_DECISION_MISSING_OR_NOT_BOOLEAN"))
        global_wait = None
    else:
        global_wait = scheduler["global_wait"]

    task_ids = [str(task.get("task_id") or "") for task in tasks]
    duplicate_ids = sorted(task_id for task_id, count in Counter(task_ids).items() if task_id and count > 1)
    if duplicate_ids:
        failures.append(_failure("DUPLICATE_TASK_ID", task_ids=duplicate_ids))
    known_ids = {task_id for task_id in task_ids if task_id}

    normalized: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        task_id = str(task.get("task_id") or "")
        lane_id = str(task.get("lane_id") or "")
        state = str(task.get("state") or "")
        if not task_id:
            failures.append(_failure("TASK_ID_MISSING", task_index=index))
        if not lane_id:
            failures.append(_failure("LANE_ID_MISSING", task_id=task_id or None, task_index=index))
        if state not in ALLOWED_STATES:
            failures.append(_failure("INVALID_TASK_STATE", task_id=task_id or None, state=state))

        predecessor = task.get("exact_predecessor_task_id")
        if state == "WAITING_DEPENDENCY":
            if not isinstance(predecessor, str) or not predecessor.strip():
                failures.append(_failure("WAITING_DEPENDENCY_EXACT_PREDECESSOR_MISSING", task_id=task_id or None))
            elif predecessor == task_id:
                failures.append(_failure("WAITING_DEPENDENCY_SELF_REFERENCE", task_id=task_id))
            elif predecessor not in known_ids and not isinstance(
                payload.get("terminal_task_ledger"), str
            ):
                failures.append(
                    _failure(
                        "WAITING_DEPENDENCY_EXACT_PREDECESSOR_UNKNOWN",
                        task_id=task_id or None,
                        exact_predecessor_task_id=predecessor,
                    )
                )
        if state == "REMOTE_WAIT" and task.get("wait_scope") != "TASK_LOCAL":
            failures.append(
                _failure(
                    "REMOTE_WAIT_SCOPE_MUST_BE_TASK_LOCAL",
                    task_id=task_id or None,
                    wait_scope=task.get("wait_scope"),
                )
            )
        freshness_valid = True
        continuous_executor_valid = True
        if state in {"RUNNING", "QA", "REMOTE_WAIT"}:
            lease_owner = task.get("lease_owner")
            if not isinstance(lease_owner, str) or not lease_owner.strip():
                freshness_valid = False
                failures.append(
                    _failure("ACTIVE_TASK_LEASE_OWNER_MISSING", task_id=task_id or None)
                )
            for field in ("last_progress_at", "next_due_at", "lease_expires_at"):
                parsed = _parse_utc_timestamp(task.get(field))
                if parsed is None:
                    freshness_valid = False
                    failures.append(
                        _failure(
                            "ACTIVE_TASK_TIMESTAMP_MISSING_OR_INVALID",
                            task_id=task_id or None,
                            field=field,
                            actual=task.get(field),
                        )
                    )
                    continue
                if field == "last_progress_at" and parsed > observed_at:
                    freshness_valid = False
                    failures.append(
                        _failure(
                            "ACTIVE_TASK_PROGRESS_IN_FUTURE",
                            task_id=task_id or None,
                            actual=task.get(field),
                            observed_at=observed_at.isoformat(),
                        )
                    )
                if field == "next_due_at" and parsed < observed_at:
                    freshness_valid = False
                    failures.append(
                        _failure(
                            "ACTIVE_TASK_NEXT_DUE_EXPIRED",
                            task_id=task_id or None,
                            actual=task.get(field),
                            observed_at=observed_at.isoformat(),
                        )
                    )
                if field == "lease_expires_at" and parsed <= observed_at:
                    freshness_valid = False
                    failures.append(
                        _failure(
                            "ACTIVE_TASK_LEASE_EXPIRED",
                            task_id=task_id or None,
                            actual=task.get(field),
                            observed_at=observed_at.isoformat(),
                        )
                        )
            heartbeat = payload.get("heartbeat_integration")
            require_continuous_executor = (
                isinstance(heartbeat, dict)
                and heartbeat.get("require_continuous_executor_ack_before_return") is True
            )
            if require_continuous_executor and state in {"RUNNING", "QA", "REMOTE_WAIT"}:
                if task.get("execution_mode") != "CONTINUOUS":
                    continuous_executor_valid = False
                    failures.append(
                        _failure(
                            "ACTIVE_TASK_CONTINUOUS_EXECUTION_MODE_MISSING",
                            task_id=task_id or None,
                            actual=task.get("execution_mode"),
                        )
                    )
                executor_handle = task.get("executor_handle")
                if not isinstance(executor_handle, str) or not executor_handle.strip():
                    continuous_executor_valid = False
                    failures.append(
                        _failure("ACTIVE_TASK_EXECUTOR_HANDLE_MISSING", task_id=task_id or None)
                    )
                if task.get("executor_task_id") != task_id:
                    continuous_executor_valid = False
                    failures.append(
                        _failure(
                            "ACTIVE_TASK_EXECUTOR_TASK_BINDING_MISMATCH",
                            task_id=task_id or None,
                            actual=task.get("executor_task_id"),
                        )
                    )
                acknowledged_at = _parse_utc_timestamp(task.get("executor_acknowledged_at"))
                last_progress_at = _parse_utc_timestamp(task.get("last_progress_at"))
                if (
                    acknowledged_at is None
                    or acknowledged_at > observed_at
                    or (last_progress_at is not None and acknowledged_at < last_progress_at)
                ):
                    continuous_executor_valid = False
                    failures.append(
                        _failure(
                            "ACTIVE_TASK_EXECUTOR_ACK_MISSING_OR_INVALID",
                            task_id=task_id or None,
                            actual=task.get("executor_acknowledged_at"),
                        )
                    )
                next_wakeup_at = _parse_utc_timestamp(task.get("executor_next_wakeup_at"))
                lease_expires_at = _parse_utc_timestamp(task.get("lease_expires_at"))
                next_due_at = _parse_utc_timestamp(task.get("next_due_at"))
                if (
                    next_wakeup_at is None
                    or next_wakeup_at <= observed_at
                    or (lease_expires_at is not None and next_wakeup_at > lease_expires_at)
                    or (next_due_at is not None and next_wakeup_at > next_due_at)
                ):
                    continuous_executor_valid = False
                    failures.append(
                        _failure(
                            "ACTIVE_TASK_EXECUTOR_NEXT_WAKEUP_MISSING_OR_INVALID",
                            task_id=task_id or None,
                            actual=task.get("executor_next_wakeup_at"),
                        )
                    )
        normalized.append(
            {
                "task_id": task_id,
                "lane_id": lane_id,
                "state": state,
                "zero_cost": task.get("zero_cost") is True,
                "exact_predecessor_task_id": predecessor,
                "freshness_valid": freshness_valid,
                "continuous_executor_valid": continuous_executor_valid,
                "fabricated_successor_reasons": _fabricated_successor_reasons(task),
                "blocked_by": task.get("blocked_by") or task.get("wait_reason"),
                "remote_task_id": _remote_task_id(task),
            }
        )

    ready = [task for task in normalized if task["state"] == "READY"]
    ready_zero_cost = [task for task in ready if task["zero_cost"]]
    qa = [task for task in normalized if task["state"] == "QA"]
    running = [task for task in normalized if task["state"] == "RUNNING"]
    waiting_dependency = [task for task in normalized if task["state"] == "WAITING_DEPENDENCY"]
    remote_wait = [task for task in normalized if task["state"] == "REMOTE_WAIT"]
    if global_wait is True and ready_zero_cost:
        failures.append(
            _failure(
                "GLOBAL_WAIT_MASKS_READY_ZERO_COST_TASKS",
                task_ids=[task["task_id"] for task in ready_zero_cost],
                lane_ids=sorted({task["lane_id"] for task in ready_zero_cost}),
            )
        )
    if global_wait is True and qa:
        failures.append(
            _failure(
                "GLOBAL_WAIT_MASKS_ACTIVE_QA",
                task_ids=[task["task_id"] for task in qa],
                lane_ids=sorted({task["lane_id"] for task in qa}),
            )
        )

    remote_lanes = {task["lane_id"] for task in remote_wait}
    ready_other_lanes = [task for task in ready if task["lane_id"] not in remote_lanes]
    if remote_wait and ready_other_lanes and global_wait is True:
        failures.append(
            _failure(
                "REMOTE_WAIT_MASKS_READY_OTHER_LANES",
                remote_wait_task_ids=[task["task_id"] for task in remote_wait],
                ready_task_ids=[task["task_id"] for task in ready_other_lanes],
            )
        )

    active_local = running + qa
    active_successors = running + qa + remote_wait
    fabricated_successors = [
        task for task in active_successors if task["fabricated_successor_reasons"]
    ]
    genuine_active_successors = [
        task
        for task in active_successors
        if not task["fabricated_successor_reasons"]
        and (task["state"] in {"RUNNING", "QA"} or task["remote_task_id"] is not None)
    ]
    fresh_active_successors = [task for task in genuine_active_successors if task["freshness_valid"]]
    unfinished = ready + active_local + waiting_dependency + remote_wait
    legal_blocker = scheduler.get("legal_blocker") if isinstance(scheduler, dict) else None
    if unfinished and not ready and not active_local and not remote_wait:
        valid_legal_blocker = (
            isinstance(legal_blocker, dict)
            and isinstance(legal_blocker.get("code"), str)
            and bool(legal_blocker["code"].strip())
            and isinstance(legal_blocker.get("evidence_ref"), str)
            and bool(legal_blocker["evidence_ref"].strip())
            and isinstance(legal_blocker.get("next_recheck_at"), str)
            and bool(legal_blocker["next_recheck_at"].strip())
        )
        if not valid_legal_blocker:
            failures.append(
                _failure(
                    "IDLE_WITH_UNFINISHED_WORK_AND_NO_LEGAL_BLOCKER",
                    waiting_dependency_task_ids=[task["task_id"] for task in waiting_dependency],
                    required_fields=["code", "evidence_ref", "next_recheck_at"],
                )
            )

    heartbeat = payload.get("heartbeat_integration")
    if not isinstance(heartbeat, dict):
        heartbeat = {}
    continuation_required = heartbeat.get("require_active_successor_before_return") is True
    continuous_executor_required = (
        heartbeat.get("require_continuous_executor_ack_before_return") is True
    )
    episode_terminal = heartbeat.get("episode_terminal") is True
    if continuation_required and not episode_terminal and fabricated_successors:
        failures.append(
            _failure(
                "FABRICATED_SUCCESSOR",
                task_ids=[task["task_id"] for task in fabricated_successors],
                reasons={
                    task["task_id"]: task["fabricated_successor_reasons"]
                    for task in fabricated_successors
                },
                detail="Audit-only successors cannot be used as heartbeat liveness evidence.",
            )
        )
    fresh_active_work = [task for task in active_successors if task["freshness_valid"]]
    continuous_active_work = [
        task
        for task in fresh_active_work
        if task["continuous_executor_valid"]
    ]
    if (
        continuation_required
        and continuous_executor_required
        and not episode_terminal
        and fresh_active_work
        and len(continuous_active_work) != len(fresh_active_work)
    ):
        failures.append(
            _failure(
                "HEARTBEAT_RETURN_WITHOUT_CONTINUOUS_EXECUTOR_ACK",
                task_ids=[
                    task["task_id"]
                    for task in fresh_active_work
                    if not task["continuous_executor_valid"]
                ],
                detail=(
                    "A fresh QA/RUNNING record is not proof of continued execution. "
                    "Bind a continuous executor handle and a future wakeup before returning."
                ),
            )
        )

    blocked_nonterminal = [
        task
        for task in normalized
        if task["state"] != "TERMINAL" and task["blocked_by"]
    ]
    if fabricated_successors:
        heartbeat_verdict = "FABRICATED_SUCCESSOR"
    elif genuine_active_successors:
        heartbeat_verdict = "ACTIVE"
    elif blocked_nonterminal:
        heartbeat_verdict = "BLOCKED_ON_INPUT"
    else:
        heartbeat_verdict = "IDLE_LEGAL"

    if not unfinished:
        liveness_state = "COMPLETE"
    elif ready or active_local:
        liveness_state = "ACTIVE"
    elif remote_wait:
        liveness_state = "REMOTE_WAIT_TASK_LOCAL"
    elif isinstance(legal_blocker, dict):
        liveness_state = "LEGALLY_BLOCKED"
    else:
        liveness_state = "FALSE_IDLE"

    counts = Counter(task["state"] for task in normalized)
    return {
        "schema": "backlotos.task_lane_global_wait_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "episode": payload.get("episode"),
        "scheduler_decision": {"global_wait": global_wait},
        "state_counts": {state: counts.get(state, 0) for state in sorted(ALLOWED_STATES)},
        "dispatchable_ready_task_ids": [task["task_id"] for task in ready],
        "ready_zero_cost_task_ids": [task["task_id"] for task in ready_zero_cost],
        "qa_task_ids": [task["task_id"] for task in qa],
        "remote_wait_task_ids": [task["task_id"] for task in remote_wait],
        "active_successor_task_ids": [task["task_id"] for task in fresh_active_successors],
        "genuine_active_task_ids": [task["task_id"] for task in genuine_active_successors],
        "fabricated_successors": [
            {
                "task_id": task["task_id"],
                "state": task["state"],
                "reasons": task["fabricated_successor_reasons"],
            }
            for task in fabricated_successors
        ],
        "heartbeat_verdict": heartbeat_verdict,
        "continuous_executor_task_ids": [task["task_id"] for task in continuous_active_work],
        "stale_or_invalid_active_task_ids": [
            task["task_id"] for task in active_successors if not task["freshness_valid"]
        ],
        "heartbeat_return_allowed": heartbeat_verdict != "FABRICATED_SUCCESSOR",
        "remote_wait_isolated_from_ready_lanes": bool(remote_wait and ready_other_lanes and global_wait is False),
        "liveness_state": liveness_state,
        "active_local_task_ids": [task["task_id"] for task in active_local],
        "legal_blocker": legal_blocker,
        "failures": failures,
        "policy": {
            "ready_zero_cost_blocks_global_wait": True,
            "waiting_dependency_requires_exact_predecessor_task_id": True,
            "remote_wait_scope": "TASK_LOCAL",
            "remote_wait_never_masks_ready_other_lane": True,
            "qa_is_active_work": True,
            "idle_unfinished_requires_legal_blocker_evidence": True,
            "heartbeat_is_checkpoint_not_completion": True,
            "idle_legal": True,
            "blocked_on_input_legal": True,
            "fabricated_successor_forbidden": True,
            "active_successor_required_when_configured": False,
            "active_successor_requires_live_lease": True,
            "active_successor_requires_unexpired_next_due": True,
            "active_successor_requires_valid_progress_timestamp": True,
            "continuous_executor_ack_required_when_configured": continuous_executor_required,
            "continuous_executor_requires_bound_task_id": True,
            "continuous_executor_requires_future_wakeup": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = audit_scheduler_state(read_json(args.state))
    if args.out:
        write_json_atomic(args.out, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
