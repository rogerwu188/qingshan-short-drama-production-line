#!/usr/bin/env python3
"""Build a failed-only retry manifest and optionally merge its new task IDs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-submit-report", type=Path, required=True)
    parser.add_argument("--status-report", type=Path, required=True)
    parser.add_argument("--retry-manifest", type=Path, required=True)
    parser.add_argument("--retry-submit-report", type=Path)
    parser.add_argument("--merged-submit-report", type=Path)
    parser.add_argument("--drop-reference-images", action="store_true")
    parser.add_argument("--single-reference-image", type=Path)
    parser.add_argument("--failed-id", action="append", default=[])
    args = parser.parse_args()

    if args.drop_reference_images and args.single_reference_image:
        parser.error("--drop-reference-images and --single-reference-image are mutually exclusive")

    manifest = read(args.source_manifest)
    submit = read(args.source_submit_report)
    status = read(args.status_report)
    failed_ids = set(args.failed_id) or {
        row.get("dialogue_id")
        for row in status.get("results", [])
        if str(row.get("remote_status", "")).lower() in {"failed", "error", "cancelled", "timeout"}
    }
    retry_tasks = []
    for task in manifest.get("tasks", []):
        if task.get("dialogue_id") not in failed_ids:
            continue
        item = dict(task)
        item["force_resubmit"] = True
        item["retry_reason"] = (
            "REMOTE_REFERENCE_UPLOAD_PROVIDER_FAILURE_PROMPT_ONLY_FALLBACK"
            if args.drop_reference_images
            else "VISUAL_IDENTITY_FAILURE_SINGLE_CANONICAL_REFERENCE_RETRY"
            if args.single_reference_image
            else "REMOTE_REFERENCE_UPLOAD_PROVIDER_FAILURE"
        )
        if args.drop_reference_images:
            item["reference_images"] = []
            item["visual_identity_qa_required"] = True
        elif args.single_reference_image:
            item["reference_images"] = [str(args.single_reference_image)]
            item["visual_identity_qa_required"] = True
        retry_tasks.append(item)

    retry_manifest = dict(manifest)
    retry_manifest["schema"] = "qingshan.giggle_failed_only_retry_manifest.v1"
    retry_manifest["authorization_ref"] = "ROGER-E20-FAILED-ONLY-AUTOMATIC-RETRY"
    retry_manifest["approval_refs"] = ["ROGER-E20-FAILED-ONLY-AUTOMATIC-RETRY"]
    retry_manifest["episode_total_prompt_count"] = len(retry_tasks)
    retry_manifest["retry_of"] = str(args.source_submit_report)
    retry_manifest["retry_policy"] = "Preserve passed/running siblings; concurrently resubmit only failed tasks."
    retry_manifest["prompt_only_fallback"] = args.drop_reference_images
    retry_manifest["tasks"] = retry_tasks
    write(args.retry_manifest, retry_manifest)

    result = {
        "status": "PASS" if retry_tasks and len(retry_tasks) == len(failed_ids) else "FAIL",
        "failed_ids": sorted(value for value in failed_ids if value),
        "retry_task_count": len(retry_tasks),
        "retry_manifest": str(args.retry_manifest),
    }

    if args.retry_submit_report and args.merged_submit_report:
        retry_submit = read(args.retry_submit_report)
        retry_by_id = {row.get("dialogue_id"): row for row in retry_submit.get("results", [])}
        merged_results = []
        for row in submit.get("results", []):
            merged_results.append(retry_by_id.get(row.get("dialogue_id"), row))
        merged = dict(submit)
        merged["schema"] = "qingshan.giggle_merged_retry_submit_report.v1"
        merged["status"] = "PASS" if all(row.get("task_id") for row in merged_results) else "FAIL"
        merged["results"] = merged_results
        merged["retry_submit_report"] = str(args.retry_submit_report)
        merged["replaced_failed_task_count"] = len(retry_by_id)
        write(args.merged_submit_report, merged)
        result["merged_submit_report"] = str(args.merged_submit_report)
        result["merged_task_count"] = len(merged_results)

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
