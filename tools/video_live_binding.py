#!/usr/bin/env python3
"""Live provider bindings of a video task, independent of the submission fingerprint.

Lab E05, 2026-10-26.  The durable video transaction store is keyed by ``task_key`` + the
submission fingerprint, and the fingerprint covers episode-wide compiled metadata (for
example ``audio_profile_binding.generation_contract_sha256``, the hash of the WHOLE
episode generation contract).  A controlled redo of one unit (VU-014) rewrote that
contract while another unit's redo (VU-001, frozen wave 28) was still rendering; the next
S6 re-entry recompiled wave 28, the VU-001 fingerprint drifted although its prompt,
ordered references, model and duration were byte-identical, the store lookup missed the
bound transaction and a second 48-credit task was POSTed.

A *live binding* is a transaction of the same ``task_key`` that

* is ``SUBMITTED_TASK_ID_BOUND`` with a provider task id,
* is not known to have terminally failed remotely (failed / error / cancelled / timeout in a
  remote status report, or an explicit ``remote_terminal_state`` on the row), and
* was bound AFTER the unit's clip was last parked for a redo (``video*/_superseded*|_rejected*|
  _parked*|_archive*/<task_key>.mp4``; the park is a rename, so the parked file's ctime is the
  park time).  A take bound before the last park is the take that was rejected; one bound after
  it is the redo that is still owed to us.

While a live binding exists the task is the provider task we already paid for: it is polled
and harvested, never POSTed again, whatever its recompiled fingerprint says.  The only way
around that is an explicit ``supersedes_submission_fingerprints`` entry on the task.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

BOUND_STATE = "SUBMITTED_TASK_ID_BOUND"
#: Same prefixes nalu_budget_ledger treats as parked evidence.
PARKED_DIR_PREFIXES = ("_superseded", "_rejected", "_parked", "_archive")
#: Remote states after which the provider will never deliver the clip (no charge stands).
TERMINAL_REMOTE_STATUSES = frozenset({"failed", "error", "cancelled", "canceled", "timeout"})
#: Alternate takes of one unit are harvested here (never the assembly path, never a park dir).
ALT_TAKES_DIRNAME = "_alt_takes"


def _epoch(value: Any) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def bound_at(row: dict[str, Any]) -> float | None:
    return _epoch(row.get("response_recorded_at") or row.get("intent_recorded_at"))


def episode_dirs(root: Path, episode: str) -> list[Path]:
    workflow = Path(root) / "workflow"
    if not episode or not workflow.is_dir():
        return []
    return sorted(path for path in workflow.glob(f"*/{episode}") if path.is_dir())


def default_video_dirs(root: Path, episode: str) -> list[Path]:
    return [d / name for d in episode_dirs(root, episode) for name in ("video", "video_ab")]


def park_time(task_key: str, video_dirs: Iterable[Path]) -> float | None:
    """Latest time a clip of ``task_key`` was moved into a park directory (None: never parked)."""
    latest = None
    for video_dir in video_dirs:
        video_dir = Path(video_dir)
        if not video_dir.is_dir():
            continue
        for sub in video_dir.iterdir():
            if not (sub.is_dir() and sub.name.startswith(PARKED_DIR_PREFIXES)):
                continue
            clip = sub / f"{task_key}.mp4"
            if clip.is_file():
                stamp = clip.stat().st_ctime
                latest = stamp if latest is None else max(latest, stamp)
    return latest


def terminal_failed_task_ids(root: Path, episode: str) -> set[str]:
    """Task ids a remote status report shows as terminally failed."""
    failed: set[str] = set()
    for d in episode_dirs(root, episode):
        for path in [*d.glob("preproduction/reports/*REMOTE_STATUS*.json"), *d.glob("video_ab/*REMOTE_STATUS*.json")]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for row in (payload.get("results") or []) if isinstance(payload, dict) else []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("remote_status") or "").lower() in TERMINAL_REMOTE_STATUSES and row.get("task_id"):
                    failed.add(str(row["task_id"]))
    return failed


def live_bindings(
    transaction_dir: Path,
    task_key: str,
    *,
    root: Path,
    episode: str,
    exclude_fingerprints: Iterable[str] = (),
    video_dirs: Iterable[Path] | None = None,
    failed_task_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Live bound takes of ``task_key``, oldest first (see module docstring)."""
    transaction_dir = Path(transaction_dir)
    if not transaction_dir.is_dir():
        return []
    excluded = {str(value) for value in exclude_fingerprints if value}
    parked = park_time(task_key, default_video_dirs(root, episode) if video_dirs is None else video_dirs)
    failed = terminal_failed_task_ids(root, episode) if failed_task_ids is None else failed_task_ids
    rows: list[dict[str, Any]] = []
    for path in sorted(transaction_dir.glob(f"{task_key}__*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(row, dict) or str(row.get("task_key") or task_key) != task_key:
            continue
        task_id = str(row.get("task_id") or "")
        if row.get("state") != BOUND_STATE or not task_id:
            continue
        fingerprint = str(row.get("submission_fingerprint") or "")
        if fingerprint and fingerprint in excluded:
            continue
        if row.get("remote_terminal_state") or task_id in failed:
            continue
        stamp = bound_at(row)
        if parked is not None and (stamp is None or stamp <= parked):
            continue
        rows.append({
            "task_key": task_key, "task_id": task_id, "submission_fingerprint": fingerprint,
            "transaction": str(path), "receipt": row.get("receipt"),
            "bound_at": row.get("response_recorded_at") or row.get("intent_recorded_at"),
            "request_sha256": (row.get("request_binding") or {}).get("request_sha256"),
            "prompt_sha256": row.get("prompt_sha256"), "reference_sha256": row.get("reference_sha256"),
        })
    rows.sort(key=lambda r: (_epoch(r["bound_at"]) or 0.0, r["task_id"]))
    return rows


#: Fleet 2026-11-12: every S6 wave on 20 devices failed remotely at once (``Provider error``, cost 0 -- the
#: account behind the video key ran dry).  The bound rows kept ``SUBMITTED_TASK_ID_BOUND``, so the planner and
#: the submitter both saw "already bound, poll only" and no device could ever POST that unit again.  A take the
#: provider terminally failed AND settled at zero cost owes us nothing and cost us nothing: it is released to a
#: new attempt, at most this many times per transaction (a provider that keeps refusing the same request is a
#: content problem the executor handles by recomposing, which is a new fingerprint).
ZERO_COST_TERMINAL_RETRY_LIMIT = 2
ZERO_COST_ARCHIVE_INFIX = ".zero_cost_failed."
RELEASED_STATE = "VERIFIED_ZERO_RETRYABLE"


def zero_cost_terminal_failure(row: dict[str, Any]) -> bool:
    """A bound take the provider terminally failed and settled at exactly zero credits."""
    if not isinstance(row, dict) or row.get("state") != BOUND_STATE or not row.get("task_id"):
        return False
    terminal = str(row.get("remote_terminal_state") or "").lower()
    if terminal not in TERMINAL_REMOTE_STATUSES and terminal != "cancelled":
        return False
    cost = row.get("provider_cost_credits")
    return isinstance(cost, (int, float)) and not isinstance(cost, bool) and float(cost) == 0.0


def zero_cost_retries_used(transaction: Path) -> int:
    transaction = Path(transaction)
    return sum(1 for p in transaction.parent.glob("*")
               if p.name.startswith(transaction.name + ZERO_COST_ARCHIVE_INFIX))


def zero_cost_retryable(transaction: Path, row: dict[str, Any]) -> bool:
    """True when this bound row may be released to a new attempt (see ZERO_COST_TERMINAL_RETRY_LIMIT)."""
    return zero_cost_terminal_failure(row) and zero_cost_retries_used(transaction) < ZERO_COST_TERMINAL_RETRY_LIMIT


def release_zero_cost_terminal(transaction: Path, *, now: str | None = None) -> dict[str, Any] | None:
    """Release a zero-cost terminal failure for a new attempt, under the transaction's flock.

    The failed take is kept verbatim beside the transaction (``<name>.zero_cost_failed.<task_id>``, not
    ``*.json``, so no store scan mistakes it for a live row) and the transaction itself becomes
    ``VERIFIED_ZERO_RETRYABLE`` -- the settled, zero-credit state every reader already lets a new POST through.
    Returns the released row, or None when the row is not (or no longer) releasable."""
    import fcntl  # noqa: PLC0415
    transaction = Path(transaction)
    if not transaction.is_file():
        return None
    stamp = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with transaction.with_suffix(".lock").open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            row = json.loads(transaction.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not zero_cost_retryable(transaction, row):
            return None
        task_id = str(row["task_id"])
        archive = transaction.with_name(transaction.name + ZERO_COST_ARCHIVE_INFIX + task_id)
        archive.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        released = {key: row[key] for key in ("schema", "task_key", "submission_fingerprint", "provider",
                                               "prompt_sha256", "reference_sha256", "receipt") if key in row}
        released.update({
            "state": RELEASED_STATE, "credit_status": "NOT_CHARGED_RETRYABLE",
            "retry_reason": "REMOTE_TERMINAL_FAILURE_ZERO_COST",
            "released_task_id": task_id, "released_at": stamp,
            "released_remote_terminal_state": row.get("remote_terminal_state"),
            "released_provider_failure": row.get("provider_failure"),
            "released_take_archive": archive.name,
            "zero_cost_retries_used": zero_cost_retries_used(transaction),
        })
        temporary = transaction.with_suffix(transaction.suffix + ".part")
        temporary.write_text(json.dumps(released, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(transaction)
        return released


def attributed_task_ids(transaction_root: Path) -> set[str]:
    """Every provider task id any durable video transaction is bound to (all episodes)."""
    ids: set[str] = set()
    root = Path(transaction_root)
    if not root.is_dir():
        return ids
    for path in root.glob("*/*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(row, dict) and row.get("task_id"):
            ids.add(str(row["task_id"]))
    return ids
