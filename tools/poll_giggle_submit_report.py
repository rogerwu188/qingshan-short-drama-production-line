#!/usr/bin/env python3
"""Poll tasks from a Giggle submit report and optionally download results."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
import hopsapi_video_client as hopsapi

ENGINE_ROOT = Path(__file__).resolve().parents[1]


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


def adopted_failure_rows(payload: dict[str, Any], known_task_ids: set[str]) -> list[dict[str, Any]]:
    """Failure rows whose durable transaction was bound AFTER the report was written -- a lost HopsAPI
    response whose task id the billing usage reconciliation adopted (tools/hopsapi_usage.py).  They
    are polled and harvested under that id like any bound task (never re-POSTed); a poll-only
    re-entry reads this same report, so without this the adopted clip would never be downloaded."""
    rows = []
    for failure in payload.get("failures") or []:
        if not isinstance(failure, dict) or failure.get("task_id"):
            continue
        path = _transaction_file(failure)
        if path is None:
            continue
        try:
            transaction = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        task_id = str(transaction.get("task_id") or "")
        if transaction.get("state") != "SUBMITTED_TASK_ID_BOUND" or not task_id or task_id in known_task_ids \
                or not str(transaction.get("task_id_source") or "").startswith("HOPSAPI_USAGE_"):
            continue
        known_task_ids.add(task_id)
        rows.append({"task_key": failure.get("task_key") or transaction.get("task_key"), "task_id": task_id,
                     "transaction": failure.get("transaction"), "provider": transaction.get("provider"),
                     "recovered_via": str(transaction["task_id_source"])})
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


def poll_workers(default: int = 6) -> int:
    """How many task queries/downloads run at once inside one poll tick.

    Each task's query is one HTTP GET and each download one GET; both release the
    GIL, so a tick that polls a six-unit wave serially pays six round trips.  The
    bound is per-tick (not remote generation capacity, which the provider holds)
    and can be overridden with NALU_POLL_WORKERS.
    """
    try:
        return max(1, int(os.environ.get("NALU_POLL_WORKERS") or default))
    except ValueError:
        return default


def _transaction_file(row: dict[str, Any]) -> Path | None:
    value = str(row.get("transaction") or "")
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = path if path.is_file() else ENGINE_ROOT / path
    return path if path.is_file() else None


def row_provider(row: dict[str, Any]) -> str:
    """Which provider owns this task id: the row, then its durable transaction, then the id shape
    (HopsAPI ids are ``tsk_…``; Giggle ids are UUIDs)."""
    if row.get("provider") in hopsapi.PROVIDERS:
        return str(row["provider"])
    path = _transaction_file(row)
    if path is not None:
        try:
            recorded = json.loads(path.read_text(encoding="utf-8")).get("provider")
        except (OSError, ValueError):
            recorded = None
        if recorded in hopsapi.PROVIDERS:
            return str(recorded)
    return hopsapi.PROVIDER_HOPSAPI if hopsapi.is_hopsapi_task_id(row.get("task_id")) else hopsapi.PROVIDER_GIGGLE


def poll_one_hopsapi(row: dict[str, Any], label: str, named: str, out_dir: Path,
                     download: bool) -> dict[str, Any]:
    """GET the HopsAPI task, download + verify a completed clip to the exact path the Giggle harvest
    uses, and record the settled ``cost`` (or 0 for status 3/4) on the durable transaction."""
    status = hopsapi.query_task(str(row["task_id"]))
    remote_status = status["remote_status"]
    urls = status["urls"]
    files: list[str] = []
    downloads: list[dict[str, Any]] = []
    if download and remote_status == "completed":
        for url_index, url in enumerate(urls, 1):
            destination = (out_dir / named if named and len(urls) == 1
                           else output_path(out_dir, label, url_index, len(urls)))
            if not destination.exists():
                downloads.append(hopsapi.download_video(str(url), destination))
            files.append(str(destination))
    elif remote_status == "completed" and named:
        files = [str(out_dir / named)] if (out_dir / named).is_file() else []
    elif remote_status == "completed":
        files = [str(path) for path in sorted(out_dir.glob(f"{safe_stem(label)}*.mp4"))]
    settled = None
    path = _transaction_file(row)
    if path is not None and remote_status in {"completed", "failed", "cancelled"}:
        settled = hopsapi.record_settlement(path, str(row["task_id"]), status,
                                            now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return {
        **row,
        "provider": hopsapi.PROVIDER_HOPSAPI,
        "remote_status": remote_status,
        "provider_status_code": status.get("status_code"),
        "provider_cost_credits": status.get("cost"),
        "provider_cost_recorded_on_transaction": bool(settled and "provider_cost_credits" in settled),
        "provider_failure": status.get("error"),
        "result_url_count": len(urls),
        "downloaded_files": files,
        "download_verification": downloads,
    }


def poll_one(
    index: int,
    row: dict[str, Any],
    out_dir: Path,
    download: bool,
) -> dict[str, Any]:
    """Query (and optionally download) one submitted task.  Order-independent."""
    task_id = row.get("task_id")
    label = str(
        row.get("task_key")
        or row.get("dialogue_id")
        or row.get("shot_id")
        or f"task-{index:03d}"
    )
    # A row may name its own file under out_dir (an alternate take of a unit that is already
    # harvested to <task_key>.mp4 -- lab E05 2026-10-26); it must stay inside out_dir.
    named = str(row.get("output_name") or "")
    if named and (Path(named).is_absolute() or ".." in Path(named).parts or not named.endswith(".mp4")):
        raise ValueError(f"output_name must be a relative .mp4 path inside out_dir: {named}")
    if not task_id:
        return {**row, "remote_status": "NO_TASK_ID", "downloaded_files": []}
    if row_provider(row) == hopsapi.PROVIDER_HOPSAPI:
        return poll_one_hopsapi(row, label, named, out_dir, download)

    response = query_task(SimpleNamespace(task_id=task_id))
    data = response.get("data") or {}
    remote_status = str(data.get("status") or "UNKNOWN")
    urls = data.get("urls") or []
    files: list[str] = []
    if download and remote_status == "completed":
        for url_index, url in enumerate(urls, 1):
            destination = (out_dir / named if named and len(urls) == 1
                           else output_path(out_dir, label, url_index, len(urls)))
            if not destination.exists():
                download_atomic(str(url), destination)
            files.append(str(destination))
    elif remote_status == "completed" and named:
        files = [str(out_dir / named)] if (out_dir / named).is_file() else []
    elif remote_status == "completed":
        files = [
            str(path)
            for path in sorted(out_dir.glob(f"{safe_stem(label)}*.mp4"))
        ]

    return {
        **row,
        "remote_status": remote_status,
        "result_url_count": len(urls),
        "downloaded_files": files,
    }


def poll(
    submit_report: Path,
    out_dir: Path,
    status_report: Path,
    download: bool,
    time_ledger: Path | None = None,
    line_id: str | None = None,
) -> dict[str, Any]:
    source = read_json(submit_report)
    base_rows = result_rows(source)
    base_rows = base_rows + adopted_failure_rows(
        source, {str(row.get("task_id")) for row in base_rows if row.get("task_id")})
    rows = list(enumerate(base_rows, 1))
    providers = {row_provider(row) for _index, row in rows if row.get("task_id")}
    giggle_key_environment = "NOT_NEEDED_NO_GIGGLE_TASKS"
    if hopsapi.PROVIDER_GIGGLE in providers or not providers:
        giggle_key_environment = ensure_giggle_api_key()
        if not os.environ.get("GIGGLE_API_KEY"):
            raise SystemExit("GIGGLE_API_KEY is not set")
    if hopsapi.PROVIDER_HOPSAPI in providers and not os.environ.get(hopsapi.API_KEY_ENV, "").strip():
        raise SystemExit(f"{hopsapi.API_KEY_ENV} is not set")
    workers = poll_workers()
    if workers <= 1 or len(rows) <= 1:
        statuses = [poll_one(index, row, out_dir, download) for index, row in rows]
    else:
        # Query every submitted task concurrently.  Results are kept in the submit
        # report's order so the status file (and any diff against it) is stable, and
        # an exception in any task still fails the whole run, exactly as serially.
        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

        with ThreadPoolExecutor(max_workers=min(workers, len(rows))) as pool:
            futures = [pool.submit(poll_one, index, row, out_dir, download)
                       for index, row in rows]
            statuses = [future.result() for future in futures]

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
