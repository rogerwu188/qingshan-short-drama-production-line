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
#: Remote states after which the provider holds a finished clip for the task.
COMPLETED_REMOTE_STATUSES = frozenset({"completed", "succeeded", "success"})
#: Stale-binding guard (JA-01 E01, 2026-11-19).  ``0`` / ``false`` / ``off`` / ``no`` turns it off.
STALE_BINDING_GUARD_ENV = "NALU_S6_STALE_BINDING_GUARD"
#: A completed binding whose request is not the unit's current request is moved under this prefix
#: (``<store>/<EP>/_stale_<UTC stamp>/``): out of every live-row scan (``*.json`` / ``<key>__*.json``),
#: still read by the budget ledger and the usage attribution, never deleted.
STALE_ARCHIVE_PREFIX = "_stale_"


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
    return _status_report_task_ids(root, episode, TERMINAL_REMOTE_STATUSES)


def completed_task_ids(root: Path, episode: str) -> set[str]:
    """Task ids a remote status report shows as completed (the clip exists at the provider)."""
    return _status_report_task_ids(root, episode, COMPLETED_REMOTE_STATUSES)


def _status_report_task_ids(root: Path, episode: str, statuses: frozenset[str]) -> set[str]:
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
                if str(row.get("remote_status") or "").lower() in statuses and row.get("task_id"):
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
    current_task: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Live bound takes of ``task_key``, oldest first (see module docstring).

    With ``current_task`` (the unit's request as compiled NOW) and the stale-binding guard on, a COMPLETED
    take whose recorded request differs from it is not live: it is a finished take of a request that is no
    longer the unit's (see ``classify_live_bindings``).  A differing take still rendering stays live (never a
    second charge) and carries ``stale_request_in_flight``."""
    video_dirs = default_video_dirs(root, episode) if video_dirs is None else list(video_dirs)
    rows = _live_rows(transaction_dir, task_key, root=root, episode=episode,
                      exclude_fingerprints=exclude_fingerprints, video_dirs=video_dirs,
                      failed_task_ids=failed_task_ids)
    if current_task is None or not rows:
        return rows
    verdict = classify_live_bindings(rows, current_task, root=root, episode=episode, video_dirs=video_dirs)
    stale = {row["transaction"] for row in verdict["stale_completed"]}
    in_flight = {row["transaction"] for row in verdict["stale_in_flight"]}
    out = []
    for row in rows:
        if row["transaction"] in stale:
            continue
        if row["transaction"] in in_flight:
            row = {**row, "stale_request_in_flight": True}
        out.append(row)
    return out


def _live_rows(
    transaction_dir: Path,
    task_key: str,
    *,
    root: Path,
    episode: str,
    exclude_fingerprints: Iterable[str] = (),
    video_dirs: Iterable[Path] | None = None,
    failed_task_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
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
            "provider_remote_status": row.get("provider_remote_status"),
        })
    rows.sort(key=lambda r: (_epoch(r["bound_at"]) or 0.0, r["task_id"]))
    return rows


# --------------------------------------------------------------------------- #
# Stale-binding guard (fleet device JA-01, E01, 2026-11-19)
# --------------------------------------------------------------------------- #
# The line owner ordered E01 redone in anime style.  The device archived workflow/nalu/E01/ but not the durable
# video store, so 28 units still had completed live bindings of the OLD live-action requests.  The recompiled
# anime tasks had new fingerprints, the live-binding rule above ("a bound take is never POSTed again, whatever
# its recompiled fingerprint says") read every one of them as "already bound -> poll", and the old takes were
# harvested as the new episode: VU-001's transaction prompt sha was the archived v1 prompt, not the anime one.
#
# The live-binding rule exists for fingerprint drift with a byte-identical request (lab E05: prompt, ordered
# references, model and duration identical).  So before a COMPLETED binding is reused, its recorded request
# identity -- ``prompt_sha256`` and the ordered source ``reference_sha256`` the intent recorded -- is compared
# with the unit's current compiled task:
#
# * equal (or not comparable: a side records nothing)  -> reused exactly as before;
# * different, take completed, no clip of the unit on disk -> stale: the transaction (and an alternate take
#   harvested from it) is MOVED to ``<store>/<EP>/_stale_<stamp>/`` and the unit goes through the normal
#   gates (budget / episode cap, D-11, order, reviews) as a fresh attempt;
# * different, take still rendering -> never re-POSTed (that would be a second charge): kept live, warned.
#
# ``sent_reference_sha256`` is deliberately not compared: it is what the transport sent (JPEG/portrait
# normalisation, and on an H3 burned-text retry the deliberately perturbed @Image1 bytes, tools/h3_burn_retry),
# which the compiled task never carries.  The source shas are what the request was built from.
#
# A unit whose clip is on disk is never touched (D-46 / lab Holmes E06: the harvested take is the unit's
# authority whatever its recompiled prompt says; it is only replaced through a park + controlled redo).  Takes
# parked for a redo / burn retry are already not live (bound before the park), and a restored best burn take
# is a clip on disk, so neither is ever classified here.


def stale_binding_guard_enabled() -> bool:
    import os  # noqa: PLC0415
    return str(os.environ.get(STALE_BINDING_GUARD_ENV, "1")).strip().lower() not in {"0", "false", "off", "no"}


def request_identity(row: dict[str, Any]) -> dict[str, Any]:
    refs = row.get("reference_sha256")
    return {"prompt_sha256": str(row.get("prompt_sha256") or "") or None,
            "reference_sha256": [str(v) for v in refs] if isinstance(refs, list) else None}


def request_identity_differs(binding: dict[str, Any], task: dict[str, Any]) -> bool:
    """True only when a field both sides record differs (unknown on either side is never "different")."""
    old, new = request_identity(binding), request_identity(task)
    if old["prompt_sha256"] and new["prompt_sha256"] and old["prompt_sha256"] != new["prompt_sha256"]:
        return True
    if old["reference_sha256"] is not None and new["reference_sha256"] is not None \
            and old["reference_sha256"] != new["reference_sha256"]:
        return True
    return False


def binding_completed(row: dict[str, Any], completed_ids: set[str] | None = None) -> bool:
    """The provider finished this take (settlement on the transaction, or a remote status report)."""
    status = str(row.get("provider_remote_status") or row.get("remote_status") or "").lower()
    if status in COMPLETED_REMOTE_STATUSES:
        return True
    return bool(completed_ids) and str(row.get("task_id") or "") in completed_ids


def clip_on_disk(task_key: str, video_dirs: Iterable[Path]) -> bool:
    return any((Path(d) / f"{task_key}.mp4").is_file() for d in video_dirs)


def classify_live_bindings(rows: list[dict[str, Any]], task: dict[str, Any], *, root: Path, episode: str,
                           video_dirs: Iterable[Path] | None = None,
                           completed_ids: set[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Split live bindings (``_live_rows`` / ``live_bindings`` rows) of one unit against its current task."""
    out: dict[str, list[dict[str, Any]]] = {"reuse": [], "stale_completed": [], "stale_in_flight": []}
    task_key = str(task.get("task_key") or "")
    video_dirs = default_video_dirs(root, episode) if video_dirs is None else list(video_dirs)
    if not stale_binding_guard_enabled() or not task_key or clip_on_disk(task_key, video_dirs):
        out["reuse"] = list(rows)
        return out
    for row in rows:
        if not request_identity_differs(row, task):
            out["reuse"].append(row)
            continue
        if completed_ids is None and not binding_completed(row):
            completed_ids = completed_task_ids(root, episode)
        out["stale_completed" if binding_completed(row, completed_ids) else "stale_in_flight"].append(row)
    return out


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def archive_stale_binding(transaction: Path, *, stamp: str | None = None, task_id: str | None = None,
                          video_dirs: Iterable[Path] = (), reason: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Move one stale, completed transaction (and its archived siblings) to ``_stale_<stamp>/``, under its flock.

    Never deletes.  Returns None when the row changed under us (no longer bound to ``task_id``) or is gone.
    An alternate take harvested from it (``<video>/_alt_takes/<key>__take_<id8>.mp4``) moves to
    ``<video>/_alt_takes/_stale_<stamp>/``.  A ``_stale_*`` folder is no park directory: a stale binding is not
    a rejected take, so it never moves a unit's park time."""
    import fcntl  # noqa: PLC0415
    import os  # noqa: PLC0415
    transaction = Path(transaction)
    if not transaction.is_file():
        return None
    stamp = stamp or _utc_stamp()
    archive_dir = transaction.parent / f"{STALE_ARCHIVE_PREFIX}{stamp}"
    moved: list[str] = []
    with transaction.with_suffix(".lock").open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            row = json.loads(transaction.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(row, dict) or row.get("state") != BOUND_STATE \
                or (task_id is not None and str(row.get("task_id") or "") != str(task_id)):
            return None
        archive_dir.mkdir(parents=True, exist_ok=True)
        siblings = sorted(p for p in transaction.parent.glob(transaction.name + ".*") if p.is_file())
        for path in [transaction, *siblings]:
            os.replace(path, archive_dir / path.name)
            moved.append(str(path))
    key = str(row.get("task_key") or transaction.name.split("__", 1)[0])
    tid = str(row.get("task_id") or "")
    for video_dir in video_dirs:
        alt = Path(video_dir) / ALT_TAKES_DIRNAME / f"{key}__take_{tid[:8]}.mp4"
        if tid and alt.is_file():
            target = alt.parent / f"{STALE_ARCHIVE_PREFIX}{stamp}"
            target.mkdir(parents=True, exist_ok=True)
            os.replace(alt, target / alt.name)
            moved.append(str(alt))
    record = {"task_key": key, "task_id": tid, "submission_fingerprint": row.get("submission_fingerprint"),
              "archived_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "archive_dir": str(archive_dir), "moved": moved,
              "old_prompt_sha256": row.get("prompt_sha256"), "old_reference_sha256": row.get("reference_sha256"),
              **(reason or {})}
    # audit trail beside the archived row; .jsonl, so no ``*.json`` scan reads it as a transaction
    with (archive_dir / "STALE_BINDING_ARCHIVE.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def retire_stale_bindings(transaction_dir: Path, task: dict[str, Any], *, root: Path, episode: str,
                          exclude_fingerprints: Iterable[str] = (), video_dirs: Iterable[Path] | None = None,
                          stamp: str | None = None, log=None) -> dict[str, list[dict[str, Any]]]:
    """Archive every stale COMPLETED live binding of ``task`` and report differing ones still in flight.

    Logs ``S6_STALE_BINDING_ARCHIVED unit=... old_prompt=... new_prompt=...`` per archived take and
    ``S6_STALE_BINDING_IN_FLIGHT ...`` (a warning; nothing is POSTed) per differing take still rendering."""
    out: dict[str, list[dict[str, Any]]] = {"archived": [], "in_flight": []}
    if not stale_binding_guard_enabled():
        return out
    task_key = str(task.get("task_key") or "")
    video_dirs = default_video_dirs(root, episode) if video_dirs is None else list(video_dirs)
    rows = _live_rows(transaction_dir, task_key, root=root, episode=episode,
                      exclude_fingerprints=exclude_fingerprints, video_dirs=video_dirs)
    if not rows:
        return out
    verdict = classify_live_bindings(rows, task, root=root, episode=episode, video_dirs=video_dirs)
    stamp = stamp or _utc_stamp()
    new_prompt = str(task.get("prompt_sha256") or "")
    for row in verdict["stale_completed"]:
        record = archive_stale_binding(Path(row["transaction"]), stamp=stamp, task_id=row["task_id"],
                                       video_dirs=video_dirs,
                                       reason={"reason": "COMPLETED_BINDING_REQUEST_DIFFERS_FROM_CURRENT",
                                               "new_prompt_sha256": task.get("prompt_sha256"),
                                               "new_reference_sha256": task.get("reference_sha256")})
        if record is None:
            continue
        out["archived"].append(record)
        if log:
            log(f"S6_STALE_BINDING_ARCHIVED unit={task_key} task_id={row['task_id']} "
                f"old_prompt={str(row.get('prompt_sha256') or '')[:16]} new_prompt={new_prompt[:16]} "
                f"refs_changed={request_identity(row)['reference_sha256'] != request_identity(task)['reference_sha256']} "
                f"archive={record['archive_dir']}")
    for row in verdict["stale_in_flight"]:
        out["in_flight"].append({k: row.get(k) for k in ("task_key", "task_id", "transaction", "prompt_sha256")})
        if log:
            log(f"S6_STALE_BINDING_IN_FLIGHT WARNING unit={task_key} task_id={row['task_id']} "
                f"old_prompt={str(row.get('prompt_sha256') or '')[:16]} new_prompt={new_prompt[:16]}: the take "
                "of a different request is still rendering; waiting for it, never re-POSTed (no second charge)")
    return out


#: Fleet 2026-11-12: every S6 wave on 20 devices failed remotely at once (``Provider error``, cost 0 -- the
#: account behind the video key ran dry).  The bound rows kept ``SUBMITTED_TASK_ID_BOUND``, so the planner and
#: the submitter both saw "already bound, poll only" and no device could ever POST that unit again.  A take the
#: provider terminally failed AND settled at zero cost owes us nothing and cost us nothing: it is released to a
#: new attempt, at most this many times per transaction (a provider that keeps refusing the same request is a
#: content problem the executor handles by recomposing, which is a new fingerprint).
ZERO_COST_TERMINAL_RETRY_LIMIT = 2
#: The limit counts releases inside this window only (fleet 2026-11-12: a provider outage used up both releases
#: in minutes and the hourly outage retry could never POST again).  Zero-cost takes cost nothing; the window
#: keeps a refusing provider from being hammered, and a content refusal is still the executor's to recompose.
ZERO_COST_RETRY_WINDOW_SECONDS = 3600
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


def zero_cost_retries_used(transaction: Path, *, window_seconds: float | None = ZERO_COST_RETRY_WINDOW_SECONDS) -> int:
    """Releases of this transaction (archived failed takes), within the last ``window_seconds`` when given."""
    import time  # noqa: PLC0415
    transaction = Path(transaction)
    cutoff = time.time() - window_seconds if window_seconds else None
    n = 0
    for p in transaction.parent.glob("*"):
        if not p.name.startswith(transaction.name + ZERO_COST_ARCHIVE_INFIX):
            continue
        try:
            if cutoff is None or p.stat().st_mtime >= cutoff:
                n += 1
        except OSError:
            continue
    return n


def zero_cost_retryable(transaction: Path, row: dict[str, Any]) -> bool:
    """True when this bound row may be released to a new attempt (see ZERO_COST_TERMINAL_RETRY_LIMIT)."""
    return zero_cost_terminal_failure(row) and zero_cost_retries_used(transaction) < ZERO_COST_TERMINAL_RETRY_LIMIT


def release_zero_cost_terminal(transaction: Path, *, now: str | None = None,
                               lock_held: bool = False) -> dict[str, Any] | None:
    """Release a zero-cost terminal failure for a new attempt, under the transaction's flock.

    The failed take is kept verbatim beside the transaction (``<name>.zero_cost_failed.<task_id>``, not
    ``*.json``, so no store scan mistakes it for a live row) and the transaction itself becomes
    ``VERIFIED_ZERO_RETRYABLE`` -- the settled, zero-credit state every reader already lets a new POST through.
    Returns the released row, or None when the row is not (or no longer) releasable.

    ``lock_held``: the caller already holds the transaction's ``.lock`` flock (the submitter's
    ``submit_one`` does).  flock is per open file, so taking it again here would block on ourselves --
    fleet 2026-11-12 (296675c): every S6 worker thread deadlocked on its own lock."""
    import contextlib  # noqa: PLC0415
    import fcntl  # noqa: PLC0415
    transaction = Path(transaction)
    if not transaction.is_file():
        return None
    stamp = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with (contextlib.nullcontext() if lock_held else transaction.with_suffix(".lock").open("a")) as handle:
        if handle is not None:
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
            "zero_cost_retries_total": zero_cost_retries_used(transaction, window_seconds=None),
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
    for path in [*root.glob("*/*.json"), *root.glob(f"*/{STALE_ARCHIVE_PREFIX}*/*.json")]:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(row, dict) and row.get("task_id"):
            ids.add(str(row["task_id"]))
    return ids
