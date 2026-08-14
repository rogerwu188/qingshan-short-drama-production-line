#!/usr/bin/env python3
"""Build a failed-only retry that transports existing image references by asset_id."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def asset_index(raw_dirs: list[Path]) -> dict[str, str]:
    index: dict[str, str] = {}
    for raw_dir in raw_dirs:
        for path in raw_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            data = payload.get("data") or {}
            task_id = str(data.get("task_id") or "")
            assets = data.get("asset_info") or []
            asset_id = str((assets[0] if assets else {}).get("asset_id") or "")
            if task_id and asset_id:
                index[task_id] = asset_id
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-config", required=True)
    parser.add_argument("--source-receipt", required=True)
    parser.add_argument("--task-key", required=True)
    parser.add_argument("--raw-dir", action="append", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    config = json.loads(resolve(args.source_config).read_text(encoding="utf-8"))
    receipt = json.loads(resolve(args.source_receipt).read_text(encoding="utf-8"))
    prior = next(task for task in receipt.get("tasks", []) if task.get("task_key") == args.task_key)
    if prior.get("state") not in {"submit_failed_terminal", "remote_failed_terminal"}:
        raise SystemExit("source task must be an explicit submit or remote failure")
    if any((row.get("actual_charged_credits") or 0) != 0 for row in prior.get("credit_attempts", [])):
        raise SystemExit("source task must have explicit zero charged credits")

    source = next(task for task in config.get("tasks", []) if task.get("task_key") == args.task_key)
    references = list(source.get("reference_images") or [])
    index = asset_index([resolve(value) for value in args.raw_dir])
    asset_ids = []
    bindings = []
    for value in references:
        path = resolve(value)
        task_id = path.stem.rsplit("_", 1)[-1]
        asset_id = index.get(task_id)
        if not asset_id:
            raise SystemExit(f"no asset_id found for {path}")
        asset_ids.append(asset_id)
        bindings.append({
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source_task_id": task_id,
            "asset_id": asset_id,
        })

    task = dict(source)
    task["reference_image_asset_ids"] = asset_ids
    task["image_transport"] = "asset_id"
    task["image_asset_bindings"] = bindings
    task["transport_retry_of"] = args.source_receipt
    task["transport_change_reason"] = "HTTP_REQUEST_BODY_OVER_64_MB_BASE64_TO_EXISTING_ASSET_IDS"
    task["state"] = "pending"
    task["status"] = "READY_TO_SUBMIT"
    task.pop("task_id", None)
    task.pop("submit_response", None)
    task.pop("credit_attempts", None)
    task.pop("retry_count", None)
    task.pop("retry_after", None)

    output = dict(config)
    output["status"] = "READY_TO_SUBMIT"
    output["recorded_at"] = datetime.now(timezone.utc).isoformat()
    output["tasks"] = [task]
    output["ready_unit_count"] = 1
    output["waiting_unit_count"] = 0
    output["retry_of"] = args.source_receipt
    output["retry_states"] = ["submit_failed_terminal"]
    output["transport_policy"] = "PRESERVE_ALL_IMAGE_STATES_USE_EXISTING_GIGGLE_ASSET_IDS"
    output["base_batch_note"] = "Transport-only retry after explicit zero-credit HTTP 400; all semantic references are preserved."

    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "READY_TO_SUBMIT", "task_key": args.task_key, "image_asset_ids": len(asset_ids), "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
