#!/usr/bin/env python3
"""Fresh paid readiness and exactly-one authorization for E40 U05 V3."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path("/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
SUBMITTER = TOOLS / "submit_giggle_video_manifest_v2.py"
SOURCE = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u05_v3_fast720_admitted_frame_v1/E40_U05_V3_FAST720_NO_SUBMIT_MANIFEST_V1.json"
PRECHECK = ROOT / "qa/e40_preproduction_20260814/u05_v3_fast720_no_submit_package_v1/E40_U05_V3_INSTALLED_PRECHECK_ONLY_V1.json"
AUTHORIZED = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u05_v3_fast720_admitted_frame_v1/E40_U05_V3_FAST720_AUTHORIZED_EXACTLY_ONCE_MANIFEST_V1.json"
OUT = ROOT / "qa/e40_preproduction_20260814/u05_v3_fast720_no_submit_package_v1/E40_U05_V3_FAST720_PAID_READINESS_V1.json"
AUTH = ROOT / "workflow/approvals/E40_U05_V3_FAST720_EXACTLY_ONCE_AUTHORIZATION_20260814.json"
PRICE_SOURCE_TASK = "b68d8003-30d5-457e-9e85-55738290555f"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def load_module(name: str, path: Path):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    submitter = load_module("e40_u05_installed_submitter", SUBMITTER)
    credit = load_module("e40_u05_credit_ledger", TOOLS / "giggle_credit_statements.py")
    submitter.ROOT = ROOT
    credit.ROOT = ROOT
    manifest = json.loads(SOURCE.read_text(encoding="utf-8"))
    precheck = json.loads(PRECHECK.read_text(encoding="utf-8"))
    task = manifest["tasks"][0]
    fingerprint = submitter.task_fingerprint(task)
    transport = submitter.transport_fingerprint(task)
    transaction_dir = ROOT / "workflow/tasks/giggle_video_submit_transactions/E40"
    expected_transaction = transaction_dir / f"{task['task_key']}__{fingerprint[:16]}.json"

    # One read-only exact-task ledger query; no generation endpoint and no polling.
    price = credit.fetch_task_credit_net_by_task_id(PRICE_SOURCE_TASK, event_description="SingleGenerateVideo")
    rows = price.get("statement_rows") or []
    same_model = len(rows) == 1 and rows[0].get("model") == "seedance-2.0-fast"
    price_per_second = int(price.get("net_charged_credits", 0)) // 4 if price.get("status") == "PASS_CHARGED" else None

    matches = {"task_key": 0, "submission_fingerprint": 0, "transport_fingerprint": 0}
    for path in transaction_dir.glob("*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        matches["task_key"] += row.get("task_key") == task["task_key"]
        matches["submission_fingerprint"] += row.get("submission_fingerprint") == fingerprint
        matches["transport_fingerprint"] += row.get("transport_fingerprint") == transport
    ledger = json.loads((ROOT / "workflow/work_queue.json").read_text(encoding="utf-8"))["e40_credits"]
    projected_charge = 4 * 16
    projected_net = int(ledger["net"]) + projected_charge
    checks = {
        "installed_version_0_2_49": Path("/Users/rogerwu/.local/share/backlotos/source/version").read_text(encoding="utf-8").strip() == "0.2.49",
        "api_key_present": bool(os.environ.get("GIGGLE_API_KEY", "").strip()),
        "source_manifest_fast_only": manifest.get("allowed_video_models") == ["seedance-2.0-fast"] and task.get("model") == "seedance-2.0-fast",
        "source_manifest_no_submit": manifest.get("submission_policy", {}).get("provider_post_allowed") is False,
        "installed_precheck_pass_zero_submit": precheck.get("status") == "PASS" and precheck.get("submitted") == 0 and precheck.get("precheck_pass") == 1,
        "fresh_same_model_ledger_pass": price.get("status") == "PASS_CHARGED" and same_model,
        "fresh_price_16_per_second": price_per_second == 16 and price.get("net_charged_credits") == 64,
        "transaction_path_fresh": not expected_transaction.exists(),
        "transaction_collision_zero": all(value == 0 for value in matches.values()),
        "projected_net_within_cap": projected_net <= int(ledger["cap"]),
        "exactly_one_generation": task.get("generating_count") == 1 and task.get("duration_seconds") == 4,
    }
    recorded = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report = {
        "schema": "qingshan.e40.u05.v3.fast720_paid_readiness.v1",
        "recorded_at": recorded,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "source_manifest": str(SOURCE.relative_to(ROOT)),
        "source_manifest_sha256": sha256(SOURCE),
        "installed_precheck": str(PRECHECK.relative_to(ROOT)),
        "installed_precheck_sha256": sha256(PRECHECK),
        "task_key": task["task_key"],
        "task_fingerprint": fingerprint,
        "transport_fingerprint": transport,
        "expected_transaction_path": str(expected_transaction.relative_to(ROOT)),
        "checks": checks,
        "collision_scan": matches,
        "fresh_authoritative_same_model_price": price,
        "pricing": {"credits_per_second": price_per_second, "projected_charge": projected_charge, "ledger_before": ledger, "projected_net": projected_net, "projected_remaining": int(ledger["cap"]) - projected_net},
        "provider_posts": 0,
        "provider_queries": 1,
        "credits": 0,
        "policy": "One provider POST may follow only from the separately persisted authorized manifest and only through the durable transaction-before-POST submitter.",
    }
    atomic_json(OUT, report)
    if report["status"] != "PASS":
        print(json.dumps({"status": "FAIL", "checks": checks}, ensure_ascii=False))
        return 2

    authorized = json.loads(SOURCE.read_text(encoding="utf-8"))
    authorized["schema"] = "qingshan.e40.u05.v3.fast720_authorized_exactly_once_manifest.v1"
    authorized["status"] = "AUTHORIZED_EXACTLY_ONCE_PENDING_INSTALLED_PRECHECK"
    authorized["authorization"] = True
    authorized["maximum_new_submissions"] = 1
    authorized["submission_policy"].update({
        "precheck_only": False,
        "paid_submission_allowed": True,
        "provider_post_allowed": True,
        "durable_transaction_allowed": True,
        "maximum_new_submissions": 1,
    })
    authorized["blocked_by"] = "AUTHORIZED_MANIFEST_INSTALLED_PRECHECK_NOT_YET_PASSED"
    authorized["tasks"][0]["submission_authorization"] = {
        "precheck_only": False,
        "authorized": True,
        "paid_submission_allowed": True,
        "transaction_creation_allowed": True,
        "maximum_new_submissions": 1,
        "paid_readiness_path": str(OUT.relative_to(ROOT)),
        "paid_readiness_sha256": sha256(OUT),
    }
    atomic_json(AUTHORIZED, authorized)
    atomic_json(AUTH, {
        "schema": "qingshan.e40.u05.v3.fast720_exactly_once_authorization.v1",
        "recorded_at": recorded,
        "status": "AUTHORIZE_EXACTLY_ONE_FAST720_PROVIDER_POST_AFTER_AUTHORIZED_MANIFEST_PRECHECK_PASS",
        "authority": "Roger standing instruction: 你应该自己选择，以后不需要问我; E40 seedance-2.0-fast-only production authorization",
        "task_key": task["task_key"],
        "task_fingerprint": fingerprint,
        "transport_fingerprint": transport,
        "source_manifest_sha256": sha256(SOURCE),
        "paid_readiness_sha256": sha256(OUT),
        "authorized_manifest": str(AUTHORIZED.relative_to(ROOT)),
        "authorized_manifest_sha256": sha256(AUTHORIZED),
        "maximum_new_submissions": 1,
        "required_transaction_before_post": True,
        "task_id_binding_immediate": True,
        "unknown_response_requires_authoritative_pay_refund_classification_before_future_action": True,
        "model": "seedance-2.0-fast",
        "forbidden_models": ["seedance-2.0-pro", "seedance-2.0-mini", "seedance-2.0"],
    })
    print(json.dumps({"status": "PASS_AUTHORIZED_MANIFEST_WRITTEN", "task_fingerprint": fingerprint, "transport_fingerprint": transport, "authorized_manifest_sha256": sha256(AUTHORIZED), "projected_charge": projected_charge}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
