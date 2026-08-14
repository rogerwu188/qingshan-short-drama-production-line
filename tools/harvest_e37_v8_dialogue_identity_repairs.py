#!/usr/bin/env python3
"""Poll and harvest E37 V8 dialogue/identity repair tasks without replay."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
API_SCRIPT = Path.home() / ".codex/skills/giggle-seedance2-gen/scripts/generation_api.py"
SUBMIT = ROOT / "workflow/tasks/E37_V8_DIALOGUE_IDENTITY_REPAIR_SUBMIT_V1_20260803.json"
OUT_DIR = ROOT / "working_assets/e37_video_20260803/v8_dialogue_identity_repairs_v1"
QA_DIR = ROOT / "qa/e37_video_20260803/v8_dialogue_identity_repairs_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_api():
    spec = importlib.util.spec_from_file_location("giggle_seedance_api", API_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {API_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    api = load_api()
    key = api.check_api_key()
    if not key:
        raise RuntimeError("GIGGLE_API_KEY missing")
    client = api.SeedanceClient(key)
    submit = json.loads(SUBMIT.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for task in submit["tasks"]:
        line = int(task["line"])
        task_id = task["task_id"]
        result = client.query_task(task_id)
        data = result.get("data", {})
        status = data.get("status", "")
        row = {
            "line": line,
            "task_id": task_id,
            "queried_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": status,
            "err_msg": data.get("err_msg", ""),
            "urls": client.extract_urls(result),
        }
        if status == "completed" and row["urls"]:
            target = OUT_DIR / f"E37-L{line:03d}-V8-DIALOGUE-IDENTITY-REPAIR_{task_id}.mp4"
            if not target.exists():
                response = requests.get(row["urls"][0], timeout=120)
                response.raise_for_status()
                target.write_bytes(response.content)
            row.update({
                "output": str(target.relative_to(ROOT)),
                "sha256": sha256(target),
                "size_bytes": target.stat().st_size,
            })
        per_line = QA_DIR / f"E37-L{line:03d}-V8-HARVEST-V1.json"
        per_line.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        row["receipt"] = str(per_line.relative_to(ROOT))
        row["receipt_sha256"] = sha256(per_line)
        rows.append(row)
    aggregate = {
        "schema": "qingshan.e37.v8_dialogue_identity_repair_harvest.v1",
        "episode": "E37",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "submit_receipt": str(SUBMIT.relative_to(ROOT)),
        "submit_receipt_sha256": sha256(SUBMIT),
        "tasks": rows,
        "counts": {
            "completed": sum(row["status"] == "completed" for row in rows),
            "running": sum(row["status"] in {"running", "processing", "pending"} for row in rows),
            "failed": sum(row["status"] in {"failed", "error"} for row in rows),
        },
        "unchanged_retry": "PROHIBITED",
    }
    aggregate_path = QA_DIR / "E37_V8_DIALOGUE_IDENTITY_REPAIR_HARVEST_V1.json"
    aggregate_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"aggregate": str(aggregate_path), "sha256": sha256(aggregate_path), "counts": aggregate["counts"], "tasks": rows}, ensure_ascii=False))


if __name__ == "__main__":
    main()
