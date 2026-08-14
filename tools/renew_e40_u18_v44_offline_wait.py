#!/usr/bin/env python3
"""Renew the isolated offline U18 V44 wait without changing its blocker or scope."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHED = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
LOCK = ROOT / "workflow/work_queue.json.lock"
TASK = "E40-U18-V44-NEW-VERSION-AND-PER-BUNDLE-AUTHORITY-TASK-LOCAL-REMOTE-WAIT"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> None:
    now = datetime.now(timezone.utc)
    wake = now + timedelta(hours=6)
    with LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        scheduler = json.loads(SCHED.read_text(encoding="utf-8"))
        task = next((row for row in scheduler["tasks"] if row.get("task_id") == TASK), None)
        if task is None or task.get("state") != "REMOTE_WAIT" or task.get("wait_scope") != "TASK_LOCAL":
            raise SystemExit("FAIL_CLOSED_U18_V44_WAIT_NOT_FOUND")
        if task.get("provider_query_allowed") or task.get("provider_post_allowed") or task.get("download_allowed"):
            raise SystemExit("FAIL_CLOSED_U18_V44_SCOPE_CHANGED")
        task.update({
            "executor_acknowledged_at": iso(now),
            "next_due_at": iso(wake),
            "executor_next_wakeup_at": iso(wake),
        })
        scheduler["updated_at"] = iso(now)
        scheduler["recorded_at"] = iso(now)
        atomic_json(SCHED, scheduler)
        queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        queue["task_lane_scheduler"]["sha256"] = sha256(SCHED)
        atomic_json(QUEUE, queue)
    print(json.dumps({"status": "PASS_U18_V44_ISOLATED_OFFLINE_WAIT_RENEWED", "next_due_at": iso(wake), "scheduler_sha256": sha256(SCHED), "work_queue_sha256": sha256(QUEUE)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
