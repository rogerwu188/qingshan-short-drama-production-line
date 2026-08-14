#!/usr/bin/env python3
"""Poll, download, hash, and cost-bind a submitted Giggle image batch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from giggle_api_client import query_task
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "-" for char in value)


def extension(url: str, asset: dict[str, Any]) -> str:
    path = urllib.parse.urlparse(asset.get("signed_url") or url).path
    suffix = Path(path).suffix.lower()
    return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp"} else ".png"


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "qingshan-image-harvester/1.0"})
    with urllib.request.urlopen(request, timeout=240) as response:
        temp.write_bytes(response.read())
    temp.replace(destination)


def poll_one(row: dict[str, Any], out_dir: Path, raw_dir: Path) -> dict[str, Any]:
    response = query_task(SimpleNamespace(task_id=row["task_id"]))
    raw_path = raw_dir / f"{safe_name(row['task_key'])}_{row['task_id']}.json"
    atomic_json(raw_path, response)
    data = response.get("data") or {}
    status = str(data.get("status") or "UNKNOWN")
    result = {**row, "remote_status": status, "raw_response": str(raw_path)}
    if status != "completed":
        if status in {"failed", "error", "cancelled"}:
            result.update({"credit": 0, "credit_status": "FAILED_ZERO", "error": data.get("err_msg")})
        return result
    assets = data.get("asset_info") or []
    urls = data.get("urls") or []
    asset = assets[0] if assets else {}
    url = asset.get("download_url") or asset.get("signed_url") or (urls[0] if urls else None)
    if not url:
        result.update({"remote_status": "completed_missing_url", "error": "completed response has no image URL"})
        return result
    destination = out_dir / f"{safe_name(row['task_key'])}_{row['task_id']}{extension(str(url), asset)}"
    if not destination.is_file():
        download(str(url), destination)
    result.update({
        "output_path": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "bytes": destination.stat().st_size, "asset_id": asset.get("asset_id"),
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit-report", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    ensure_giggle_api_key()
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("GIGGLE_API_KEY is not set")
    submit_path = resolve(args.submit_report)
    out_dir = resolve(args.out_dir)
    out_path = resolve(args.out)
    raw_dir = out_dir.parent / f"raw_{out_dir.name}"
    submit = json.loads(submit_path.read_text())
    rows = submit.get("results") or []
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(poll_one, row, out_dir, raw_dir) for row in rows]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: row["task_key"])
    reconciliation = submit.get("credit_reconciliation") or {}
    statements = reconciliation.get("statement_rows") or []
    amounts = [abs(float(row["credit"])) for row in statements if row.get("credit") is not None]
    uniform_credit = amounts[0] if amounts and len(amounts) == len(rows) and len(set(amounts)) == 1 else None
    if reconciliation.get("status") in {"PASS", "PASS_BOUNDED"} and uniform_credit is not None:
        for row in results:
            if row.get("remote_status") == "completed":
                row.update({"credit": uniform_credit, "credit_status": "KNOWN_BATCH_LEDGER_EXACT_COUNT"})
    counts: dict[str, int] = {}
    for row in results:
        counts[row["remote_status"]] = counts.get(row["remote_status"], 0) + 1
    complete = bool(results) and counts.get("completed", 0) == len(results)
    payload = {
        "schema": "qingshan.giggle_image_batch_harvest.v1", "episode": submit.get("episode"),
        "status": "PASS" if complete else "PENDING_REMOTE", "submit_report": str(submit_path),
        "status_counts": counts, "all_completed": complete,
        "credit_reconciliation": reconciliation, "results": results,
    }
    atomic_json(out_path, payload)
    print(json.dumps({"status": payload["status"], "counts": counts, "out": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
