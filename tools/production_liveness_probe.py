#!/usr/bin/env python3
"""Is the production line actually moving? Answered from artifacts, not claims.

Authorization: `ROGER-20260718-EXTERNAL-WATCHDOG` — Roger, 2026-07-18:
「codex 的生产线经常会停下来，怎么让他修改自己的定时巡检机制，确保生产线主流程不会停」

Why the existing watchdog never fired (measured 2026-07-18):

  1. Circular dependency. `parallel_line_sla_breaches` lives in
     `workflow/dashboard/build_status.py`, which runs as part of codex's own
     patrol. codex stalls -> patrol stops -> watchdog stops. It can only fire
     while the thing it monitors is healthy. build_status.py last wrote its
     output 2026-07-17 16:35 (25h before this file was written); the patrol
     record 2026-07-17 07:52 (34h).

  2. Detection without action. The only callers of that breach function in the
     whole repo are build_status.py itself and its unit test. A breach paints a
     red field in a JSON nobody opens — no mailbox write, no task, no escalation.

  3. Self-declared heartbeat. `last_heartbeat_at` / `blocked_by` are fields the
     production agent writes about itself. Run against the live ledgers, all
     four lines were in breach on field validity alone (E18R and E19R had no
     `last_heartbeat_at` at all), which reports "the form is filled in wrong",
     not "the work stopped".

This probe therefore: (a) runs from an external scheduler, never from codex's
own loop; (b) derives liveness from filesystem mtimes and mailbox growth, which
the production agent cannot assert its way past; (c) is meant to be wired to an
action, not to a dashboard.

Measured stall on 2026-07-18 (files written per hour, PDT): 00h=58, 01h=42,
02h=12, 03-06h=0, 07h=1, 08h=8, 09h=14, 10h=16 — a 4.5-hour dead zone that
nothing detected or reported.

Outputs `qingshan.production_liveness.v1`.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any


RUNTIME_GATE_IDS = frozenset({"LINE-HEARTBEAT-WATCHDOG"})
RUNTIME_GATE_BINDINGS = {"LINE-HEARTBEAT-WATCHDOG": "current_line_handles"}

# Directories whose mtimes constitute evidence that work is happening.
WATCHED = ("configs", "qa", "exports", "working_assets", "workflow")

REMOTE_ACTIVE_STATUSES = {
    "REMOTE_RUNNING",
    "RUNNING",
    "PENDING",
    "GENERATING",
    "QUEUED",
    "SUPERVISOR_RUNNING",
}
REMOTE_TERMINAL_STATUS_TOKENS = ("COMPLETE", "COMPLETED", "FAILED", "CANCELLED", "RELEASED", "PUBLISHED")
RELEASED_STATUS_PREFIXES = ("RELEASED", "PUBLISHED")

# Paths that must be excluded from the liveness signal: they are written by the
# supervisor (me), not by the production line. Counting them would let the
# watchdog observe its own footsteps and conclude the line is alive.
EXCLUDED_MARKERS = (
    "gate_repair_",
    "script_review",
    "/reviews/",
    "CLAUDE_TO_CODEX",
    "CODEX_TO_CLAUDE",
    "storyclaw_outbox",
    "storyclaw_replies",
    "storyclaw_bridge_outgoing",
    "bridge_outgoing",
    "/tasks/",
    "agentcut_runtime_activation",
    "cl2x298_cut_contract",
    "gate_registry_v3_",
    "cl2x299_watchdog",
    "s3_relay/outbox",
    ".review_agent",
    "liveness",
    "/watchdog/",
    "watchdog_heartbeat",
    "/dashboard/",
    "ACTIVE_EPISODE_LINES_LATEST",
    "time_ledger",
    "/runtime/",
)

ALIVE_SECONDS = 1800  # 30 min without a new artifact -> slowing
STALLED_SECONDS = 3600  # 60 min -> stalled, act on it


def _is_supervisor_artifact(path: str) -> bool:
    return any(marker in path for marker in EXCLUDED_MARKERS)


def _episode_has_release_record(root: Path, episode: str | None) -> bool:
    if not episode:
        return False
    release_dir = root / "workflow" / "release" / episode.lower()
    for path in release_dir.glob("*.json") if release_dir.is_dir() else ():
        try:
            status = str(json.loads(path.read_text(encoding="utf-8")).get("status") or "").upper()
        except (OSError, json.JSONDecodeError):
            continue
        if status.startswith(RELEASED_STATUS_PREFIXES):
            return True
    return False


def _remote_task_ids(receipt: dict[str, Any]) -> list[str]:
    overall_status = str(receipt.get("status") or "").upper()
    if any(token in overall_status for token in REMOTE_TERMINAL_STATUS_TOKENS):
        return []
    remote_states = {"remote_running", "running", "pending", "queued", "processing", "submitted", "generating"}
    tasks = receipt.get("tasks") or receipt.get("results") or []
    return [
        str(task["task_id"])
        for task in tasks
        if task.get("task_id")
        and str(task.get("state") or task.get("status") or task.get("remote_status") or "").lower() in remote_states
    ]


def _latest_active_receipt(root: Path, episode: str, minimum_mtime: float = 0.0) -> tuple[Path, dict[str, Any], list[str]] | None:
    task_root = root / "workflow" / "tasks"
    candidates = sorted(
        task_root.glob(f"{episode}_*.json") if task_root.is_dir() else (),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            if path.stat().st_mtime < minimum_mtime:
                break
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        task_ids = _remote_task_ids(receipt)
        if task_ids:
            return path, receipt, task_ids
    return None


def newest_artifact(root: Path, watched=WATCHED) -> tuple[float, str] | None:
    """Most recent production artifact by mtime, excluding supervisor output."""
    best: tuple[float, str] | None = None
    for folder in watched:
        base = root / folder
        if not base.is_dir():
            continue
        for candidate in base.rglob("*"):
            if not candidate.is_file() or _is_supervisor_artifact(str(candidate)):
                continue
            try:
                value = candidate.stat().st_mtime
            except OSError:
                continue
            if best is None or value > best[0]:
                best = (value, str(candidate))
    return best


def current_line_handles(root: Path) -> list[dict[str, Any]]:
    """Return evidence handles for the current candidate lines.

    A recent frame or receipt proves that a file changed; it does not prove
    that production is still running. Current activity therefore requires an
    unfinished remote task or a separately recorded local process handle.
    """
    snapshot_path = root / "workflow/production_line/ACTIVE_EPISODE_LINES_LATEST.json"
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        snapshot = {}
    snapshot_lines = [
        line
        for line in (snapshot.get("parallel_lines") or [])
        if not _episode_has_release_record(root, line.get("episode"))
    ]
    if snapshot_lines:
        lines: list[dict[str, Any]] = []
        for line in snapshot_lines:
            evidence = line.get("evidence")
            receipt_path = root / evidence if evidence and not str(evidence).startswith("/") else Path(evidence) if evidence else None
            receipt: dict[str, Any] = {}
            if receipt_path and receipt_path.is_file():
                try:
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    receipt = {}
            receipt_mtime = receipt_path.stat().st_mtime if receipt_path and receipt_path.is_file() else 0.0
            active_override = _latest_active_receipt(root, str(line.get("episode") or ""), receipt_mtime)
            if active_override:
                receipt_path, receipt, _ = active_override
                receipt_mtime = receipt_path.stat().st_mtime
            dependency_stalled = False
            dependency_reason = None
            receipt_status = str(receipt.get("status") or "").upper()
            if receipt_status.startswith("BLOCKED") or receipt_status in {"FAIL", "FAILED"}:
                dependency_stalled = True
                dependency_reason = receipt_status
            if str(receipt.get("approval_owner") or "").upper() in {"UNASSIGNED", "UNSPECIFIED"} and receipt.get("approval_wait_is_valid") is False:
                dependency_stalled = True
                dependency_reason = "UNRESOLVED_DEPENDENCY"
            if receipt.get("approved_evidence_hits") == []:
                dependency_stalled = True
                dependency_reason = "UNRESOLVED_DEPENDENCY"
            pid = receipt.get("local_pid") or line.get("local_pid")
            local_active = False
            if pid:
                try:
                    os.kill(int(pid), 0)
                    local_active = True
                except (OSError, TypeError, ValueError):
                    local_active = False
            if dependency_stalled:
                local_active = False
            receipt_is_terminal = any(token in receipt_status for token in REMOTE_TERMINAL_STATUS_TOKENS)
            remote_evidence_fresh = bool(receipt_mtime and time.time() - receipt_mtime <= ALIVE_SECONDS)
            task_ids = _remote_task_ids(receipt) if remote_evidence_fresh else []
            if (
                not task_ids
                and not receipt_is_terminal
                and remote_evidence_fresh
                and receipt.get("task_id")
                and str(receipt.get("last_remote_status") or "").lower() in {"running", "queued", "pending", "generating"}
            ):
                task_ids = [receipt["task_id"]]
            lines.append({
                "episode": line.get("episode"),
                "status": receipt.get("status") or line.get("state") or "UNKNOWN",
                "task_id": task_ids[0] if task_ids else None,
                "task_ids": task_ids,
                "remote_active": bool(task_ids),
                "local_pid": pid,
                "local_active": local_active,
                "dependency_stalled": dependency_stalled,
                "liveness_reason": dependency_reason or (
                    "LIVE_LOCAL_PID" if local_active else "LIVE_REMOTE_TASK" if task_ids else "NO_LIVE_HANDLE"
                ),
                "evidence": str(receipt_path) if receipt_path else evidence,
                "next": "poll_internal_parallel_tasks",
            })
        return lines

    policy_path = root / "workflow/production_line/THREE_EPISODE_CONCURRENCY_POLICY.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        policy = {}
    episodes = [row.get("episode") for row in policy.get("current_slots", []) if row.get("episode")]
    lines: list[dict[str, Any]] = []
    for episode in episodes:
        candidates = sorted((root / "workflow" / "tasks").glob(f"{episode}_*json"))
        candidates = [path for path in candidates if "submit" in path.name or "status" in path.name]
        path = candidates[-1] if candidates else None
        if path is None:
            lines.append({"episode": episode, "status": "NO_RECEIPT", "remote_active": False})
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        status = str(data.get("status") or "").upper()
        task_id = data.get("task_id")
        local_pid = data.get("local_pid")
        local_active = False
        if local_pid:
            try:
                os.kill(int(local_pid), 0)
                local_active = True
            except (OSError, TypeError, ValueError):
                local_active = False
        remote_active = bool(task_id and status in REMOTE_ACTIVE_STATUSES)
        lines.append(
            {
                "episode": data.get("episode"),
                "status": status,
                "task_id": task_id,
                "remote_active": remote_active,
                "local_pid": local_pid,
                "local_active": local_active,
                "evidence": str(path),
                "next": data.get("next"),
            }
        )
    return lines


def target_active_line_count(root: Path) -> int:
    """Read the currently effective concurrency target, including debug overrides."""
    path = root / "workflow" / "production_line" / "THREE_EPISODE_CONCURRENCY_POLICY.json"
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 3
    override = policy.get("runtime_override") or {}
    value = override.get("target_concurrent_episode_lines", policy.get("target_concurrent_episode_lines", 3))
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 3


def probe(root: Path, now: float | None = None) -> dict[str, Any]:
    now = now if now is not None else time.time()
    newest = newest_artifact(root)
    current_lines = current_line_handles(root)
    active_count = sum(1 for line in current_lines if line["remote_active"] or line.get("local_active"))
    target_active_count = target_active_line_count(root)
    dependency_stalled_lines = [line.get("episode") for line in current_lines if line.get("dependency_stalled")]

    if newest is None:
        return {
            "schema": "qingshan.production_liveness.v1",
            "state": "UNKNOWN",
            "detail": "no production artifacts found",
            "action_required": True,
            "current_lines": current_lines,
            "active_handle_count": active_count,
            "target_active_handle_count": target_active_count,
            "dependency_stalled_lines": dependency_stalled_lines,
        }

    mtime, path = newest
    idle = now - mtime

    # Fixture roots and older projects may not have the current candidate
    # receipts; retain the artifact-threshold behavior there. On the live
    # project, once current lines are discoverable, missing handles are a
    # real partial stall even when an old frame was written recently.
    if current_lines and active_count < target_active_count:
        state = "PARTIAL_STALLED"
    elif idle > STALLED_SECONDS:
        state = "STALLED"
    elif idle > ALIVE_SECONDS:
        state = "SLOW"
    else:
        state = "ALIVE"

    # The self-declared ledger is reported alongside, never used to decide.
    ledger_claims: list[dict[str, Any]] = []
    for ledger in sorted((root / "workflow" / "time_ledger").glob("*.json")):
        try:
            data = json.loads(ledger.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ledger_claims.append(
            {
                "line": ledger.stem.replace("_time_ledger", ""),
                "blocked_by": data.get("blocked_by"),
                "last_heartbeat_at": data.get("last_heartbeat_at"),
            }
        )

    return {
        "schema": "qingshan.production_liveness.v1",
        "state": state,
        "idle_seconds": round(idle),
        "idle_minutes": round(idle / 60, 1),
        "newest_artifact": path,
        "newest_artifact_epoch": mtime,
        "thresholds": {"slow_seconds": ALIVE_SECONDS, "stalled_seconds": STALLED_SECONDS},
        "evidence_basis": "filesystem_mtime_excluding_supervisor_output",
        "current_lines": current_lines,
        "active_handle_count": active_count,
        "target_active_handle_count": target_active_count,
        "dependency_stalled_lines": dependency_stalled_lines,
        "activity_rule": "unfinished remote task_id or separately recorded live local PID; recent artifacts alone do not count",
        "self_declared_ledger_FOR_REFERENCE_ONLY": ledger_claims,
        "action_required": state in ("PARTIAL_STALLED", "STALLED", "UNKNOWN") or bool(dependency_stalled_lines),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out")
    args = parser.parse_args()

    result = probe(Path(args.root).expanduser().resolve())
    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "self_declared_ledger_FOR_REFERENCE_ONLY"}, ensure_ascii=False))
    return 0 if result["state"] in ("ALIVE", "SLOW") else 1


if __name__ == "__main__":
    raise SystemExit(main())
