#!/usr/bin/env python3
"""Poll tasks from a Giggle submit report and optionally download results."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import re
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from giggle_api_client import query_task
from submit_giggle_task_manifest import ensure_giggle_api_key
from line_heartbeat import record_line_heartbeat


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return stem or "task"


def result_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("results") or payload.get("tasks") or []
    if not isinstance(rows, list):
        raise ValueError("submit report results/tasks must be a list")
    return rows


def download_atomic(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "qingshan-giggle-submit-report-poller/1.0"},
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        temporary.write_bytes(response.read())
    temporary.replace(destination)


def output_path(out_dir: Path, label: str, index: int, total: int) -> Path:
    suffix = "" if total == 1 else f"_{index:02d}"
    return out_dir / f"{safe_stem(label)}{suffix}.mp4"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def close_remote_generation_line(
    time_ledger: Path,
    line_id: str,
    status_report: Path,
    now: str | None = None,
) -> dict[str, Any]:
    ledger = read_json(time_ledger)
    lines = ledger.get("parallel_lines") or []
    line = next((row for row in lines if row.get("line_id") == line_id), None)
    if line is None:
        raise ValueError(f"line_id not found in time ledger: {line_id}")
    if line.get("blocked_by") != "REMOTE_GENERATION":
        raise ValueError(
            f"line {line_id} is not blocked by REMOTE_GENERATION: {line.get('blocked_by')}"
        )
    timestamp = now or datetime.now().astimezone().isoformat(timespec="seconds")
    line = record_line_heartbeat(
        time_ledger,
        line_id,
        active_work="REMOTE_HARVEST_DOWNLOADED_LOCAL_QA_ACTIVE",
        evidence_ref=str(status_report),
        next_work="RUN_DOWNLOAD_IMMEDIATE_MACHINE_AND_VISUAL_QA",
        state="ACTIVE_LOCAL_POST_HARVEST_QA",
        now=timestamp,
    )
    ledger = read_json(time_ledger)
    ledger.setdefault("events", []).append(
        {
            "at": timestamp,
            "event": f"{line_id}_REMOTE_GENERATION_HARVEST_DOWNLOADED_AUTO_CLOSE_TO_NONE",
            "timestamp_precision": "SECOND",
            "source_ref": str(status_report),
        }
    )
    write_json_atomic(time_ledger, ledger)
    return line


def poll(
    submit_report: Path,
    out_dir: Path,
    status_report: Path,
    download: bool,
    time_ledger: Path | None = None,
    line_id: str | None = None,
) -> dict[str, Any]:
    giggle_key_environment = ensure_giggle_api_key()
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("GIGGLE_API_KEY is not set")

    source = read_json(submit_report)
    statuses: list[dict[str, Any]] = []
    for index, row in enumerate(result_rows(source), 1):
        task_id = row.get("task_id")
        label = str(
            row.get("task_key")
            or row.get("dialogue_id")
            or row.get("shot_id")
            or f"task-{index:03d}"
        )
        if not task_id:
            statuses.append({**row, "remote_status": "NO_TASK_ID", "downloaded_files": []})
            continue

        response = query_task(SimpleNamespace(task_id=task_id))
        data = response.get("data") or {}
        remote_status = str(data.get("status") or "UNKNOWN")
        urls = data.get("urls") or []
        files: list[str] = []
        if download and remote_status == "completed":
            for url_index, url in enumerate(urls, 1):
                destination = output_path(out_dir, label, url_index, len(urls))
                if not destination.exists():
                    download_atomic(str(url), destination)
                files.append(str(destination))
        elif remote_status == "completed":
            files = [
                str(path)
                for path in sorted(out_dir.glob(f"{safe_stem(label)}*.mp4"))
            ]

        statuses.append(
            {
                **row,
                "remote_status": remote_status,
                "result_url_count": len(urls),
                "downloaded_files": files,
            }
        )

    counts: dict[str, int] = {}
    for row in statuses:
        status = row["remote_status"]
        counts[status] = counts.get(status, 0) + 1
    payload = {
        "schema": "qingshan.giggle_submit_report_remote_status.v1",
        "giggle_key_environment": giggle_key_environment,
        "submit_report": str(submit_report),
        "out_dir": str(out_dir),
        "status_counts": counts,
        "all_completed": bool(statuses) and counts.get("completed", 0) == len(statuses),
        "results": statuses,
    }
    write_json_atomic(status_report, payload)
    downloaded_all = bool(statuses) and all(row.get("downloaded_files") for row in statuses)
    if bool(time_ledger) != bool(line_id):
        raise ValueError("--time-ledger and --line-id must be provided together")
    if payload["all_completed"] and download and downloaded_all and time_ledger and line_id:
        closed = close_remote_generation_line(time_ledger, line_id, status_report)
        payload["line_closeout"] = {
            "status": "AUTO_CLOSED_REMOTE_GENERATION_TO_NONE",
            "line_id": line_id,
            "last_heartbeat_at": closed["last_heartbeat_at"],
        }
        write_json_atomic(status_report, payload)
    elif time_ledger and line_id:
        payload["line_closeout"] = {
            "status": "NOT_CLOSED_REQUIRES_ALL_COMPLETED_AND_DOWNLOADED",
            "line_id": line_id,
        }
        write_json_atomic(status_report, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit-report", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--status-report", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--time-ledger", type=Path)
    parser.add_argument("--line-id")
    args = parser.parse_args()
    payload = poll(
        args.submit_report,
        args.out_dir,
        args.status_report,
        args.download,
        args.time_ledger,
        args.line_id,
    )
    print(
        json.dumps(
            {
                "status_counts": payload["status_counts"],
                "all_completed": payload["all_completed"],
                "status_report": str(args.status_report),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
