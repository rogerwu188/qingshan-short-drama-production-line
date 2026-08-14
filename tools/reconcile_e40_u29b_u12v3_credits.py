#!/usr/bin/env python3
"""Authoritatively and idempotently merge U29B Pay64 and U12 V3 Pay5."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "workflow/work_queue.json"
OUT = ROOT / "workflow/releases/E40_U29B_U12V3_AUTHORITATIVE_CREDIT_LEDGER_RECONCILIATION_20260810.json"
TOOLS = Path("/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
U29B_TASK_ID = "6b69682e-cdeb-498d-bed6-8f2554735377"
U12V3_TASK_ID = "562bcf99-ee03-48fa-9a57-f774f75a52d2"
RECONCILIATION_ID = "E40-U29B-PAY64-U12V3-PAY5-DEDUPE-V1"

U29B_SUBMIT = ROOT / "workflow/tasks/E40_U29B_INDEPENDENT_FAST720_EXACTLY_ONE_SUBMIT_20260809.json"
U29B_TX = ROOT / "workflow/tasks/giggle_video_submit_transactions/E40/E40-U29B-CHENJI-ASHUAN-REACTION-V3-INDEPENDENT-FAST720-EXACT-FIRST-FRAME-EXACTLY-ONE-V1__0b5a2b6659cdf1f7.json"
U29B_CLOSEOUT = ROOT / "workflow/releases/E40_U29B_INDEPENDENT_FAST720_EXACTLY_ONE_TERMINAL_QA_FAIL_CLOSEOUT_20260809.json"
U12V3_SUBMIT = ROOT / "workflow/tasks/E40_U12_V3_INTERIOR_DESK_MOUTH_ABSENT_PLATE_SUBMIT_20260810.json"
U12V3_TX = ROOT / "workflow/tasks/giggle_submit_transactions/E40/E40-U12-V3-INTERIOR-DESK-MOUTH-ABSENT-PLATE-V1__e91e29d0b246e82f.json"
U12V3_CLOSEOUT = ROOT / "workflow/releases/E40_U12_V3_INTERIOR_DESK_MOUTH_ABSENT_PLATE_EXACTLY_ONE_CLOSEOUT_20260810.json"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_credit_module() -> Any:
    sys.path.insert(0, str(TOOLS))
    path = TOOLS / "giggle_credit_statements.py"
    spec = importlib.util.spec_from_file_location("installed_giggle_credit_statements_reconcile", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def count_task_id_in_transactions(task_id: str) -> tuple[int, list[str]]:
    paths: list[str] = []
    for directory in (
        ROOT / "workflow/tasks/giggle_video_submit_transactions/E40",
        ROOT / "workflow/tasks/giggle_submit_transactions/E40",
    ):
        for path in directory.glob("*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if str(row.get("task_id") or "") == task_id:
                paths.append(str(path.relative_to(ROOT)))
    return len(paths), sorted(paths)


def main() -> int:
    expected_sha = {
        U29B_SUBMIT: "707c7946b665a66ed0bfe29b90894ef09730acd304975bf8128e13dd9973eb5b",
        U29B_CLOSEOUT: "4af7f9e71ce48aed3aff57a9d4eaba3c197ffa6515cb2edb7847ab580d4314f4",
        U12V3_SUBMIT: "9136ebd9604928c876e1ce10b83bc7f1950fc8512b8cfa3f441ff9fe75651b50",
        U12V3_CLOSEOUT: "94fd2c2e6cdaf456c49f4d7847836e082ac23662cc021e4d79a3f9f4c996855a",
    }
    failures = [f"SHA_MISMATCH:{path}" for path, expected in expected_sha.items() if not path.is_file() or sha256(path) != expected]
    u29b_tx = json.loads(U29B_TX.read_text(encoding="utf-8"))
    u12v3_tx = json.loads(U12V3_TX.read_text(encoding="utf-8"))
    if u29b_tx.get("state") != "SUBMITTED_TASK_ID_BOUND" or u29b_tx.get("task_id") != U29B_TASK_ID:
        failures.append("U29B_TRANSACTION_NOT_BOUND")
    if u12v3_tx.get("state") != "SUBMITTED_TASK_ID_BOUND" or u12v3_tx.get("task_id") != U12V3_TASK_ID:
        failures.append("U12V3_TRANSACTION_NOT_BOUND")
    u29b_count, u29b_paths = count_task_id_in_transactions(U29B_TASK_ID)
    u12v3_count, u12v3_paths = count_task_id_in_transactions(U12V3_TASK_ID)
    if u29b_count != 1:
        failures.append(f"U29B_TRANSACTION_TASK_ID_COUNT_{u29b_count}")
    if u12v3_count != 1:
        failures.append(f"U12V3_TRANSACTION_TASK_ID_COUNT_{u12v3_count}")

    credit = load_credit_module()
    u29b_live = credit.fetch_task_credit_net_by_task_id(U29B_TASK_ID, event_description="SingleGenerateVideo")
    if u29b_live.get("status") != "PASS_CHARGED" or u29b_live.get("net_charged_credits") != 64:
        failures.append("U29B_LIVE_NET_NOT_64")

    u12_submit = json.loads(U12V3_SUBMIT.read_text(encoding="utf-8"))
    u12_credit = u12_submit.get("credit_reconciliation") or {}
    if u12_credit.get("matched_count") != 1 or u12_credit.get("charged_credits") != 5:
        failures.append("U12V3_ISOLATED_IMAGE_PAY_NOT_EXACTLY_5")
    live_rows = credit.fetch_pay_statements(100)
    evidence_row = (u12_credit.get("statement_rows") or [{}])[0]
    image_live_matches = [
        row for row in live_rows
        if row.get("event_type") == evidence_row.get("event_type") == "Pay"
        and row.get("event_description") == evidence_row.get("event_description") == "SingleGenerateImage"
        and row.get("model") == evidence_row.get("model") == "gpt-image-2-pro"
        and row.get("created_at") == evidence_row.get("created_at")
        and str(row.get("credit")) == str(evidence_row.get("credit")) == "-5"
    ]
    if len(image_live_matches) != 1:
        failures.append(f"U12V3_LIVE_ISOLATED_ROW_COUNT_{len(image_live_matches)}")

    queue_before = json.loads(QUEUE.read_text(encoding="utf-8"))
    existing = queue_before.get("latest_e40_u29b_u12v3_credit_reconciliation") or {}
    before_credits = dict(queue_before["e40_credits"])
    already_applied = existing.get("reconciliation_id") == RECONCILIATION_ID
    accepted_pre_states = (
        {"gross_pay": 1197, "refund": 128, "net": 1069, "remaining": 8931, "video_pay": 544},
        {"gross_pay": 1261, "refund": 128, "net": 1133, "remaining": 8867, "video_pay": 608},
    )
    observed_core = {key: before_credits.get(key) for key in accepted_pre_states[0]}
    if observed_core not in accepted_pre_states:
        failures.append(f"UNEXPECTED_LEDGER_PRESTATE:{observed_core}")
    if failures:
        raise SystemExit(";".join(failures))

    target = {
        "gross_pay": 1261,
        "refund": 128,
        "net": 1133,
        "cap": 10000,
        "remaining": 8867,
        "active_remote_image_pay": 0,
        "video_pay": 608,
        "active_remote_video_pay": 0,
    }
    receipt = {
        "schema": "qingshan.e40.cross_lane_authoritative_credit_reconciliation.v1",
        "recorded_at": stamp(),
        "status": "PASS_DEDUPED_AUTHORITATIVE_LEDGER",
        "reconciliation_id": RECONCILIATION_ID,
        "source_cl2x": "Root ordered authoritative cross-lane reconciliation before U12 V4 paid work after concurrent work_queue writes omitted U29B Pay64 while retaining U12 V3 Pay5.",
        "blocked_by": [],
        "dedupe": {
            "u29b_task_id": U29B_TASK_ID,
            "u29b_transaction_occurrences": u29b_count,
            "u29b_transaction_paths": u29b_paths,
            "u12v3_task_id": U12V3_TASK_ID,
            "u12v3_transaction_occurrences": u12v3_count,
            "u12v3_transaction_paths": u12v3_paths,
            "reconciliation_already_applied_before_run": already_applied,
            "rule": "Each bound provider task and isolated authoritative payment row contributes exactly once."
        },
        "authority": {
            "u29b_live_exact_task_ledger": u29b_live,
            "u12v3_live_isolated_statement_match": image_live_matches,
            "source_files": [
                {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in expected_sha
            ]
        },
        "ledger_before": before_credits,
        "ledger_after": target,
        "workaround_executed": "Preserved the already-recorded U12 V3 Pay5 and added only the omitted U29B Pay64/video_pay64; idempotency marker prevents a second addition.",
        "credits": {"u29b": {"pay": 64, "refund": 0, "net": 64}, "u12v3": {"pay": 5, "refund": 0, "net": 5}},
        "next_action": "Use the reconciled E40 ledger as V4 paid-preflight authority; never reapply either task charge."
    }
    atomic_json(OUT, receipt)
    receipt_sha = sha256(OUT)

    for _attempt in range(40):
        before = QUEUE.read_bytes()
        payload = json.loads(before)
        existing = payload.get("latest_e40_u29b_u12v3_credit_reconciliation") or {}
        if existing.get("reconciliation_id") == RECONCILIATION_ID:
            if payload.get("e40_credits") != target:
                raise SystemExit("idempotency marker exists but ledger differs from target")
            print(json.dumps({"status": "ALREADY_APPLIED", "receipt_sha256": receipt_sha, "queue_sha256": hashlib.sha256(before).hexdigest()}))
            return 0
        current_core = {key: payload["e40_credits"].get(key) for key in accepted_pre_states[0]}
        if current_core == accepted_pre_states[0]:
            payload["e40_credits"] = target
        elif current_core != accepted_pre_states[1]:
            raise SystemExit(f"ledger changed to unexpected state during CAS: {current_core}")
        payload["latest_e40_u29b_u12v3_credit_reconciliation"] = {
            "reconciliation_id": RECONCILIATION_ID,
            "path": str(OUT.relative_to(ROOT)),
            "sha256": receipt_sha,
            "status": receipt["status"],
            "u29b_task_id": U29B_TASK_ID,
            "u12v3_task_id": U12V3_TASK_ID,
        }
        payload["updated_at"] = stamp()
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if QUEUE.read_bytes() != before:
            time.sleep(0.05)
            continue
        descriptor, temporary = tempfile.mkstemp(prefix=QUEUE.name + ".", suffix=".part", dir=QUEUE.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if QUEUE.read_bytes() != before:
                os.unlink(temporary)
                time.sleep(0.05)
                continue
            os.replace(temporary, QUEUE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        print(json.dumps({"status": "COMMITTED_CAS", "receipt_sha256": receipt_sha, "queue_sha256": hashlib.sha256(encoded).hexdigest()}))
        return 0
    raise SystemExit("work_queue CAS contention did not settle")


if __name__ == "__main__":
    raise SystemExit(main())
