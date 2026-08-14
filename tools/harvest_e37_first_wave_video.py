#!/usr/bin/env python3
"""Harvest E37 first-wave videos without letting one failed segment stop the batch."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from giggle_api_client import query_task
from giggle_credit_statements import fetch_task_credit_net_by_task_id
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]
VENDORED_FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
FFPROBE = VENDORED_FFPROBE if VENDORED_FFPROBE.is_file() else Path(shutil.which("ffprobe") or "")
TERMINAL_FAILURES = {"failed", "error", "cancelled", "canceled", "timeout"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def media_probe(path: Path) -> dict:
    result = subprocess.run(
        [
            str(FFPROBE), "-v", "error", "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    data["duration_seconds"] = round(float((data.get("format") or {}).get("duration") or 0), 3)
    return data


def download(url: str, output: Path) -> None:
    if not url:
        raise RuntimeError("completed task returned no usable download URL")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "qingshan-e37-harvester/1.0"})
    with urllib.request.urlopen(request, timeout=600) as response, partial.open("wb") as handle:
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            handle.write(chunk)
    if not partial.is_file() or partial.stat().st_size <= 0:
        raise RuntimeError("download produced an empty file")
    partial.replace(output)


def credit_reconciliation(task_id: str) -> dict:
    return fetch_task_credit_net_by_task_id(
        task_id,
        event_description="SingleGenerateVideo",
    )


def settle_attempt(task: dict, success: bool) -> None:
    attempts = task.setdefault("credit_attempts", [])
    attempt = attempts[-1] if attempts else {"attempt": 1, "task_id": task["task_id"]}
    if not attempts:
        attempts.append(attempt)
    statement = credit_reconciliation(str(task["task_id"]))
    attempt["success"] = success
    attempt["credit_statement_reconciliation"] = statement
    attempt["settled_at"] = utc_now()
    if success and statement.get("status") == "PASS_CHARGED":
        attempt["charge_status"] = "EXACT_TASK_ID_STATEMENT_MATCH"
        attempt["actual_charged_credits"] = statement["net_charged_credits"]
        attempt["evidence"] = "credit_statement_project_id_pay_minus_refund"
    elif not success and statement.get("status") == "PASS_ZERO_REFUNDED":
        attempt["charge_status"] = "FAILED_ZERO_NET_AFTER_REFUND"
        attempt["actual_charged_credits"] = 0
        attempt["evidence"] = "credit_statement_pay_minus_refund"
    else:
        attempt["charge_status"] = (
            "SUCCESS_CREDIT_EVIDENCE_INCOMPLETE" if success
            else "FAILED_CREDIT_REFUND_EVIDENCE_INCOMPLETE"
        )
        attempt["actual_charged_credits"] = None


def asset_from_response(data: dict) -> tuple[str, str | None, str | None]:
    assets = data.get("asset_info") or []
    if assets:
        asset = assets[0] or {}
        url = asset.get("download_url") or asset.get("signed_url") or asset.get("url")
        short_url = asset.get("download_url_shorter")
        asset_id = asset.get("asset_id")
        return str(url or ""), short_url, asset_id
    urls = data.get("urls") or []
    if urls:
        first = urls[0]
        if isinstance(first, dict):
            return str(first.get("url") or first.get("download_url") or ""), first.get("short_url"), first.get("asset_id")
        return str(first), None, None
    return "", None, None


def task_output(output_dir: Path, task: dict) -> Path:
    return output_dir / f"{task['task_key']}_{task['task_id']}.mp4"


def harvest_task(task: dict, output_dir: Path) -> str:
    existing = task.get("output_path")
    if existing:
        path = Path(existing)
        path = path if path.is_absolute() else ROOT / path
        if path.is_file() and path.stat().st_size > 0:
            task["state"] = "local_downloaded_pending_qa"
            return "downloaded"

    response = query_task(SimpleNamespace(task_id=task["task_id"]))
    data = response.get("data") or {}
    status = str(data.get("status") or "unknown").lower()
    task["remote_status"] = status
    task["last_polled_at"] = utc_now()

    if status == "completed":
        url, short_url, asset_id = asset_from_response(data)
        output = task_output(output_dir, task)
        if not output.is_file() or output.stat().st_size <= 0:
            download(url, output)
        probe = media_probe(output)
        task.update({
            "state": "local_downloaded_pending_qa",
            "output_path": str(output.relative_to(ROOT)),
            "output_sha256": sha256(output),
            "output_size_bytes": output.stat().st_size,
            "output_duration_seconds": probe["duration_seconds"],
            "media_probe": probe,
            "remote_short_url": short_url,
            "remote_asset_id": asset_id,
            "downloaded_at": utc_now(),
        })
        settle_attempt(task, True)
        return "downloaded"

    if status in TERMINAL_FAILURES:
        task.update({
            "state": "remote_failed_preserved",
            "failure_reason": data.get("err_msg") or data.get("error") or status,
            "retry_policy": "NO_UNCHANGED_RETRY; evaluate materially changed transport or zero-credit salvage",
        })
        settle_attempt(task, False)
        return "failed"

    task["state"] = "remote_running"
    return "running"


def refresh_summary(receipt: dict) -> None:
    tasks = receipt.get("tasks", [])
    downloaded = [row for row in tasks if row.get("state") == "local_downloaded_pending_qa"]
    running = [row for row in tasks if row.get("state") == "remote_running"]
    failed = [row for row in tasks if row.get("state") == "remote_failed_preserved"]
    attempts = [attempt for row in tasks for attempt in row.get("credit_attempts", [])]
    known = [attempt["actual_charged_credits"] for attempt in attempts if isinstance(attempt.get("actual_charged_credits"), (int, float))]
    unknown = [attempt for attempt in attempts if attempt.get("success") is not None and attempt.get("actual_charged_credits") is None]
    receipt.update({
        "active_task_ids": [row["task_id"] for row in running],
        "active_task_count": len(running),
        "downloaded_count": len(downloaded),
        "remote_failed_count": len(failed),
        "credit_summary": {
            "known_net_credits": sum(known),
            "settled_attempt_count": sum(attempt.get("success") is not None for attempt in attempts),
            "unknown_settled_attempt_count": len(unknown),
        },
        "status": (
            "ALL_TERMINAL_WITH_PRESERVED_FAILURES_PENDING_QA" if not running and failed
            else "ALL_DOWNLOADED_PENDING_QA" if len(downloaded) == len(tasks)
            else "PARTIAL_DOWNLOADED_REMOTE_RUNNING"
        ),
        "last_harvested_at": utc_now(),
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    if ensure_giggle_api_key() in {"MISSING", "UNSAFE_FILE_PERMISSIONS"}:
        raise RuntimeError("Giggle API key unavailable")
    if not FFPROBE.is_file():
        raise RuntimeError("ffprobe missing from both AgentCut vendor runtime and PATH")

    receipt_path = Path(args.receipt).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    counts = {"downloaded": 0, "running": 0, "failed": 0}
    errors = []
    for task in receipt.get("tasks", []):
        try:
            counts[harvest_task(task, output_dir)] += 1
        except Exception as exc:
            task["last_harvest_error"] = f"{type(exc).__name__}: {exc}"
            task["last_harvest_error_at"] = utc_now()
            errors.append({"task_key": task.get("task_key"), "error": task["last_harvest_error"]})

    refresh_summary(receipt)
    receipt["harvest_errors"] = errors
    temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(receipt_path)
    print(json.dumps({
        "status": receipt["status"],
        **counts,
        "errors": errors,
        "credit_summary": receipt["credit_summary"],
        "receipt": str(receipt_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
