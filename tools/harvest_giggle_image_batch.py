#!/usr/bin/env python3
"""Poll and download a submitted Giggle image batch without resubmission."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.request import Request, urlopen

try:
    from giggle_api_client import query_task
    from submit_giggle_task_manifest import ensure_giggle_api_key
except ModuleNotFoundError:  # Imported as tools.harvest_giggle_image_batch.
    from tools.giggle_api_client import query_task
    from tools.submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"completed", "failed", "error", "cancelled", "timeout"}
CREDIT_KEYS = {
    "credit", "credits", "credit_cost", "credits_cost", "consumed_credit",
    "consumed_credits", "credit_used", "credits_used", "used_credit",
    "used_credits", "point_cost", "points_cost", "consumed_points",
}


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "task"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def explicit_credit(payload: Any) -> int | float | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).lower()
            if normalized in CREDIT_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool):
                return value
        for value in payload.values():
            found = explicit_credit(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = explicit_credit(value)
            if found is not None:
                return found
    return None


def batch_credit_assignment(source: dict[str, Any], result_count: int) -> tuple[int | float | None, dict[str, Any] | None]:
    """Return per-item credit only for an exact, uniform isolated batch ledger."""
    reconciliation = source.get("credit_reconciliation")
    if not isinstance(reconciliation, dict) or reconciliation.get("status") not in {"PASS", "PASS_BOUNDED"}:
        return None, reconciliation if isinstance(reconciliation, dict) else None
    rows = reconciliation.get("statement_rows") or []
    if reconciliation.get("matched_count") != result_count or len(rows) != result_count or result_count < 1:
        return None, reconciliation
    values: list[float] = []
    for row in rows:
        try:
            values.append(abs(float(row["credit"])))
        except (KeyError, TypeError, ValueError):
            return None, reconciliation
    if len(set(values)) != 1:
        return None, reconciliation
    value = values[0]
    return int(value) if value.is_integer() else value, reconciliation


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = Request(url, headers={"User-Agent": "qingshan-image-batch-harvester/1.0"})
    with urlopen(request, timeout=240) as response, partial.open("wb") as target:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            target.write(chunk)
    os.replace(partial, destination)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def poll_once(submit_report: Path, output_dir: Path, raw_dir: Path) -> dict[str, Any]:
    source = json.loads(submit_report.read_text(encoding="utf-8"))
    episode = safe(str(source.get("episode") or "EPISODE"))
    rows = source.get("results") or []
    batch_credit, credit_reconciliation = batch_credit_assignment(source, len(rows))
    results: list[dict[str, Any]] = []
    for row in rows:
        task_id = row["task_id"]
        response = query_task(SimpleNamespace(task_id=task_id))
        raw_path = raw_dir / f"{safe(row['task_key'])}_{task_id}.json"
        atomic_json(raw_path, response)
        data = response.get("data") or {}
        status = str(data.get("status") or "unknown").lower()
        explicit = explicit_credit(response)
        credit = explicit if explicit is not None else batch_credit if status == "completed" else None
        item: dict[str, Any] = {
            **row,
            "remote_status": status,
            "credit": 0 if status in {"failed", "error", "cancelled", "timeout"} else credit,
            "credit_status": (
                "FAILED_ZERO" if status in {"failed", "error", "cancelled", "timeout"}
                else "EXPLICIT" if explicit is not None
                else "KNOWN_BATCH_LEDGER_EXACT_COUNT" if credit is not None
                else "UNKNOWN_API_FIELD_MISSING" if status == "completed"
                else "PENDING"
            ),
            "raw_response": str(raw_path),
        }
        urls = data.get("urls") or []
        if status == "completed" and urls:
            output = output_dir / f"{episode}_{safe(row['task_key'])}_{task_id}.png"
            if not output.is_file():
                download(str(urls[0]), output)
            item.update({"output_path": str(output), "sha256": sha256(output), "bytes": output.stat().st_size})
        results.append(item)
    counts: dict[str, int] = {}
    for item in results:
        counts[item["remote_status"]] = counts.get(item["remote_status"], 0) + 1
    return {
        "schema": "qingshan.giggle_image_batch_harvest.v1",
        "episode": source.get("episode"),
        "submit_report": str(submit_report),
        "status_counts": counts,
        "all_terminal": bool(results) and all(item["remote_status"] in TERMINAL for item in results),
        "all_completed": bool(results) and all(item["remote_status"] == "completed" for item in results),
        "credit_known_total": sum(item["credit"] for item in results if isinstance(item.get("credit"), (int, float))),
        "credit_unknown_success_count": sum(item["credit_status"] == "UNKNOWN_API_FIELD_MISSING" for item in results),
        "credit_reconciliation": credit_reconciliation,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit-report", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--status-report", required=True)
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args()
    ensure_giggle_api_key()
    submit_report = resolve(args.submit_report)
    output_dir = resolve(args.output_dir)
    raw_dir = resolve(args.raw_dir)
    status_report = resolve(args.status_report)
    while True:
        payload = poll_once(submit_report, output_dir, raw_dir)
        atomic_json(status_report, payload)
        print(json.dumps({"status_counts": payload["status_counts"], "all_terminal": payload["all_terminal"]}, ensure_ascii=False), flush=True)
        if not args.watch or payload["all_terminal"]:
            return 0 if payload["all_completed"] else 2 if payload["all_terminal"] else 0
        time.sleep(max(2, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
