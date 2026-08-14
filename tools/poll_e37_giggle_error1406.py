#!/usr/bin/env python3
"""Poll the immutable E37 Error1406 cohort without exposing output URLs."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from giggle_api_client import _get  # noqa: E402
from submit_giggle_task_manifest import ensure_giggle_api_key  # noqa: E402


DEFAULT_INCIDENT = ROOT / "workflow/tasks/E37_GIGGLE_ERROR1406_DEVELOPER_INCIDENT_PACKET_V1_20260802.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sanitize_response(task_id: str, response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") or response
    result = data.get("result") or data.get("output") or {}
    serialized = json.dumps(response, ensure_ascii=False)
    urls = result.get("urls") or data.get("urls") or []
    return {
        "task_id": task_id,
        "query_transport": "PASS" if response.get("code") in {None, 200} else "ERROR",
        "status": data.get("status") or response.get("status") or "unknown",
        "error1406": "Error 1406" in serialized,
        "urls_count": len(urls) if isinstance(urls, list) else int(bool(urls)),
        "file_id_present": bool(result.get("file_id") or data.get("file_id")),
        "asset_info_present": bool(result.get("asset_info") or data.get("asset_info")),
        "extract_results_present": bool(result.get("extract_results") or data.get("extract_results")),
    }


def query_one(task_id: str) -> dict[str, Any]:
    try:
        return sanitize_response(task_id, _get("/api/v1/generation/task/query", {"task_id": task_id}))
    except BaseException as exc:
        return {
            "task_id": task_id,
            "query_transport": "ERROR",
            "status": "unknown",
            "error1406": False,
            "urls_count": 0,
            "file_id_present": False,
            "asset_info_present": False,
            "extract_results_present": False,
            "query_error_type": type(exc).__name__,
        }


def build_report(rows: list[dict[str, Any]], queried_at: str, version: str) -> dict[str, Any]:
    transport_pass = sum(row["query_transport"] == "PASS" for row in rows)
    terminal_failed = sum(row["status"] == "failed" for row in rows)
    same_error1406 = sum(bool(row["error1406"]) for row in rows)
    urls_present = sum(row["urls_count"] > 0 for row in rows)
    file_id_present = sum(bool(row["file_id_present"]) for row in rows)
    asset_info_present = sum(bool(row["asset_info_present"]) for row in rows)
    extract_results_present = sum(bool(row["extract_results_present"]) for row in rows)
    recoverable_outputs = sum(
        row["urls_count"] > 0
        or row["file_id_present"]
        or row["asset_info_present"]
        or row["extract_results_present"]
        for row in rows
    )
    all_still_failed = (
        transport_pass == len(rows)
        and terminal_failed == len(rows)
        and same_error1406 == len(rows)
        and recoverable_outputs == 0
    )
    status = (
        "OUTPUT_RECOVERY_FAIL_ALL_TERMINAL_NO_RECOVERABLE_ASSET"
        if all_still_failed
        else "RECOVERY_SIGNAL_OR_QUERY_VARIANCE_DETECTED_REVIEW_REQUIRED"
    )
    return {
        "schema": f"qingshan.giggle.error1406_recovery_poll.{version}",
        "episode": "E37",
        "queried_at": queried_at,
        "status": status,
        "query_endpoint": "/api/v1/generation/task/query",
        "query_transport": f"PASS_{transport_pass}_OF_{len(rows)}",
        "task_ids": [row["task_id"] for row in rows],
        "task_observations": rows,
        "observed": {
            "terminal_failed": terminal_failed,
            "same_error1406": same_error1406,
            "urls_present": urls_present,
            "file_id_present": file_id_present,
            "asset_info_present": asset_info_present,
            "extract_results_present": extract_results_present,
            "recoverable_outputs": recoverable_outputs,
        },
        "gate_results": {
            "api_key": "PASS_PROTECTED_LOCAL_FILE_NOT_EXPOSED",
            "query_transport": f"PASS_{transport_pass}_OF_{len(rows)}" if transport_pass == len(rows) else "FAIL",
            "terminal_status": f"FAIL_PRESERVED_{terminal_failed}_OF_{len(rows)}",
            "error1406": f"FAIL_PRESERVED_{same_error1406}_OF_{len(rows)}",
            "recovery_fields": "FAIL_EMPTY_ALL" if recoverable_outputs == 0 else "RECOVERY_SIGNAL_PRESENT",
            "provider_output_recovery": "FAIL_NOT_DEMONSTRATED" if all_still_failed else "REVIEW_REQUIRED",
            "paid_canary_gate": "CLOSED_BY_FAIL_CLOSED_GUARD" if all_still_failed else "RERUN_GUARD",
            "new_submission": "NONE",
        },
        "blocked_by": "PROVIDER_OUTPUT_ASSET_DB_ERROR1406_FOR_VIDEO_OUTPUT_ONLY" if all_still_failed else None,
        "workaround_executed": "Queried the exact immutable failure cohort and sanitized all responses to counts and booleans; no URL, secret, signed asset location or credential is persisted.",
        "credits": {
            "pay": 0,
            "refund": 0,
            "net": 0,
            "episode_source_attributable_pay": 1433,
            "episode_source_attributable_refund": 1433,
            "episode_source_attributable_net": 0,
            "episode_cap": 10000,
            "headroom": 10000,
        },
        "next_action": "Keep U08-S3 closed until a provenance-valid recovery signal exists; if variance is detected, rerun the exact-SHA canary guard before any submission.",
    }


def self_test() -> int:
    cases = [
        ({"code": 200, "data": {"status": "failed", "err_msg": "Error 1406"}}, ("failed", True, 0)),
        ({"code": 200, "data": {"status": "completed", "urls": ["redacted"]}}, ("completed", False, 1)),
        ({"code": 200, "data": {"status": "completed", "asset_info": [{"asset_id": "x"}]}}, ("completed", False, 0)),
        ({"code": 200, "data": {"status": "failed", "result": {"file_id": "x"}}}, ("failed", False, 0)),
    ]
    results = []
    for index, (payload, expected) in enumerate(cases, 1):
        actual = sanitize_response(f"case-{index}", payload)
        observed = (actual["status"], actual["error1406"], actual["urls_count"])
        results.append({"case": index, "status": "PASS" if observed == expected else "FAIL"})
    print(json.dumps({"schema": "qingshan.e37.error1406_poll_selftest.v1", "status": "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL", "cases": results}, indent=2))
    return 0 if all(result["status"] == "PASS" for result in results) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incident", type=Path, default=DEFAULT_INCIDENT)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--queried-at", default=None)
    parser.add_argument("--version", default="v7")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.out:
        parser.error("--out is required unless --self-test is used")
    if ensure_giggle_api_key() in {"MISSING", "UNSAFE_FILE_PERMISSIONS"}:
        raise RuntimeError("Giggle API key unavailable")
    incident = json.loads(args.incident.read_text(encoding="utf-8"))
    task_ids = [str(task["task_id"]) for task in incident.get("tasks", [])]
    if len(task_ids) != 8 or len(set(task_ids)) != 8:
        raise RuntimeError("Incident packet must contain exactly eight unique task IDs")
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        rows = list(pool.map(query_one, task_ids))
    report = build_report(rows, args.queried_at or utc_now(), args.version)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(args.out), "observed": report["observed"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
