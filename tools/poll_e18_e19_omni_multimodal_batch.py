#!/usr/bin/env python3
"""Poll and download submitted E18/E19 omni multimodal candidate tasks."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from giggle_api_client import query_task


BASE = Path("/Users/rogerwu/qingshan_short_drama")
RECEIPT = BASE / "workflow/generation/e18_e19/E18_E19_FINAL_OMNI_MULTIMODAL_SUBMIT_RECEIPT_20260715.json"
STATUS = BASE / "workflow/generation/e18_e19/E18_E19_FINAL_OMNI_MULTIMODAL_REMOTE_STATUS_20260715.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def download(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "qingshan-e18-e19-omni-poller/1.0"})
    with urllib.request.urlopen(req, timeout=240) as resp:
        out_path.write_bytes(resp.read())


class Args:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id


def task_out_dir(result: dict[str, Any]) -> Path:
    receipt = Path(result["receipt"])
    return receipt.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll submitted E18/E19 omni multimodal tasks.")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("Missing GIGGLE_API_KEY")
    receipt = read_json(RECEIPT)
    statuses: list[dict[str, Any]] = []
    for result in receipt.get("results", []):
        task_id = result.get("task_id")
        if not task_id:
            statuses.append({**result, "remote_status": "NO_TASK_ID"})
            continue
        out_dir = task_out_dir(result)
        response = query_task(Args(task_id))
        (out_dir / "last_query_response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        data = response.get("data") or {}
        remote_status = data.get("status") or "UNKNOWN"
        files: list[str] = []
        if args.download and remote_status == "completed":
            urls = data.get("urls") or []
            for idx, url in enumerate(urls, 1):
                out_path = out_dir / f"result_{idx:02d}.mp4"
                if not out_path.exists():
                    download(url, out_path)
                files.append(str(out_path))
        statuses.append(
            {
                **result,
                "remote_status": remote_status,
                "downloaded_files": files or [str(p) for p in sorted(out_dir.glob("result_*.mp4"))],
            }
        )
    counts: dict[str, int] = {}
    for item in statuses:
        counts[item["remote_status"]] = counts.get(item["remote_status"], 0) + 1
    payload = {
        "schema": "qingshan.e18_e19_omni_multimodal_remote_status.v1",
        "receipt": str(RECEIPT),
        "status_counts": counts,
        "all_completed": counts.get("completed", 0) == len(statuses),
        "results": statuses,
    }
    STATUS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status_counts": counts, "status_path": str(STATUS)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
