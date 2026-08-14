#!/usr/bin/env python3
"""Poll and harvest E37 V9 failed-only repairs without replay."""

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
API_SCRIPT = Path.home() / ".codex/skills/giggle-seedance2-gen/scripts/generation_api.py"
SUBMIT = ROOT / "workflow/tasks/E37_V9_FAILED_ONLY_PROMPT_REPAIR_SUBMIT_V1_20260803.json"
OUT_DIR = ROOT / "working_assets/e37_video_20260803/v9_failed_only_prompt_repairs_v1"
QA_DIR = ROOT / "qa/e37_video_20260803/v9_failed_only_prompt_repairs_v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_api():
    spec = importlib.util.spec_from_file_location("giggle_seedance_api", API_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    api = load_api()
    client = api.SeedanceClient(api.check_api_key())
    submit = json.loads(SUBMIT.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for task in submit["tasks"]:
        line, task_id = int(task["line"]), task["task_id"]
        result = client.query_task(task_id)
        data = result.get("data") or {}
        urls = client.extract_urls(result)
        row = {"line": line, "task_id": task_id, "queried_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "status": data.get("status", ""), "err_msg": data.get("err_msg", ""), "url_count": len(urls)}
        if row["status"] == "completed" and urls:
            target = OUT_DIR / f"E37-L{line:03d}-V9-FAILED-ONLY-REPAIR_{task_id}.mp4"
            if not target.exists():
                response = requests.get(urls[0], timeout=120)
                response.raise_for_status()
                target.write_bytes(response.content)
            row.update({"output": str(target.relative_to(ROOT)), "sha256": sha256(target), "size_bytes": target.stat().st_size})
        receipt = QA_DIR / f"E37-L{line:03d}-V9-HARVEST-V1.json"
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        row["receipt"] = str(receipt.relative_to(ROOT))
        row["receipt_sha256"] = sha256(receipt)
        rows.append(row)
    aggregate = {"schema": "qingshan.e37.v9_failed_only_harvest.v1", "episode": "E37", "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "submit_receipt": str(SUBMIT.relative_to(ROOT)), "submit_receipt_sha256": sha256(SUBMIT), "tasks": rows, "counts": {"completed": sum(r["status"] == "completed" for r in rows), "running": sum(r["status"] in {"running", "processing", "pending"} for r in rows), "failed": sum(r["status"] in {"failed", "error"} for r in rows)}, "unchanged_retry": "PROHIBITED"}
    out = QA_DIR / "E37_V9_FAILED_ONLY_HARVEST_V1.json"
    out.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"aggregate": str(out.relative_to(ROOT)), "sha256": sha256(out), "counts": aggregate["counts"], "tasks": rows}, ensure_ascii=False))


if __name__ == "__main__":
    main()
