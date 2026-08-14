#!/usr/bin/env python3
"""Safely preview or refresh the producer queue from current evidence.

The command is intentionally dry-run by default.  A write requires an explicit
``--write`` flag plus the exact SHA-256 of the current queue.  This protects the
episode-owned aggregate from legacy runtime projections and accidental invocations
such as ``--help``.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "workflow/production_line/ACTIVE_EPISODE_LINES_LATEST.json"
OUT = ROOT / "workflow/work_queue.json"
CONCURRENCY_POLICY = ROOT / "workflow/production_line/THREE_EPISODE_CONCURRENCY_POLICY.json"
RELEASED_PREFIXES = ("RELEASED", "PUBLISHED", "GRANDFATHERED_PUBLIC")
PUBLIC_PREFIXES = ("PUBLIC", "PUBLISHED", "RELEASED", "GRANDFATHERED_PUBLIC")
ACTIVE_RELEASE_TOKENS = (
    "UPLOAD_ACTIVE",
    "RELEASE_ACTIVE",
    "PROCESSING_ACTIVE",
    "PLATFORM_REVIEW_PENDING",
    "PLATFORM_REVIEWING",
    "SUBMITTED_REVIEW",
)
ACTIVE_PROCESS_TOKENS = (
    "agentcut render",
    "agentcut render-batch",
    "episode_parallel_batch_supervisor.py",
    "qingshan-review review-many",
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="persist the refresh; without this flag the command is read-only",
    )
    parser.add_argument(
        "--expected-current-sha256",
        help="required with --write; compare-and-swap guard for workflow/work_queue.json",
    )
    return parser


def projection_episodes(projection: dict) -> set[str]:
    return {
        str(row.get("episode") or "").upper()
        for row in (projection.get("lines") or {}).values()
        if isinstance(row, dict) and row.get("episode")
    }


def merge_runtime_projection(current: dict, projection: dict) -> dict:
    """Preserve an active E40 aggregate and attach runtime evidence conservatively."""
    if str(current.get("active_episode") or "").upper() != "E40":
        return projection

    if "E40" not in projection_episodes(projection):
        raise RuntimeError("runtime projection omits active E40; refusing legacy downgrade")

    merged = dict(current)
    merged["updated_at"] = now()
    merged["latest_runtime_refresh"] = {
        "status": "PASS_CONSERVATIVE_MERGE_E40_AGGREGATE_PRESERVED",
        "recorded_at": now(),
        "projection": projection,
    }
    return merged


def _critical_e40_values(payload: dict) -> dict:
    keys = {
        "active_episode",
        "status",
        "blocked_by",
        "next_action",
        "e40_credits",
        "canonical",
    }
    keys.update(key for key in payload if key.startswith("latest_e40_"))
    return {key: payload.get(key) for key in sorted(keys)}


def _write_backup(backup_path: Path, data: bytes) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with backup_path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if backup_path.read_bytes() != data:
            raise RuntimeError(f"backup collision with different bytes: {backup_path}")
    if sha256_bytes(backup_path.read_bytes()) != sha256_bytes(data):
        raise RuntimeError(f"backup verification failed: {backup_path}")


def _atomic_cas_write(payload: dict, expected_sha256: str) -> tuple[str, str]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or ""):
        raise RuntimeError("--expected-current-sha256 must be one lowercase 64-hex SHA")

    lock_path = OUT.with_suffix(OUT.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        current_bytes = OUT.read_bytes()
        observed_sha = sha256_bytes(current_bytes)
        if observed_sha != expected_sha256:
            raise RuntimeError(
                f"CAS mismatch: expected {expected_sha256}, observed {observed_sha}"
            )

        current = json.loads(current_bytes)
        final_payload = merge_runtime_projection(current, payload)
        if str(current.get("active_episode") or "").upper() == "E40":
            before = _critical_e40_values(current)
            after = _critical_e40_values(final_payload)
            if before != after:
                raise RuntimeError("E40 conservative merge changed protected aggregate fields")

        rendered = (json.dumps(final_payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = OUT.parent / ".work_queue.backups" / f"work_queue.{stamp}.{observed_sha}.json"
        _write_backup(backup, current_bytes)

        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=OUT.parent, prefix=".work_queue.", suffix=".tmp", delete=False
            ) as handle:
                temp_name = handle.name
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            if sha256_bytes(OUT.read_bytes()) != expected_sha256:
                raise RuntimeError("CAS changed after backup; refusing replacement")
            os.replace(temp_name, OUT)
            temp_name = ""
            directory_fd = os.open(OUT.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)

    return sha256_bytes(rendered), str(backup)


def episode_number(value: str) -> int:
    match = re.fullmatch(r"E(\d+)", value.upper())
    return int(match.group(1)) if match else 10**9


def released(episode: str) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    release_dir = ROOT / "workflow/release" / episode.lower()
    for path in sorted(release_dir.glob("*.json")) if release_dir.is_dir() else ():
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        status = str(payload.get("status") or "").upper()
        if status.startswith(RELEASED_PREFIXES):
            evidence.append(str(path.relative_to(ROOT)))
            continue

        platform_statuses: dict[str, str] = {}

        def collect(value: object, key_path: tuple[str, ...] = ()) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    collect(child, (*key_path, str(key).lower()))
                return
            if not key_path or key_path[-1] not in {"status", "visibility", "state"}:
                return
            joined = "/".join(key_path)
            for platform in ("youtube", "douyin"):
                if platform in joined:
                    platform_statuses[platform] = str(value or "").upper()

        collect(payload)
        if all(platform_statuses.get(name, "").startswith(PUBLIC_PREFIXES) for name in ("youtube", "douyin")):
            evidence.append(str(path.relative_to(ROOT)))
    return bool(evidence), evidence


def latest_release_preflights() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in (ROOT / "workflow/tasks").glob("E*_YOUTUBE_RELEASE_CHANNEL_PREFLIGHT_*.json"):
        try:
            episode = str(read_json(path).get("episode") or "").upper()
        except (OSError, json.JSONDecodeError):
            continue
        if not episode or (episode in result and result[episode].stat().st_mtime >= path.stat().st_mtime):
            continue
        result[episode] = path
    return result


def is_release_active_status(status: str) -> bool:
    return any(token in str(status or "").upper() for token in ACTIVE_RELEASE_TOKENS)


def active_release_evidence(episode: str) -> str | None:
    release_dir = ROOT / "workflow/release" / episode.lower()
    latest: tuple[float, str] | None = None
    for path in release_dir.glob("*.json") if release_dir.is_dir() else ():
        try:
            status = str(read_json(path).get("status") or "").upper()
        except (OSError, json.JSONDecodeError):
            continue
        if not is_release_active_status(status):
            continue
        candidate = (path.stat().st_mtime, str(path.relative_to(ROOT)))
        if latest is None or candidate[0] > latest[0]:
            latest = candidate
    return latest[1] if latest else None


def episode_process_map(ps_output: str) -> dict[str, list[int]]:
    """Map real production PIDs to every episode named in the process command."""
    result: dict[str, list[int]] = {}
    for raw in ps_output.splitlines():
        match = re.match(r"\s*(\d+)\s+(.+)$", raw)
        if not match:
            continue
        pid = int(match.group(1))
        command = match.group(2)
        lowered = command.lower()
        if not any(token in lowered for token in ACTIVE_PROCESS_TOKENS):
            continue
        episodes = {value.upper() for value in re.findall(r"(?<![A-Za-z0-9])e\d+(?!\d)", lowered)}
        for episode in episodes:
            result.setdefault(episode, []).append(pid)
    return result


def active_local_processes() -> dict[str, list[int]]:
    return episode_process_map(subprocess.check_output(["ps", "-axo", "pid=,command="], text=True))


def active_runtime_evidence(ps_output: str) -> dict[str, dict[str, list]]:
    """Union live PIDs and active task ids across every supervisor for an episode."""
    result: dict[str, dict[str, list]] = {}
    for raw in ps_output.splitlines():
        match = re.match(r"\s*(\d+)\s+(.+)$", raw)
        if not match or "episode_parallel_batch_supervisor.py" not in match.group(2):
            continue
        pid = int(match.group(1))
        command = match.group(2)
        receipt_match = re.search(r"--receipt\s+(\S+)", command)
        if not receipt_match:
            continue
        receipt_path = Path(receipt_match.group(1))
        if not receipt_path.is_absolute():
            receipt_path = ROOT / receipt_path
        try:
            receipt = read_json(receipt_path)
        except (OSError, json.JSONDecodeError):
            continue
        episode = str(receipt.get("episode") or "").upper()
        if not episode:
            continue
        row = result.setdefault(episode, {"pids": [], "task_ids": [], "receipts": []})
        row["pids"].append(pid)
        row["receipts"].append(str(receipt_path.relative_to(ROOT)))
        for task_id in receipt.get("active_task_ids") or []:
            if task_id not in row["task_ids"]:
                row["task_ids"].append(task_id)
    return result


def build_projection() -> dict:
    snapshot = read_json(SNAPSHOT) if SNAPSHOT.is_file() else {}
    concurrency = read_json(CONCURRENCY_POLICY) if CONCURRENCY_POLICY.is_file() else {}
    override = (
        concurrency.get("runtime_override")
        or concurrency.get("temporary_override")
        or concurrency.get("active_override")
        or {}
    )
    single_episode_mode = (
        snapshot.get("mode") == "SINGLE_EPISODE_WORKFLOW_DEBUG"
        or override.get("mode") == "SINGLE_EPISODE_WORKFLOW_DEBUG"
    )
    target_slots = 1 if single_episode_mode else 3
    lines: list[dict] = []
    released_evidence: dict[str, list[str]] = {}
    seen: set[str] = set()
    ps_output = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)
    local_processes = episode_process_map(ps_output)
    runtime_evidence = active_runtime_evidence(ps_output)
    command_by_pid = {}
    for raw in ps_output.splitlines():
        match = re.match(r"\s*(\d+)\s+(.+)$", raw)
        if match:
            command_by_pid[int(match.group(1))] = match.group(2).lower()

    release_root = ROOT / "workflow/release"
    for release_dir in release_root.iterdir() if release_root.is_dir() else ():
        if not release_dir.is_dir():
            continue
        episode = release_dir.name.upper()
        is_released, evidence = released(episode)
        if is_released:
            released_evidence[episode] = evidence

    for source in snapshot.get("parallel_lines", []):
        episode = str(source.get("episode") or "").upper()
        if not episode or episode in seen:
            continue
        is_released, evidence = released(episode)
        if is_released:
            released_evidence[episode] = evidence
            continue
        task_states = source.get("task_states") or {}
        active_states = {"pending", "retry_pending", "remote_running", "submitted", "queued", "processing"}
        task_ids = [
            task_id for task_id in (source.get("task_ids") or [])
            if not task_states or any(
                str(key) and state in active_states
                for key, state in task_states.items()
            )
        ]
        runtime = runtime_evidence.get(episode) or {}
        task_ids = list(dict.fromkeys([*task_ids, *(runtime.get("task_ids") or [])]))
        release_activity = active_release_evidence(episode)
        release_payload = read_json(ROOT / release_activity) if release_activity else {}
        local_pids = runtime.get("pids") or local_processes.get(episode, [])
        ai_review_active = any(
            "qingshan-review review-many" in command_by_pid.get(pid, "")
            for pid in local_pids
        )
        local_stage = "LOCAL_AI_REVIEW" if ai_review_active else "LOCAL_AGENTCUT_OR_BATCH_SUPERVISOR"
        local_next_action = (
            "harvest the active AI-review batches, preserve raw failures, and advance admitted outputs"
            if ai_review_active
            else "poll all remote tasks concurrently; download and QA each completed item"
        )
        lines.append({
            "episode": episode,
            "stage": "ORDERED_PLATFORM_RELEASE" if release_activity else (local_stage if local_pids else (source.get("active_work") or source.get("state") or "UNKNOWN")),
            "status": release_payload.get("status") if release_activity else ("ACTIVE_LOCAL_PROCESS" if local_pids else (source.get("state") or "UNKNOWN")),
            "active_evidence": (
                ",".join(runtime.get("receipts") or [])
                if runtime.get("receipts") else
                release_activity or (f"local_process:{local_pids[0]}" if local_pids else source.get("evidence"))
            ),
            "local_pid": local_pids[0] if local_pids else None,
            "local_pids": local_pids,
            "remote_task_ids": task_ids,
            "real_activity": bool(local_pids or task_ids),
            "next_action": release_payload.get("next_trigger") if release_activity else local_next_action,
        })
        seen.add(episode)

    for episode, path in latest_release_preflights().items():
        if episode in seen:
            continue
        is_released, evidence = released(episode)
        if is_released:
            released_evidence[episode] = evidence
            continue
        data = read_json(path)
        lines.append({
            "episode": episode,
            "stage": "ORDERED_PLATFORM_RELEASE",
            "status": data.get("status") or "UNKNOWN",
            "active_evidence": str(path.relative_to(ROOT)),
            "local_pid": None,
            "remote_task_ids": [],
            "real_activity": False,
            "completed_delivery": data.get("final_package"),
            "completed_delivery_sha256": data.get("final_package_sha256"),
            "next_action": (data.get("order_gate") or {}).get("next_trigger"),
            "wait_reason": (data.get("order_gate") or {}).get("reason"),
        })
        seen.add(episode)

    lines.sort(key=lambda row: episode_number(row["episode"]))
    if single_episode_mode:
        active_lines = [row for row in lines if row["real_activity"]]
        lines = active_lines[-1:] if active_lines else lines[-1:]
    else:
        lines = lines[:target_slots]
    payload = {
        "schema": "qingshan.producer.work_queue.v2",
        "authorization_ref": "ROGER-20260720-SINGLE-EPISODE-WORKFLOW-DEBUG" if single_episode_mode else "ROGER-20260718-NO-IDLE-LINE",
        "updated_at": now(),
        "source": "ACTIVE_EPISODE_LINES_LATEST + latest ordered-release preflight + release records",
        "rules": {
            "episode_isolation": True,
            "internal_parallel_tools": ["image_generation", "video_generation", "agentcut", "ai_review"],
            "replacement_only_after_release": True,
            "released_episode_auto_dequeue": True,
            "text_active_is_not_evidence": True
        },
        "mode": "SINGLE_EPISODE_WORKFLOW_DEBUG" if single_episode_mode else "THREE_EPISODE_CONCURRENCY",
        "target_slots": target_slots,
        "occupied_slot_count": len(lines),
        "real_active_handle_count": sum(1 for row in lines if row["real_activity"]),
        "lines": {f"SLOT_{index + 1}_{row['episode']}": row for index, row in enumerate(lines)},
        "released_auto_dequeue_assertion": {
            "passed": all(episode not in {row["episode"] for row in lines} for episode in released_evidence),
            "excluded_episodes": sorted(released_evidence, key=episode_number),
            "evidence": released_evidence,
        },
        "replacement_backlog": [],
        "replacement_backlog_reason": "Do not activate a later episode until an occupied episode has a completed platform release record."
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.expected_current_sha256 and not args.write:
        raise RuntimeError("--expected-current-sha256 is valid only with --write")
    if args.write and not args.expected_current_sha256:
        raise RuntimeError("--write requires --expected-current-sha256")

    projection = build_projection()
    report = {
        "status": "DRY_RUN",
        "out": str(OUT),
        "episodes": sorted(projection_episodes(projection), key=episode_number),
        "real_active_handle_count": projection["real_active_handle_count"],
        "released_excluded": projection["released_auto_dequeue_assertion"]["excluded_episodes"],
        "written": False,
    }
    if args.write:
        new_sha, backup = _atomic_cas_write(projection, args.expected_current_sha256)
        report.update(
            status="PASS_WRITTEN_ATOMIC_CAS",
            written=True,
            new_sha256=new_sha,
            backup=backup,
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(json.dumps({"status": "REFUSED_NO_WRITE", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
