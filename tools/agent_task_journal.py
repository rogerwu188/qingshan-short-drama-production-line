#!/usr/bin/env python3
"""Durable per-Agent task journal for StoryClaw factory recovery."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ACTIVE_STATUSES = {"DISPATCHED", "CLAIMED", "RUNNING", "RETRYING"}
TERMINAL_STATUSES = {"PASS", "FAIL", "BLOCKED", "CANCELLED", "SUPERSEDED"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_record_sha(record: dict) -> str:
    canonical = json.dumps(
        {key: value for key, value in record.items() if key != "record_sha"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(canonical)


def atomic_json(path: Path, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    path.with_suffix(path.suffix + ".sha256").write_text(
        sha256_bytes(data) + "\n", encoding="ascii"
    )


def agent_dir(shared_root: Path, agent_id: str) -> Path:
    if not agent_id or "/" in agent_id or agent_id in {".", ".."}:
        raise ValueError("invalid agent_id")
    return shared_root.resolve() / "factory/agents" / agent_id


def read_and_verify_journal(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records: list[dict] = []
    previous = "GENESIS"
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid journal JSON at line {line_number}") from exc
        if record.get("sequence") != len(records) + 1:
            raise ValueError(f"journal sequence mismatch at line {line_number}")
        if record.get("previous_sha") != previous:
            raise ValueError(f"journal previous_sha mismatch at line {line_number}")
        observed = str(record.get("record_sha", ""))
        expected = canonical_record_sha(record)
        if observed != expected:
            raise ValueError(f"journal record_sha mismatch at line {line_number}")
        previous = observed
        records.append(record)
    return records


def append_task_record(
    shared_root: Path,
    agent_id: str,
    *,
    job_id: str,
    status: str,
    event: str,
    details: dict | None = None,
) -> dict:
    if status not in ACTIVE_STATUSES | TERMINAL_STATUSES:
        raise ValueError(f"invalid task status: {status}")
    root = agent_dir(shared_root, agent_id)
    root.mkdir(parents=True, exist_ok=True)
    journal = root / "task_journal.jsonl"
    lock_path = root / ".task_journal.lock"
    with lock_path.open("a+", encoding="ascii") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        records = read_and_verify_journal(journal)
        previous = records[-1]["record_sha"] if records else "GENESIS"
        record = {
            "schema": "qingshan.factory.agent_task_record.v1",
            "sequence": len(records) + 1,
            "previous_sha": previous,
            "agent_id": agent_id,
            "job_id": job_id,
            "status": status,
            "event": event,
            "details": details or {},
            "recorded_at": now(),
        }
        record["record_sha"] = canonical_record_sha(record)
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        head = {
            "schema": "qingshan.factory.agent_task_journal_head.v1",
            "agent_id": agent_id,
            "record_count": record["sequence"],
            "head_sha": record["record_sha"],
            "last_job_id": job_id,
            "last_status": status,
            "updated_at": record["recorded_at"],
        }
        atomic_json(root / "task_journal.head.json", head)
        return {
            "journal_path": str(journal.resolve()),
            "head_path": str((root / "task_journal.head.json").resolve()),
            "record": record,
        }


def verify_sha_sidecar(path: Path) -> bool:
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not path.is_file() or not sidecar.is_file():
        return False
    expected = sidecar.read_text(encoding="ascii").strip()
    return expected == sha256_bytes(path.read_bytes())


def recover_task_state(shared_root: Path, agent_id: str) -> dict:
    root = agent_dir(shared_root, agent_id)
    journal = root / "task_journal.jsonl"
    records = read_and_verify_journal(journal)
    active_path = root / "active_job.json"
    active = None
    active_valid = False
    if active_path.is_file():
        active_valid = verify_sha_sidecar(active_path)
        if active_valid:
            active = json.loads(active_path.read_text(encoding="utf-8"))
    resume_required = bool(
        active_valid
        and isinstance(active, dict)
        and active.get("status") in ACTIVE_STATUSES
    )
    return {
        "schema": "qingshan.factory.agent_task_recovery.v1",
        "status": "PASS",
        "agent_id": agent_id,
        "journal_path": str(journal.resolve()),
        "journal_records": len(records),
        "journal_head_sha": records[-1]["record_sha"] if records else "GENESIS",
        "active_job_path": str(active_path.resolve()),
        "active_job_valid": active_valid,
        "active_job": active,
        "resume_required": resume_required,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shared-root", type=Path, required=True)
    parser.add_argument("--agent-id", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--job-id", required=True)
    append_parser.add_argument("--status", required=True)
    append_parser.add_argument("--event", required=True)
    append_parser.add_argument("--details-json", default="{}")
    subparsers.add_parser("recover")
    args = parser.parse_args()
    if args.command == "append":
        result = append_task_record(
            args.shared_root,
            args.agent_id,
            job_id=args.job_id,
            status=args.status,
            event=args.event,
            details=json.loads(args.details_json),
        )
    else:
        result = recover_task_state(args.shared_root, args.agent_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
