#!/usr/bin/env python3
"""Poll and download both E38 V6 submit waves."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import urllib.request

from giggle_api_shot_runner import query


ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = [
    ROOT / "workflow/tasks/E38_V6_AUDIO_DRIVEN_NO_GLYPHS_PARALLEL_SUBMIT_20260805.json",
    ROOT / "workflow/tasks/E38_V6_AUDIO_DRIVEN_NO_GLYPHS_PARALLEL_SUBMIT_R3_20260805.json",
]
STATUS = ROOT / "workflow/tasks/E38_V6_AUDIO_DRIVEN_NO_GLYPHS_STATUS_20260805.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "qingshan-e38-v6-poller/1.0"})
    with urllib.request.urlopen(request, timeout=240) as response:
        path.write_bytes(response.read())


def main() -> int:
    rows = []
    for receipt in RECEIPTS:
        rows.extend(json.loads(receipt.read_text(encoding="utf-8"))["results"])
    results = []
    counts: dict[str, int] = {}
    for row in rows:
        response = query(os.environ["GIGGLE_API_KEY"], row["task_id"])
        data = response.get("data") or {}
        status = data.get("status") or "UNKNOWN"
        counts[status] = counts.get(status, 0) + 1
        out_dir = Path(row["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "last_query_response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output = out_dir / "result_01.mp4"
        urls = data.get("urls") or []
        if status == "completed" and urls and not output.exists():
            download(urls[0], output)
        results.append({
            **row,
            "remote_status": status,
            "urls": urls,
            "asset_info": data.get("asset_info") or [],
            "output_path": str(output) if output.exists() else None,
            "output_sha256": sha(output) if output.exists() else None,
            "output_bytes": output.stat().st_size if output.exists() else None,
            "fail_reason": data.get("fail_reason") or data.get("err_msg"),
        })
    payload = {
        "schema": "qingshan.e38_v6_audio_driven_remote_status.v1",
        "episode": "E38",
        "status": "PASS_COMPLETED" if counts.get("completed", 0) == len(results) else "IN_PROGRESS_OR_FAILED",
        "status_counts": counts,
        "results": sorted(results, key=lambda item: item["shot_id"]),
    }
    STATUS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "counts": counts, "status_path": str(STATUS)}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS_COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
