#!/usr/bin/env python3
"""Build a failed-only retry config from an episode supervisor receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FAILED_STATES = {
    "submit_failed_terminal",
    "remote_failed_terminal",
    "qa_failed_terminal",
    "download_failed_terminal",
}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--suffix", default="R1-FAILED-ONLY")
    parser.add_argument("--exclude-receipt", action="append", type=Path, default=[])
    args = parser.parse_args()
    config = read(args.config)
    receipt = read(args.receipt)
    failed_keys = {
        str(task.get("task_key"))
        for task in receipt.get("tasks") or []
        if str(task.get("status") or task.get("state") or "").lower() in FAILED_STATES
    }
    excluded_source_keys: set[str] = set()
    for excluded_path in args.exclude_receipt:
        for task in read(excluded_path).get("tasks") or []:
            metadata = task.get("metadata") or {}
            source_key = metadata.get("retry_of_task_key")
            if source_key:
                excluded_source_keys.add(str(source_key))
    failed_keys -= excluded_source_keys
    tasks = []
    for source in config.get("tasks") or []:
        if str(source.get("task_key")) not in failed_keys:
            continue
        task = json.loads(json.dumps(source, ensure_ascii=False))
        task["task_key"] = f"{task['task_key']}-{args.suffix}"
        task["status"] = "READY_FOR_PARALLEL_SUBMIT"
        metadata = dict(task.get("metadata") or {})
        metadata.update({
            "retry_of_task_key": source.get("task_key"),
            "retry_reason": "ISOLATED_TERMINAL_FAILURE",
        })
        task["metadata"] = metadata
        tasks.append(task)
    if not tasks or len(tasks) != len(failed_keys):
        raise SystemExit(f"failed-only extraction mismatch: keys={len(failed_keys)} tasks={len(tasks)}")
    retry = {
        **{key: value for key, value in config.items() if key != "tasks"},
        "status": "READY_TO_SUBMIT_FAILED_ONLY",
        "parallel_submission": True,
        "concurrency": len(tasks),
        "max_retries": 1,
        "retry_of": str(args.receipt),
        "excluded_active_retry_receipts": [str(path) for path in args.exclude_receipt],
        "base_batch_note": "Preserve all passed and running siblings; concurrently retry only isolated terminal failures.",
        "tasks": tasks,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(retry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "episode": config.get("episode"), "retry_task_count": len(tasks), "output": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
