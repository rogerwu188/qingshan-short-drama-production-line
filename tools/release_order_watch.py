#!/usr/bin/env python3
"""Monitor an episode's immutable final package and ordered-release prerequisites."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_LINES_PATH = ROOT / "workflow/production_line/ACTIVE_EPISODE_LINES_LATEST.json"
WORK_QUEUE_PATH = ROOT / "workflow/work_queue.json"

COMPLETE_PLATFORM_STATES = {
    "COMPLETE",
    "PUBLISHED",
    "PUBLISHED_PUBLIC",
    "REPLACEMENT_COMPLETE",
    "RELEASE_COMPLETE",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def iter_values(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from iter_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_values(child)
    else:
        yield value


def release_complete(directory: Path) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    youtube = False
    douyin = False
    if not directory.exists():
        return False, evidence
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        values = {str(value).upper() for value in iter_values(payload)}
        explicit_complete = payload.get("release_complete") is True or "BOTH_PLATFORMS_RELEASE_COMPLETE" in values
        text = json.dumps(payload, ensure_ascii=False).upper()
        has_complete_state = bool(values & COMPLETE_PLATFORM_STATES)
        if explicit_complete:
            youtube = douyin = True
            evidence.append(str(path))
            continue
        if "YOUTUBE" in text and has_complete_state:
            youtube = True
            evidence.append(str(path))
        if "DOUYIN" in text and has_complete_state:
            douyin = True
            evidence.append(str(path))
    return youtube and douyin, sorted(set(evidence))


def release_schedule_hold(episode: str, path: Path = WORK_QUEUE_PATH) -> tuple[bool, Optional[str]]:
    """Honor producer HARD_GATE holds even if an old watcher is relaunched."""
    try:
        queue = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, None
    gate = queue.get("schedule_gate") or {}
    blocked = {str(item).upper() for item in gate.get("release_blocked_episodes", [])}
    episode_upper = episode.upper()
    if episode_upper in blocked or any(item.startswith(f"{episode_upper}_") for item in blocked):
        return True, str(gate.get("directive") or "workflow/work_queue.json")
    for line in (queue.get("lines") or {}).values():
        if str(line.get("episode") or "").upper() != episode_upper:
            continue
        status = str(line.get("status") or "").upper()
        if status.startswith("HOLD_"):
            return True, str(gate.get("directive") or status)
    return False, None


def build_receipt(args) -> dict:
    final_path = Path(args.final_video).expanduser().resolve()
    final_exists = final_path.is_file()
    actual_sha = sha256(final_path) if final_exists else None
    integrity = final_exists and actual_sha == args.expected_sha256
    prerequisites = []
    all_complete = True
    for item in args.prerequisite:
        episode, raw_directory = item.split("=", 1)
        directory = Path(raw_directory).expanduser().resolve()
        complete, evidence = release_complete(directory)
        prerequisites.append(
            {
                "episode": episode,
                "release_directory": str(directory),
                "both_platforms_complete": complete,
                "evidence": evidence,
            }
        )
        all_complete = all_complete and complete
    held, hold_ref = release_schedule_hold(args.episode)
    if held:
        status = "STOPPED_SCHEDULE_HOLD"
    elif not integrity:
        status = "BLOCKED_FINAL_PACKAGE_INTEGRITY"
    elif all_complete:
        status = "READY_FOR_ORDERED_PLATFORM_UPLOAD"
    else:
        status = "ACTIVE_ORDERED_RELEASE_WATCH"
    return {
        "schema": "qingshan.release_order_watch.v1",
        "episode": args.episode,
        "status": status,
        "local_pid": None if held else os.getpid(),
        "schedule_hold": held,
        "schedule_hold_ref": hold_ref,
        "final_video": str(final_path),
        "expected_sha256": args.expected_sha256,
        "actual_sha256": actual_sha,
        "final_package_integrity": "PASS" if integrity else "FAIL",
        "prerequisites": prerequisites,
        "platform_mutation_performed": False,
        "next_action": (
            "Do not publish or replace this package; follow the producer schedule gate."
            if held
            else "Begin ordered platform upload in the built-in browser."
            if status == "READY_FOR_ORDERED_PLATFORM_UPLOAD"
            else "Continue monitoring predecessor release receipts without blocking local or S3 work."
        ),
        "rollback": "Stop this read-only watcher; it never uploads, deletes or modifies platform state.",
        "updated_at": now_iso(),
    }


def update_activity_snapshot(payload: dict, path: Path = ACTIVE_LINES_PATH) -> None:
    """Expose the read-only watcher as a real local activity line."""
    if not path.is_file():
        return
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for line in snapshot.get("parallel_lines", []):
        if line.get("episode") != payload.get("episode"):
            continue
        line.update(
            {
                "active_work": payload.get("status"),
                "local_pid": payload.get("local_pid"),
                "task_ids": [],
                "task_count": 0,
                "task_states": {},
                "task_id": None,
                "evidence": str(Path(payload["receipt_path"]).relative_to(ROOT))
                if payload.get("receipt_path") and Path(payload["receipt_path"]).is_relative_to(ROOT)
                else payload.get("receipt_path"),
                "state": payload.get("status"),
                "note": "Read-only ordered-release watcher is a real local process; it performs no platform mutation.",
            }
        )
        break
    snapshot["observed_at"] = now_iso()
    snapshot["active_count"] = sum(
        1
        for line in snapshot.get("parallel_lines", [])
        if line.get("task_count", 0) or line.get("local_pid")
    )
    snapshot["state"] = "ACTIVE" if snapshot["active_count"] >= snapshot.get("target", 3) else "UNDER_TARGET"
    atomic_write_json(path, snapshot)


def main() -> int:
    # This read-only watcher does not need production service credentials.
    os.environ.pop("GIGGLE_API_KEY", None)
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--final-video", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--prerequisite", action="append", default=[])
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    receipt = Path(args.receipt).expanduser().resolve()
    while True:
        payload = build_receipt(args)
        payload["receipt_path"] = str(receipt)
        atomic_write_json(receipt, payload)
        update_activity_snapshot(payload)
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        if args.once or payload["status"] != "ACTIVE_ORDERED_RELEASE_WATCH":
            return 0 if payload["status"] != "BLOCKED_FINAL_PACKAGE_INTEGRITY" else 1
        time.sleep(max(5.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
