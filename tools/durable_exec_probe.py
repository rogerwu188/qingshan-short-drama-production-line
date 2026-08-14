#!/usr/bin/env python3
"""Write a durable exec-health receipt before emitting best-effort stdout."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def nested_value(data: Any, names: set[str]) -> str | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in names and isinstance(value, str) and value.strip():
                return value.strip()
        for value in data.values():
            found = nested_value(value, names)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = nested_value(value, names)
            if found:
                return found
    return None


def load_job(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("job must be a JSON object")
    return data


def resolve_shared_root(value: str | None) -> Path:
    selected = (
        value
        or os.environ.get("QINGSHAN_FACTORY_SHARED_ROOT")
        or str(Path.home() / ".openclaw/shared/ai-drama-factory")
    )
    return Path(selected).expanduser().resolve()


def resolve_project_root(
    explicit: str | None,
    project_id: str | None,
    shared_root: Path,
    job: dict[str, Any],
) -> Path:
    selected = (
        explicit
        or os.environ.get("QINGSHAN_PROJECT_ROOT")
        or nested_value(job, {"project_root", "PROJECT_ROOT"})
    )
    if selected:
        return Path(selected).expanduser().resolve()
    selected_id = (
        project_id
        or os.environ.get("QINGSHAN_PROJECT_ID")
        or nested_value(job, {"project_id", "PROJECT_ID"})
    )
    if not selected_id:
        raise ValueError("project root is unresolved")
    return (shared_root / "factory/projects" / selected_id).resolve()


def resolve_facts_path(
    explicit: str | None,
    project_root: Path,
    job: dict[str, Any],
) -> Path:
    selected = (
        explicit
        or os.environ.get("QINGSHAN_PROJECT_FACTS_ABS")
        or nested_value(job, {"project_facts_abs", "PROJECT_FACTS_ABS"})
    )
    if selected:
        return Path(selected).expanduser().resolve()
    return (project_root / "source/facts/chapter_facts.jsonl").resolve()


def read_facts(path: Path) -> tuple[int, int | None]:
    if not path.is_file():
        raise FileNotFoundError(path)
    count = 0
    last_n: int | None = None
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            count += 1
            record = json.loads(line)
            if not isinstance(record, dict) or not isinstance(record.get("n"), int):
                raise ValueError(f"invalid facts record at line {count}")
            last_n = int(record["n"])
    return count, last_n


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shared-root")
    parser.add_argument("--project-root")
    parser.add_argument("--project-id")
    parser.add_argument("--facts-path")
    parser.add_argument("--job", type=Path)
    parser.add_argument("--nonce")
    parser.add_argument("--receipt-dir", type=Path)
    parser.add_argument("--quiet-stdout", action="store_true")
    args = parser.parse_args()

    job = load_job(args.job)
    shared_root = resolve_shared_root(args.shared_root)
    project_root = resolve_project_root(
        args.project_root,
        args.project_id,
        shared_root,
        job,
    )
    facts_path = resolve_facts_path(args.facts_path, project_root, job)
    facts, last_n = read_facts(facts_path)
    nonce = args.nonce or uuid.uuid4().hex
    receipt_dir = (
        args.receipt_dir.expanduser().resolve()
        if args.receipt_dir
        else project_root / "runtime/exec_probe_receipts"
    )
    receipt_path = receipt_dir / f"{nonce}.json"
    receipt = {
        "schema": "qingshan.factory.exec_probe_receipt.v1",
        "status": "HEALTHY",
        "nonce": nonce,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "project_root": str(project_root),
        "project_facts_abs": str(facts_path),
        "facts": facts,
        "last_n": last_n,
    }
    atomic_write_json(receipt_path, receipt)
    if not args.quiet_stdout:
        print(
            "EXEC_PROBE_HEALTHY"
            f"|nonce={nonce}|facts={facts}|last_n={last_n}"
            f"|receipt={receipt_path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
