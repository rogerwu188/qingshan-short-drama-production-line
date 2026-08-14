#!/usr/bin/env python3
"""Execute the authorized U18 exact-two image posts once, without status polling."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLED = Path("/Users/rogerwu/.local/share/backlotos/share/pipeline-tools/submit_giggle_image_manifest.py")
PIPELINE_TOOLS = INSTALLED.parent
sys.path.insert(0, str(PIPELINE_TOOLS))

MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/keyframe_precompile/u18_isolated_asset_acquisition_v1/E40_U18_EXACT_TWO_INSTALLED_PRECHECK_MANIFEST_V1.json"
AUTH = ROOT / "workflow/approvals/E40_U18_EXACT_TWO_ISOLATED_ASSET_IMAGE_AUTHORIZATION_20260813.json"
READINESS = ROOT / "qa/e40_preproduction_20260813/u18_exact_two_isolated_asset_precheck_v1/E40_U18_EXACT_TWO_EXECUTION_READINESS_AUDIT_V1.json"
WORK_QUEUE = ROOT / "workflow/work_queue.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANONICAL_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
OUT_DIR = ROOT / "qa/e40_production_20260813/u18_exact_two_isolated_asset_execution_v1"
REPORT = OUT_DIR / "E40_U18_EXACT_TWO_ONE_POST_TASK_ID_BINDING_RECEIPT_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_installed():
    spec = importlib.util.spec_from_file_location("e40_u18_installed_image_submitter", INSTALLED)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load installed image submitter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args()
    del args

    submitter = load_installed()
    auth = load(AUTH)
    manifest = load(MANIFEST)
    readiness = load(READINESS)
    queue = load(WORK_QUEUE)

    assert auth["authorized"] is True
    assert auth["status"] == "AUTHORIZED_EXACTLY_TWO_NOT_YET_EXECUTED"
    assert sha(SCRIPT) == auth["canonical_script_sha256"] == manifest["canonical_script_sha256"]
    assert sha(CANONICAL_MANIFEST) == auth["canonical_manifest_sha256"] == manifest["canonical_manifest_sha256"]
    assert sha(MANIFEST) == auth["authorized_manifest"]["sha256"]
    assert sha(READINESS) == auth["execution_readiness_audit"]["sha256"]
    assert sha(INSTALLED) == auth["installed_submitter"]["sha256"]
    assert sha(WORK_QUEUE) == auth["execution_limits"]["work_queue_sha256_at_authorization"]
    assert queue["e40_credits"]["net"] + auth["execution_limits"]["aggregate_hard_credit_cap"] <= queue["e40_credits"]["cap"]

    gates = [submitter.validate_gate(path) for path in manifest["machine_gate_reports"]]
    submitter.validate_anchor_count_gate_requirement(manifest, gates)
    tasks = manifest["tasks"]
    assert len(tasks) == auth["execution_limits"]["maximum_new_submissions"] == 2
    authorized = {row["task_key"]: row for row in auth["authorized_tasks"]}
    transaction_dir = ROOT / "workflow/tasks/giggle_submit_transactions/E40"
    for task in tasks:
        submitter.validate_task(task)
        row = authorized[task["task_key"]]
        fingerprint = submitter.submission_fingerprint(task)
        assert fingerprint == row["submission_fingerprint"]
        assert task["prompt_sha256"] == row["prompt_sha256"]
        planned = ROOT / row["planned_transaction_path"]
        assert planned == submitter.transaction_path(transaction_dir, task)
        if planned.exists():
            raise RuntimeError(f"duplicate transaction exists before authorized post: {planned}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    receipt_dir = OUT_DIR / "submit_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    results, failures = submitter.submit_all(tasks, receipt_dir, transaction_dir, concurrency=2)
    finished = datetime.now(timezone.utc)
    results.sort(key=lambda row: row["task_key"])
    failures.sort(key=lambda row: row["task_key"])

    credit_classification = {
        "status": "NOT_QUERIED_SUCCESS_TASK_IDS_BOUND_NO_PLATFORM_POLL_POLICY",
        "query_count": 0,
        "pay": None,
        "refund": None,
        "net": None,
    }
    ambiguity_resolution = "NO_AMBIGUOUS_SUBMISSIONS"
    if failures:
        # Response loss is the only condition that permits one authoritative ledger read.
        statement_rows = submitter.fetch_pay_statements()
        credit_classification = submitter.reconcile_rows(
            statement_rows,
            start=started - timedelta(seconds=10),
            end=datetime.now(timezone.utc) + timedelta(seconds=10),
            expected_count=len(results) + len(failures),
            event_description="SingleGenerateImage",
            model="gpt-image-2-pro",
        )
        credit_classification["query_count"] = 1
        ambiguity_resolution = submitter.classify_ambiguous_failures(
            failures,
            known_submitted=len(results),
            matched_ledger_rows=int(credit_classification.get("matched_count", 0)),
            transaction_dir=transaction_dir,
        )

    report = {
        "schema": "qingshan.e40.u18.exact_two.one_post_task_id_binding_receipt.v1",
        "recorded_at": now(),
        "status": "PASS_EXACT_TWO_TASK_IDS_BOUND_REMOTE_WAIT_NO_STATUS_POLL" if len(results) == 2 and not failures else "FAIL_CLOSED_RESPONSE_LOSS_CLASSIFIED_NO_RETRY",
        "authorization": {"path": str(AUTH.relative_to(ROOT)), "sha256": sha(AUTH)},
        "manifest": {"path": str(MANIFEST.relative_to(ROOT)), "sha256": sha(MANIFEST)},
        "installed_submitter_sha256": sha(INSTALLED),
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "finished_at": finished.isoformat().replace("+00:00", "Z"),
        "maximum_provider_posts": 2,
        "new_provider_posts": len(results) + len(failures),
        "task_ids_bound": len(results),
        "results": results,
        "failures": failures,
        "credit_classification": credit_classification,
        "ambiguity_resolution": ambiguity_resolution,
        "generation_status_polls": 0,
        "automatic_retry": False,
        "next_action": "Remain in exact-task REMOTE_WAIT. Do not poll generation status in this turn; admit outputs only after exact-task retrieval and U18 output gate plus human review."
    }
    submitter.atomic_json(REPORT, report)
    print(json.dumps({"status": report["status"], "task_ids": [row.get("task_id") for row in results], "failures": len(failures)}, ensure_ascii=False))
    return 0 if report["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
