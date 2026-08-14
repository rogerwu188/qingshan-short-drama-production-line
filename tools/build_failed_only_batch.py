#!/usr/bin/env python3
"""Build a retry batch containing only terminally failed tasks from a receipt."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


FAILED_STATES = {
    "qa_failed_terminal",
    "remote_failed_terminal",
    "tool_failed_terminal",
    "submit_failed_terminal",
}

RUNTIME_FIELDS = {
    "downloaded_at",
    "failure_evidence",
    "last_polled_at",
    "output_path",
    "qa",
    "remote_status",
    "retry_count",
    "sha256",
    "state",
    "submit_response",
    "submitted_at",
    "task_id",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-config", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--status", default="READY_FOR_PARALLEL_SUBMIT")
    parser.add_argument(
        "--states",
        default=",".join(sorted(FAILED_STATES)),
        help="Comma-separated terminal states to include.",
    )
    args = parser.parse_args()

    selected_states = {value.strip() for value in args.states.split(",") if value.strip()}
    invalid_states = selected_states - FAILED_STATES
    if invalid_states:
        raise SystemExit(f"Unsupported failed states: {sorted(invalid_states)}")

    config = read_json(args.base_config)
    receipt = read_json(args.receipt)
    failed_keys = {
        task.get("task_key")
        for task in receipt.get("tasks", [])
        if task.get("state") in selected_states
    }

    retry_tasks = []
    for source in config.get("tasks", []):
        if source.get("task_key") not in failed_keys:
            continue
        task = copy.deepcopy(source)
        for field in RUNTIME_FIELDS:
            task.pop(field, None)
        task["status"] = args.status
        retry_tasks.append(task)

    if not retry_tasks:
        raise SystemExit("No terminally failed tasks found")

    output = copy.deepcopy(config)
    output["status"] = args.status
    output["tasks"] = retry_tasks
    output["retry_of"] = str(args.receipt)
    output["retry_states"] = sorted(selected_states)
    current_passes = [
        task.get("task_key")
        for task in receipt.get("tasks", [])
        if task.get("state") == "qa_pass"
    ]
    output["retained_pass_task_keys"] = list(dict.fromkeys([
        *config.get("retained_pass_task_keys", []),
        *current_passes,
    ]))
    output["base_batch_note"] = (
        f"Failed-only retry for {len(retry_tasks)} tasks; retain all previously passed tasks."
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "failed_task_count": len(retry_tasks),
        "retained_pass_task_count": len(output["retained_pass_task_keys"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
