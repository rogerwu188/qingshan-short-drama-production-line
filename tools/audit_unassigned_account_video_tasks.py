#!/usr/bin/env python3
"""Query read-only task metadata for account video charges lacking local evidence."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from giggle_api_client import _get
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]
EPISODE_RE = re.compile(r"(?i)(?:^|[/_.-])(E(?:1[7-9]R?|2[0-8]))(?:[/_.-]|$)")
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".log", ".yaml", ".yml", ".csv", ".tsv"}


def resolve(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def local_episode_evidence(task_ids: set[str], excluded: set[Path]) -> dict[str, dict[str, set[str]]]:
    evidence: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    roots = [ROOT / "workflow", ROOT / "working_assets", ROOT / "qa"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES or path.resolve() in excluded:
                continue
            if "bridge_outgoing" in path.parts or "bridge_incoming" in path.parts:
                continue
            path_match = EPISODE_RE.search(str(path.relative_to(ROOT)))
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            present = task_ids.intersection(re.findall(r"[0-9a-fA-F-]{36}", content))
            if not present:
                continue
            episode = path_match.group(1).upper() if path_match else None
            for task_id in present:
                if episode:
                    evidence[task_id][episode].add(str(path.relative_to(ROOT)))
    return evidence


def query_task(task_id: str) -> dict:
    try:
        response = _get("/api/v1/generation/task/query", {"task_id": task_id})
    except BaseException as exc:
        return {"task_id": task_id, "query_status": "ERROR", "error": str(exc), "credits_consumed": 0}
    data = response.get("data") or {}
    assets = data.get("asset_info") or []
    return {
        "task_id": task_id,
        "query_status": "PASS" if response.get("code") == 200 else "ERROR",
        "response_code": response.get("code"),
        "remote_status": data.get("status"),
        "remote_error": data.get("err_msg") or "",
        "asset_count": len(assets),
        "assets": [
            {
                "asset_id": asset.get("asset_id"),
                "duration": asset.get("duration"),
                "file_type": asset.get("file_type"),
                "status": asset.get("status"),
                "signed_url": asset.get("signed_url"),
                "thumbnail_url": asset.get("thumbnail_url"),
            }
            for asset in assets
        ],
        "credits_consumed": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-audit", required=True)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    if ensure_giggle_api_key() in {"MISSING", "UNSAFE_FILE_PERMISSIONS"}:
        raise RuntimeError("Giggle API key unavailable")

    account_path = resolve(args.account_audit)
    account = json.loads(account_path.read_text(encoding="utf-8"))
    rows = account.get("unmatched_video_statements") or []
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        task_id = str(row.get("project_id") or "")
        if task_id:
            grouped[task_id].append(row)

    out = resolve(args.out)
    excluded = {account_path.resolve(), out.resolve(), *(resolve(value).resolve() for value in args.exclude)}
    evidence = local_episode_evidence(set(grouped), excluded)
    unassigned_ids = sorted(task_id for task_id in grouped if not evidence.get(task_id))
    recovered_ids = sorted(task_id for task_id in grouped if evidence.get(task_id))
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        queried = list(pool.map(query_task, unassigned_ids))

    query_map = {row["task_id"]: row for row in queried}
    tasks = []
    for task_id in unassigned_ids:
        statements = grouped[task_id]
        credits = int(sum((abs(Decimal(str(row["credit"]))) for row in statements), Decimal("0")))
        tasks.append({
            "task_id": task_id,
            "statement_count": len(statements),
            "statement_credits": credits,
            "statement_times": sorted(str(row.get("created_at") or "") for row in statements),
            "statement_models": sorted({str(row.get("model") or "") for row in statements}),
            **query_map[task_id],
        })

    query_errors = sum(row["query_status"] != "PASS" for row in tasks)
    recovered = []
    for task_id in recovered_ids:
        statements = grouped[task_id]
        credits = int(sum((abs(Decimal(str(row["credit"]))) for row in statements), Decimal("0")))
        recovered.append({
            "task_id": task_id,
            "statement_count": len(statements),
            "statement_credits": credits,
            "episode_evidence": {
                episode: sorted(paths) for episode, paths in sorted(evidence[task_id].items())
            },
        })
    report = {
        "schema": "qingshan.unassigned_account_video_task_metadata_audit.v1",
        "status": "PASS_UNASSIGNED_RETAINED" if not query_errors else "PARTIAL_QUERY_ERRORS",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_account_audit": str(account_path.relative_to(ROOT)),
        "method": "LOCAL_EPISODE_EVIDENCE_FILTER_THEN_READ_ONLY_REMOTE_TASK_QUERY",
        "policy": "Remote status and asset metadata alone do not prove Qingshan episode ownership; keep tasks unassigned without an episode-bearing receipt or asset match.",
        "newly_recovered_local_evidence_task_count": len(recovered),
        "newly_recovered_local_evidence_statement_count": sum(row["statement_count"] for row in recovered),
        "newly_recovered_local_evidence_credits": sum(row["statement_credits"] for row in recovered),
        "newly_recovered_local_evidence_tasks": recovered,
        "unassigned_unique_task_count": len(tasks),
        "unassigned_statement_count": sum(row["statement_count"] for row in tasks),
        "unassigned_statement_credits": sum(row["statement_credits"] for row in tasks),
        "completed_remote_task_count": sum(row.get("remote_status") == "completed" for row in tasks),
        "remote_query_error_count": query_errors,
        "tasks": tasks,
        "remote_call_count": len(tasks),
        "remote_call_type": "READ_ONLY_TASK_QUERY",
        "generation_call_count": 0,
        "new_credits": 0,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "tasks": len(tasks),
        "statements": report["unassigned_statement_count"],
        "credits": report["unassigned_statement_credits"],
        "completed": report["completed_remote_task_count"],
        "errors": query_errors,
        "out": str(out),
    }, ensure_ascii=False))
    return 0 if not query_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
