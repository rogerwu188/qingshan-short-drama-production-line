#!/usr/bin/env python3
"""Build a recovery batch only for image submissions with no durable task ID."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--recovery-report", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    manifest = json.loads(resolve(args.manifest).read_text(encoding="utf-8"))
    recovery = json.loads(resolve(args.recovery_report).read_text(encoding="utf-8"))
    unknown = {row["task_key"] for row in recovery.get("unknown") or []}
    if not unknown:
        raise ValueError("recovery report has no unknown task keys")
    tasks = []
    for source in manifest.get("tasks") or []:
        if source["task_key"] not in unknown:
            continue
        task = copy.deepcopy(source)
        task["original_task_key"] = task["task_key"]
        task["task_key"] = f"{task['task_key']}-UNRECEIPTED-RECOVERY-R1"
        task["recovery_reason"] = "NO_TASK_ID_OR_RECEIPT_AFTER_NETWORK_WRITE_TIMEOUT_AND_15_MINUTE_WINDOW"
        task["prior_credit_status"] = "UNKNOWN"
        task["status"] = "READY_FOR_PARALLEL_SUBMIT"
        tasks.append(task)
    if len(tasks) != len(unknown):
        found = {task["original_task_key"] for task in tasks}
        raise ValueError(f"unknown task keys missing from manifest: {sorted(unknown - found)}")
    output = {
        **{key: value for key, value in manifest.items() if key != "tasks"},
        "schema": "qingshan.unreceipted_image_recovery_batch.v1",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "recorded_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "recovery_source": args.recovery_report,
        "recovery_task_count": len(tasks),
        "prior_unknown_requests_preserved": True,
        "machine_adjudication": (
            "No task ID, no receipt and no local result after the 15-minute window; "
            "submit one recovery request per missing planned state."
        ),
        "tasks": tasks,
    }
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
