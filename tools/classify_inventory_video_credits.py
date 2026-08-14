#!/usr/bin/env python3
"""Classify mixed-media task ids by exact Giggle video credit statements."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from giggle_api_client import _get
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def statements(task_id: str) -> list[dict]:
    response = _get(
        "/api/v1/payment/credit-statements",
        {"credit_type": "Pay", "page": 1, "page_size": 10, "project_id": task_id},
    )
    if response.get("code") != 200:
        raise RuntimeError(f"credit statement query failed for {task_id}")
    return [
        row for row in ((response.get("data") or {}).get("list") or [])
        if str(row.get("project_id")) == task_id
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", action="append", required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if ensure_giggle_api_key() in {"MISSING", "UNSAFE_FILE_PERMISSIONS"}:
        raise RuntimeError("Giggle API key unavailable")

    candidates: dict[str, dict] = {}
    inventory_sources = []
    for inventory_arg in args.inventory:
        path = resolve(inventory_arg)
        document = json.loads(path.read_text(encoding="utf-8"))
        episode = str(document["episode"])
        inventory_sources.append(str(path.relative_to(ROOT)))
        for row in document.get("new_candidate_task_ids") or []:
            task_id = str(row["task_id"])
            item = candidates.setdefault(task_id, {"task_id": task_id, "candidate_episodes": [], "source_files": []})
            if episode not in item["candidate_episodes"]:
                item["candidate_episodes"].append(episode)
            for source in row.get("source_files") or []:
                if source not in item["source_files"]:
                    item["source_files"].append(source)

    ordered = sorted(candidates)
    selected = ordered[args.offset:args.offset + max(0, args.limit)]
    results = []
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {pool.submit(statements, task_id): task_id for task_id in selected}
        for future in as_completed(futures):
            task_id = futures[future]
            item = candidates[task_id]
            try:
                rows = future.result()
            except BaseException as exc:
                errors.append({"task_id": task_id, "error": str(exc)})
                continue
            video_rows = [row for row in rows if row.get("event_description") == "SingleGenerateVideo"]
            if len(video_rows) > 1:
                errors.append({"task_id": task_id, "error": "multiple SingleGenerateVideo charge rows"})
                continue
            if video_rows:
                credit = abs(Decimal(str(video_rows[0]["credit"])))
                item.update({
                    "classification": "EXACT_VIDEO_CHARGE",
                    "actual_charged_credits": int(credit) if credit == credit.to_integral() else str(credit),
                    "video_statement": video_rows[0],
                })
            else:
                item.update({
                    "classification": "NO_VIDEO_CHARGE_FOR_EXACT_TASK_ID",
                    "actual_charged_credits": 0,
                    "other_statement_event_descriptions": sorted({str(row.get("event_description")) for row in rows}),
                })
            item["attribution"] = item["candidate_episodes"][0] if len(item["candidate_episodes"]) == 1 else "SHARED_E18R_E19R_PENDING_SOURCE_ATTRIBUTION"
            results.append(item)

    results.sort(key=lambda row: row["task_id"])
    charged = [row for row in results if row["classification"] == "EXACT_VIDEO_CHARGE"]
    total = sum(Decimal(str(row["actual_charged_credits"])) for row in charged)
    report = {
        "schema": "qingshan.inventory_video_credit_classification_batch.v1",
        "status": "PASS" if not errors and len(results) == len(selected) else "INCOMPLETE",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "endpoint": "/api/v1/payment/credit-statements",
        "method": "GLOBAL_DEDUPED_EXACT_PROJECT_ID_VIDEO_EVENT_CLASSIFICATION",
        "inventory_sources": inventory_sources,
        "global_candidate_task_id_count": len(ordered),
        "batch_offset": args.offset,
        "batch_limit": args.limit,
        "selected_task_id_count": len(selected),
        "classified_task_id_count": len(results),
        "video_charge_task_count": len(charged),
        "non_video_or_no_charge_task_count": len(results) - len(charged),
        "video_credits_known_total": int(total) if total == total.to_integral() else str(total),
        "errors": errors,
        "results": results,
        "generation_call_count": 0,
        "new_credits": 0,
    }
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "global_candidates": len(ordered),
        "selected": len(selected),
        "classified": len(results),
        "video_charges": len(charged),
        "video_credits": report["video_credits_known_total"],
        "out": str(out),
    }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
