#!/usr/bin/env python3
"""Read-only, evidence-bound certification for the reconstructed E40 work queue.

The tool never writes ``workflow/work_queue.json``.  ``--out`` may be used to
atomically materialize only the certification receipt named by the caller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from tools.task_lane_global_wait_gate import audit_scheduler_state
except ModuleNotFoundError:  # Direct execution from the tools directory.
    from task_lane_global_wait_gate import audit_scheduler_state


BASELINE_REL = "workflow/releases/E40_PRODUCTION_STATE_SOURCE_OF_TRUTH_CONSISTENCY_AUDIT_20260809.json"
SCRIPT_REL = "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
MANIFEST_REL = "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
QUEUE_REL = "workflow/work_queue.json"
SCHEDULER_REL = "workflow/production_line/E40_TASK_LANES_V1.json"
CERTIFICATION_REL = "workflow/releases/E40_WORK_QUEUE_CERTIFICATION_V2_DYNAMIC_LIVENESS_POLICY_20260810.json"

EXPECTED_SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
EXPECTED_MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"

POST_BASELINE_AUTHORITIES = (
    {
        "task_key": "E40-U29A-BAILI-JADE-RETRACT-V3-FAST720-EXACT-FIRST-FRAME-V2",
        "transaction": "workflow/tasks/giggle_video_submit_transactions/E40/E40-U29A-BAILI-JADE-RETRACT-V3-FAST720-EXACT-FIRST-FRAME-V2__49a00650e03cbd3a.json",
        "evidence": "workflow/releases/E40_U29A_FAST720_EXACTLY_ONE_TERMINAL_QA_FAIL_CLOSEOUT_20260809.json",
        "task_id_path": "execution.remote_task_id",
        "pay_path": "execution.pay",
        "refund_path": "execution.refund",
        "net_path": "execution.net",
        "status_path": "status",
        "terminal_tokens": ("TERMINAL", "COMPLETED"),
        "media": "video",
    },
    {
        "task_key": "E40-U29A-BAILI-JADE-RETRACT-V3-FAST720-EXACT-FIRST-FRAME-V3-NO-SUBMIT",
        "transaction": "workflow/tasks/giggle_video_submit_transactions/E40/E40-U29A-BAILI-JADE-RETRACT-V3-FAST720-EXACT-FIRST-FRAME-V3-NO-SUBMIT__7f399aa97ed52dd7.json",
        "evidence": "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/next_generatable_unit_readiness_audit_v2/harvest_v3/E40_U29A_V3_EXACTLY_ONE_HARVEST_QA_RECEIPT.json",
        "task_id_path": "execution.remote_task_id",
        "pay_path": "transaction.pay",
        "refund_path": "transaction.refund",
        "net_path": "transaction.net",
        "status_path": "status",
        "terminal_tokens": ("COMPLETED", "QUARANTINED"),
        "media": "video",
    },
    {
        "task_key": "E40-U12-DIA010-EXACTLY-ONE-TTS-V1",
        "transaction": "workflow/tasks/giggle_audio_submit_transactions/E40/E40-U12-DIA010-EXACTLY-ONE-TTS-V1.json",
        "evidence": "workflow/tasks/giggle_audio_submit_transactions/E40/E40-U12-DIA010-EXACTLY-ONE-TTS-V1.json",
        "task_id_path": "task_id",
        "pay_path": "credit.paid_credits",
        "refund_path": "credit.refunded_credits",
        "net_path": "credit.net_charged_credits",
        "status_path": "state",
        "terminal_tokens": ("TERMINAL", "COMPLETED"),
        "media": "audio",
    },
    {
        "task_key": "E40-U12-MOUTH-NONVISIBLE-FAST720-SILENT-VISUAL-EXACTLY-ONE-V1",
        "transaction": "workflow/tasks/giggle_video_submit_transactions/E40/E40-U12-MOUTH-NONVISIBLE-FAST720-SILENT-VISUAL-EXACTLY-ONE-V1__684d380a3960979f.json",
        "evidence": "workflow/tasks/giggle_video_submit_transactions/E40/E40-U12-MOUTH-NONVISIBLE-FAST720-SILENT-VISUAL-EXACTLY-ONE-V1__684d380a3960979f.json",
        "task_id_path": "task_id",
        "pay_path": "credit.pay",
        "refund_path": "credit.refund",
        "net_path": "credit.net",
        "status_path": "state",
        "terminal_tokens": ("TERMINAL", "COMPLETED"),
        "media": "video",
    },
    {
        "task_key": "E40-U29B-CHENJI-ASHUAN-REACTION-V3-INDEPENDENT-FAST720-EXACT-FIRST-FRAME-EXACTLY-ONE-V1",
        "transaction": "workflow/tasks/giggle_video_submit_transactions/E40/E40-U29B-CHENJI-ASHUAN-REACTION-V3-INDEPENDENT-FAST720-EXACT-FIRST-FRAME-EXACTLY-ONE-V1__0b5a2b6659cdf1f7.json",
        "evidence": "workflow/releases/E40_U29B_INDEPENDENT_FAST720_EXACTLY_ONE_TERMINAL_QA_FAIL_CLOSEOUT_20260809.json",
        "task_id_path": "execution.provider_task_id",
        "pay_path": "credits.pay",
        "refund_path": "credits.refund",
        "net_path": "credits.net",
        "status_path": "status",
        "terminal_tokens": ("TERMINAL", "COMPLETED"),
        "media": "video",
    },
    {
        "task_key": "E40-U12-V3-INTERIOR-DESK-MOUTH-ABSENT-PLATE-V1",
        "transaction": "workflow/tasks/giggle_submit_transactions/E40/E40-U12-V3-INTERIOR-DESK-MOUTH-ABSENT-PLATE-V1__e91e29d0b246e82f.json",
        "evidence": "workflow/releases/E40_U12_V3_INTERIOR_DESK_MOUTH_ABSENT_PLATE_EXACTLY_ONE_CLOSEOUT_20260810.json",
        "task_id_path": "runtime_and_exactly_once.task_id",
        "pay_path": "credits.this_task.gross_pay",
        "refund_path": "credits.this_task.refund",
        "net_path": "credits.this_task.net",
        "status_path": "status",
        "terminal_tokens": ("PASS", "ADMITTED"),
        "media": "image",
    },
    {
        "task_key": "E40-U12-V4-NEW-PLATE-MOUTH-ABSENT-FAST720-SILENT-EXACTLY-ONE-V1",
        "transaction": "workflow/tasks/giggle_video_submit_transactions/E40/E40-U12-V4-NEW-PLATE-MOUTH-ABSENT-FAST720-SILENT-EXACTLY-ONE-V1__32585bf2588d3fd3.json",
        "evidence": "workflow/releases/E40_U12_V4_NEW_PLATE_FAST720_SILENT_EXACTLY_ONE_TERMINAL_QA_FAIL_CLOSEOUT_20260810.json",
        "task_id_path": "execution.task_id",
        "pay_path": "credits.pay",
        "refund_path": "credits.refund",
        "net_path": "credits.net",
        "status_path": "status",
        "terminal_tokens": ("TERMINAL", "COMPLETED"),
        "media": "video",
    },
)

VIDEO_CLASS_AUTHORITIES = (
    # The two early charged video batches already have ordinary credit statements.
    ("workflow/tasks/E40_U01_FAST_VIDEO_R2_SUBMIT_20260809_credit_statement.json", "charged_credits", 128),
    ("workflow/tasks/E40_U03_FAST720_VIDEO_SUBMIT_20260809_credit_statement.json", "charged_credits", 80),
    # Fully refunded R1 still contributes to gross and refund.
    ("workflow/tasks/giggle_video_submit_transactions/E40/E40-U01-FAST-VIDEO-R1__9599ea314ce59b30.json", "paid_credits", 128),
    ("workflow/tasks/giggle_video_submit_transactions/E40/E40-U03-FAST720-NATIVE-START-FRAME-R2__e36bfe3a164e87f2.json", "credit_closure.paid_credits", 64),
    ("workflow/tasks/E40_U27_FAST720_SILENT_VISUAL_SUBMIT_20260809.json", "credit_reconciliation.charged_credits", 112),
    ("workflow/tasks/E40_U28A_FAST720_EXACTLY_ONE_VIDEO_SUBMIT_20260809.json", "credit_reconciliation.charged_credits", 64),
    ("workflow/releases/E40_U29A_FAST720_EXACTLY_ONE_TERMINAL_QA_FAIL_CLOSEOUT_20260809.json", "execution.pay", 64),
    ("workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/next_generatable_unit_readiness_audit_v2/harvest_v3/E40_U29A_V3_EXACTLY_ONE_HARVEST_QA_RECEIPT.json", "transaction.pay", 64),
    ("workflow/tasks/giggle_video_submit_transactions/E40/E40-U12-MOUTH-NONVISIBLE-FAST720-SILENT-VISUAL-EXACTLY-ONE-V1__684d380a3960979f.json", "credit.pay", 112),
    ("workflow/releases/E40_U29B_INDEPENDENT_FAST720_EXACTLY_ONE_TERMINAL_QA_FAIL_CLOSEOUT_20260809.json", "credits.pay", 64),
    ("workflow/releases/E40_U12_V4_NEW_PLATE_FAST720_SILENT_EXACTLY_ONE_TERMINAL_QA_FAIL_CLOSEOUT_20260810.json", "credits.pay", 112),
)


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_json_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    """Read one immutable byte snapshot and derive both JSON and SHA from it."""
    payload = path.read_bytes()
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value, hashlib.sha256(payload).hexdigest()


def parse_utc(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {value}")
    return parsed.astimezone(timezone.utc)


def nested(value: dict[str, Any], dotted: str) -> Any:
    current: Any = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted)
        current = current[part]
    return current


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def transaction_inventory(root: Path) -> dict[str, Any]:
    groups = {
        "image": root / "workflow/tasks/giggle_submit_transactions/E40",
        "video": root / "workflow/tasks/giggle_video_submit_transactions/E40",
        "audio": root / "workflow/tasks/giggle_audio_submit_transactions/E40",
    }
    entries: list[dict[str, Any]] = []
    listing_lines: list[str] = []
    for media, directory in groups.items():
        for path in sorted(directory.glob("*.json")):
            data = read_json(path)
            task_key = data.get("task_key") or data.get("transaction_key")
            intent = data.get("intent_recorded_at") or data.get("intent_persisted_at")
            entry = {
                "media": media,
                "path": str(path.relative_to(root)),
                "sha256": sha256_path(path),
                "task_key": task_key,
                "task_id": data.get("task_id"),
                "state": data.get("state"),
                "intent_at": intent,
                "ledger_reconciled_at": data.get("ledger_reconciled_at"),
                "batch_ledger_pay_rows": int(data.get("batch_ledger_pay_rows") or 0),
                "batch_unmapped_pay_rows": data.get("batch_unmapped_pay_rows"),
                "model": data.get("model") or nested(data, "request.engine") if media == "audio" else data.get("model"),
            }
            entries.append(entry)
            listing_lines.append(f"{entry['path']}\0{entry['sha256']}\n")
    unbound = [entry for entry in entries if not entry["task_id"]]
    unbound_reconciliation_failures = [
        entry["path"]
        for entry in unbound
        if entry["state"] not in {"VERIFIED_ZERO_RETRYABLE", "NOT_CHARGED_RETRYABLE"}
        or not entry["ledger_reconciled_at"]
        or (
            entry["batch_ledger_pay_rows"] != 0
            and entry["batch_unmapped_pay_rows"] != 0
        )
    ]
    return {
        "entries": entries,
        "file_count": len(entries),
        "task_bound_count": sum(bool(entry["task_id"]) for entry in entries),
        "unbound_count": sum(not bool(entry["task_id"]) for entry in entries),
        "unbound_zero_or_not_charged_reconciled": not unbound_reconciliation_failures,
        "unbound_reconciliation_failures": unbound_reconciliation_failures,
        "listing_sha256": hashlib.sha256("".join(listing_lines).encode("utf-8")).hexdigest(),
        "counts_by_media": {
            media: sum(entry["media"] == media for entry in entries)
            for media in ("image", "video", "audio")
        },
    }


def post_baseline_reconciliation(root: Path, inventory: dict[str, Any], cutoff: str) -> dict[str, Any]:
    post_entries = [entry for entry in inventory["entries"] if str(entry.get("intent_at") or "") > cutoff]
    by_key = {entry["task_key"]: entry for entry in post_entries}
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for authority in POST_BASELINE_AUTHORITIES:
        key = authority["task_key"]
        entry = by_key.get(key)
        txn_path = root / authority["transaction"]
        evidence_path = root / authority["evidence"]
        if entry is None:
            failures.append(f"POST_BASELINE_TRANSACTION_MISSING:{key}")
            continue
        if entry["path"] != authority["transaction"]:
            failures.append(f"POST_BASELINE_TRANSACTION_PATH_MISMATCH:{key}")
        txn = read_json(txn_path)
        evidence = read_json(evidence_path)
        task_id = txn.get("task_id")
        evidence_task_id = nested(evidence, authority["task_id_path"])
        status = str(nested(evidence, authority["status_path"]))
        terminal = all(token in status for token in authority["terminal_tokens"])
        pay = int(nested(evidence, authority["pay_path"]))
        refund = int(nested(evidence, authority["refund_path"]))
        net = int(nested(evidence, authority["net_path"]))
        if task_id != evidence_task_id:
            failures.append(f"POST_BASELINE_TASK_ID_MISMATCH:{key}")
        if pay - refund != net:
            failures.append(f"POST_BASELINE_CREDIT_ARITHMETIC:{key}")
        if not terminal:
            failures.append(f"POST_BASELINE_NOT_TERMINAL:{key}")
        rows.append(
            {
                "task_key": key,
                "task_id": task_id,
                "media": authority["media"],
                "transaction_path": authority["transaction"],
                "transaction_sha256": sha256_path(txn_path),
                "evidence_path": authority["evidence"],
                "evidence_sha256": sha256_path(evidence_path),
                "status": status,
                "terminal": terminal,
                "pay": pay,
                "refund": refund,
                "net": net,
            }
        )
    expected_keys = {authority["task_key"] for authority in POST_BASELINE_AUTHORITIES}
    extra = sorted(set(by_key) - expected_keys)
    missing = sorted(expected_keys - set(by_key))
    if extra:
        failures.append(f"UNCLASSIFIED_POST_BASELINE_TRANSACTIONS:{','.join(extra)}")
    if missing:
        failures.append(f"MISSING_POST_BASELINE_TRANSACTIONS:{','.join(missing)}")
    return {
        "cutoff": cutoff,
        "transaction_count": len(post_entries),
        "expected_transaction_count": len(POST_BASELINE_AUTHORITIES),
        "rows": rows,
        "pay": sum(row["pay"] for row in rows),
        "refund": sum(row["refund"] for row in rows),
        "net": sum(row["net"] for row in rows),
        "all_terminal": all(row["terminal"] for row in rows) and not failures,
        "failures": failures,
    }


def class_credit_recompute(root: Path) -> dict[str, Any]:
    image_pay = 0
    batch_rows: list[dict[str, Any]] = []
    for path in sorted((root / "workflow/tasks").glob("E40*credit_statement.json")):
        data = read_json(path)
        event = data.get("event_description")
        charged = int(data.get("charged_credits") or 0)
        if int(data.get("invalid_credit_rows") or 0) != 0:
            raise ValueError(f"invalid credit rows in {path}")
        if event == "SingleGenerateImage":
            image_pay += charged
        batch_rows.append(
            {
                "path": str(path.relative_to(root)),
                "sha256": sha256_path(path),
                "event_description": event,
                "charged_credits": charged,
                "matched_count": data.get("matched_count"),
                "status": data.get("status"),
            }
        )
    video_rows: list[dict[str, Any]] = []
    video_pay = 0
    for rel, dotted, expected in VIDEO_CLASS_AUTHORITIES:
        path = root / rel
        data = read_json(path)
        observed = int(nested(data, dotted))
        if observed != expected:
            raise ValueError(f"video credit authority mismatch {rel}: {observed} != {expected}")
        video_pay += observed
        video_rows.append({"path": rel, "sha256": sha256_path(path), "field": dotted, "pay": observed})
    audio_path = root / "workflow/tasks/giggle_audio_submit_transactions/E40/E40-U12-DIA010-EXACTLY-ONE-TTS-V1.json"
    audio = read_json(audio_path)
    audio_pay = int(nested(audio, "credit.paid_credits"))
    refund = int(
        nested(
            read_json(root / "workflow/tasks/giggle_video_submit_transactions/E40/E40-U01-FAST-VIDEO-R1__9599ea314ce59b30.json"),
            "refunded_credits",
        )
    )
    gross = image_pay + video_pay + audio_pay
    return {
        "gross_pay": gross,
        "refund": refund,
        "net": gross - refund,
        "image_pay": image_pay,
        "video_pay": video_pay,
        "audio_pay": audio_pay,
        "batch_credit_statement_count": len(batch_rows),
        "batch_credit_statements": batch_rows,
        "video_authorities": video_rows,
        "audio_authority": {"path": str(audio_path.relative_to(root)), "sha256": sha256_path(audio_path)},
    }


def field_result(field: str, observed: Any, expected: Any, evidence: Iterable[str]) -> dict[str, Any]:
    return {
        "field": field,
        "status": "PASS" if observed == expected else "FAIL",
        "observed": observed,
        "expected": expected,
        "evidence": list(evidence),
    }


def derive_paid_safety(
    *,
    stable_fields_closed: bool,
    dual_credit_method_agrees: bool,
    active_remote_handle_count: int,
    active_paid_authorization_count: int,
    transactions_closed: bool,
    scheduler_hard_gates_pass: bool,
) -> bool:
    """Derive safety without treating unrelated zero-cost work as a blocker."""
    return bool(
        stable_fields_closed
        and dual_credit_method_agrees
        and active_remote_handle_count == 0
        and active_paid_authorization_count == 0
        and transactions_closed
        and scheduler_hard_gates_pass
    )


def build_certification(root: Path, observed_at: str | None = None) -> dict[str, Any]:
    observed_at = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    queue_path = root / QUEUE_REL
    scheduler_path = root / SCHEDULER_REL
    baseline_path = root / BASELINE_REL
    queue, queue_sha = read_json_snapshot(queue_path)
    scheduler, scheduler_sha = read_json_snapshot(scheduler_path)
    baseline, baseline_sha = read_json_snapshot(baseline_path)
    inventory = transaction_inventory(root)
    cutoff = str(baseline["recorded_at"])
    post = post_baseline_reconciliation(root, inventory, cutoff)
    class_credits = class_credit_recompute(root)

    base_credits = baseline["credits"]
    credit_recomputed = {
        "gross_pay": int(base_credits["gross_pay"]) + post["pay"],
        "refund": int(base_credits["refund"]) + post["refund"],
        "net": int(base_credits["net"]) + post["net"],
        "cap": int(base_credits["cap"]),
    }
    credit_recomputed["remaining"] = credit_recomputed["cap"] - credit_recomputed["net"]
    dual_credit_method_agrees = all(
        credit_recomputed[key] == class_credits[key] for key in ("gross_pay", "refund", "net")
    )

    tasks = scheduler.get("tasks") or []
    active = [task for task in tasks if task.get("state") in {"READY", "RUNNING", "QA", "REMOTE_WAIT"}]
    active_paid_authorizations = [
        task.get("task_id")
        for task in active
        if task.get("authorization") is True
        and task.get("provider_post_allowed") is True
        and int(task.get("maximum_new_submissions") or 0) > 0
    ]
    remote_provider_handles = [
        task.get("task_id")
        for task in active
        if task.get("state") == "REMOTE_WAIT" and bool(task.get("remote_task_id"))
    ]
    active_remote_handle_count = len(remote_provider_handles)

    # Current U29C authority supersedes the rejected V1 candidate stored in the reconstruction.
    u29c_gate_rel = "qa/e40_preproduction_20260808/u29c_v5_two_identity_depth_layer_v1/E40_U29C_V5_EXACT_START_FRAME_ADMISSION_GATE_V2.json"
    u29c_gate_path = root / u29c_gate_rel
    u29c_gate = read_json(u29c_gate_path)
    u29c_candidate_path = str(nested(u29c_gate, "admitted_candidate.path"))
    u29c_candidate_sha = str(nested(u29c_gate, "admitted_candidate.sha256"))

    u29b_readiness_rel = "workflow/releases/E40_U29A_V4_U29B_FINAL_CHAIN_READINESS_NO_ASSEMBLY_RECEIPT_20260810.json"
    u29b_readiness_path = root / u29b_readiness_rel
    u29b_readiness = read_json(u29b_readiness_path)

    scheduler_gate = audit_scheduler_state(scheduler, observed_at=parse_utc(observed_at))
    scheduler_heartbeat = scheduler.get("heartbeat_integration") or {}
    scheduler_episode_terminal = scheduler_heartbeat.get("episode_terminal") is True
    queue_scheduler = queue.get("task_lane_scheduler") or {}
    scheduler_sha_drift = queue_scheduler.get("observed_sha256") != scheduler_sha
    dynamic_warnings = []
    if scheduler_sha_drift:
        dynamic_warnings.append(
            {
                "code": "DYNAMIC_SCHEDULER_SHA_DRIFT_REQUIRES_PAID_PREFLIGHT_REOBSERVATION",
                "severity": "WARNING",
                "execution_critical_field_failure": False,
                "stored_sha256": queue_scheduler.get("observed_sha256"),
                "observed_sha256": scheduler_sha,
            }
        )

    queue_credits = queue.get("e40_credits") or {}
    stable_certifications = [
        field_result("schema", queue.get("schema"), "qingshan.producer.work_queue.v2", [QUEUE_REL]),
        field_result("active_episode", queue.get("active_episode"), "E40", [SCRIPT_REL, MANIFEST_REL]),
        field_result("canonical.script_sha256", nested(queue, "canonical.script_sha256"), sha256_path(root / SCRIPT_REL), [SCRIPT_REL]),
        field_result("canonical.manifest_sha256", nested(queue, "canonical.manifest_sha256"), sha256_path(root / MANIFEST_REL), [MANIFEST_REL]),
        field_result("rules.only_video_model", nested(queue, "rules.only_video_model"), "seedance-2.0-fast", [u29c_gate_rel]),
        field_result("rules.only_video_resolution", nested(queue, "rules.only_video_resolution"), "720p", [u29c_gate_rel]),
        field_result(
            "rules.forbidden_video_models",
            sorted(nested(queue, "rules.forbidden_video_models")),
            sorted(["seedance-2.0-pro", "seedance-2.0-mini", "seedance-2.0"]),
            [u29c_gate_rel],
        ),
        field_result("e40_credits.gross_pay", queue_credits.get("gross_pay"), credit_recomputed["gross_pay"], [BASELINE_REL, "post_baseline_authorities"]),
        field_result("e40_credits.refund", queue_credits.get("refund"), credit_recomputed["refund"], [BASELINE_REL, "post_baseline_authorities"]),
        field_result("e40_credits.net", queue_credits.get("net"), credit_recomputed["net"], [BASELINE_REL, "post_baseline_authorities"]),
        field_result("e40_credits.cap", queue_credits.get("cap"), credit_recomputed["cap"], [BASELINE_REL]),
        field_result("e40_credits.remaining", queue_credits.get("remaining"), credit_recomputed["remaining"], [BASELINE_REL, "post_baseline_authorities"]),
        field_result("e40_credits.active_remote_image_pay", queue_credits.get("active_remote_image_pay"), 0, [BASELINE_REL, SCHEDULER_REL]),
        field_result("e40_credits.active_remote_video_pay", queue_credits.get("active_remote_video_pay"), 0, [BASELINE_REL, SCHEDULER_REL]),
        field_result("e40_credits.image_pay", queue_credits.get("image_pay"), class_credits["image_pay"], ["image_credit_statements"]),
        field_result("e40_credits.video_pay", queue_credits.get("video_pay"), class_credits["video_pay"], ["video_class_authorities"]),
        field_result("e40_credits.audio_pay", queue_credits.get("audio_pay"), class_credits["audio_pay"], ["audio_task_authority"]),
        field_result("real_active_handle_count", queue.get("real_active_handle_count"), active_remote_handle_count, [BASELINE_REL, SCHEDULER_REL, "post_baseline_authorities"]),
        field_result("task_lane_scheduler.path", queue_scheduler.get("path"), SCHEDULER_REL, [QUEUE_REL, SCHEDULER_REL]),
        field_result(
            "task_lane_scheduler.episode_terminal",
            queue_scheduler.get("episode_terminal"),
            scheduler_episode_terminal,
            [QUEUE_REL, SCHEDULER_REL],
        ),
        field_result("latest_e40_u29c.path", nested(queue, "latest_e40_u29c_local_depth_layer_candidate.path"), u29c_candidate_path, [u29c_gate_rel]),
        field_result("latest_e40_u29c.sha256", nested(queue, "latest_e40_u29c_local_depth_layer_candidate.sha256"), u29c_candidate_sha, [u29c_gate_rel]),
        field_result("latest_e40_u29c.status", nested(queue, "latest_e40_u29c_local_depth_layer_candidate.status"), str(u29c_gate.get("status")), [u29c_gate_rel]),
        field_result(
            "latest_e40_u29b.readiness_receipt",
            nested(queue, "latest_e40_u29b_independent_material_admission_final_chain_hold.path"),
            u29b_readiness_rel,
            [u29b_readiness_rel],
        ),
        field_result(
            "latest_e40_u29b.final_chain_slot_enabled",
            nested(queue, "latest_e40_u29b_independent_material_admission_final_chain_hold.final_chain_slot_enabled"),
            bool(nested(u29b_readiness, "readiness_binding.final_chain_slot_enabled")),
            [u29b_readiness_rel],
        ),
        field_result("work_queue_recovery.release_actions_allowed", nested(queue, "work_queue_recovery.release_actions_allowed"), False, [QUEUE_REL]),
    ]
    stable_failures = [item for item in stable_certifications if item["status"] == "FAIL"]
    transactions_closed = bool(
        post["all_terminal"]
        and not post["failures"]
        and inventory["task_bound_count"] + inventory["unbound_count"] == inventory["file_count"]
        and inventory["unbound_zero_or_not_charged_reconciled"]
    )
    scheduler_hard_gates_pass = bool(
        queue_scheduler.get("path") == SCHEDULER_REL
        and queue_scheduler.get("episode_terminal") == scheduler_episode_terminal
        and scheduler_gate["status"] == "PASS"
        and scheduler_gate["heartbeat_return_allowed"] is True
    )
    runtime_gate_failures: list[dict[str, Any]] = []
    if not dual_credit_method_agrees:
        runtime_gate_failures.append({"field": "credit_dual_method_agreement", "status": "FAIL"})
    if not transactions_closed:
        runtime_gate_failures.append(
            {
                "field": "transaction_reconciliation_closure",
                "status": "FAIL",
                "post_baseline_failures": post["failures"],
                "unbound_reconciliation_failures": inventory["unbound_reconciliation_failures"],
            }
        )
    if active_remote_handle_count:
        runtime_gate_failures.append(
            {"field": "active_remote_handles", "status": "FAIL", "task_ids": remote_provider_handles}
        )
    if active_paid_authorizations:
        runtime_gate_failures.append({"field": "active_paid_authorizations", "status": "FAIL", "task_ids": active_paid_authorizations})
    if not scheduler_hard_gates_pass:
        runtime_gate_failures.append(
            {
                "field": "scheduler_path_episode_terminal_global_gate",
                "status": "FAIL",
                "global_gate_status": scheduler_gate["status"],
                "heartbeat_return_allowed": scheduler_gate["heartbeat_return_allowed"],
                "failures": scheduler_gate["failures"],
            }
        )

    current_blockers = [
        {
            "task_id": task.get("task_id"),
            "state": task.get("state"),
            "blocked_by": task.get("blocked_by"),
            "provider_post_allowed": task.get("provider_post_allowed") is True,
            "authorization": task.get("authorization") is True,
            "maximum_new_submissions": int(task.get("maximum_new_submissions") or 0),
        }
        for task in active
    ]
    stable_fields_closed = not stable_failures
    paid_actions_allowed = derive_paid_safety(
        stable_fields_closed=stable_fields_closed,
        dual_credit_method_agrees=dual_credit_method_agrees,
        active_remote_handle_count=active_remote_handle_count,
        active_paid_authorization_count=len(active_paid_authorizations),
        transactions_closed=transactions_closed,
        scheduler_hard_gates_pass=scheduler_hard_gates_pass,
    )
    queue_recovery_paid_flag = nested(queue, "work_queue_recovery.paid_actions_allowed") is True
    recovery_paid_flag_matches_derived = queue_recovery_paid_flag == paid_actions_allowed

    patchable_stable_fields = {
        "e40_credits.image_pay",
        "e40_credits.video_pay",
        "e40_credits.audio_pay",
        "latest_e40_u29c.path",
        "latest_e40_u29c.sha256",
        "latest_e40_u29c.status",
        "latest_e40_u29b.readiness_receipt",
    }
    non_patchable_stable_failures = [
        row for row in stable_failures if row["field"] not in patchable_stable_fields
    ]
    prospective_phase1_stable_fields_closed = not non_patchable_stable_failures
    phase2_candidate_paid_safety = derive_paid_safety(
        stable_fields_closed=prospective_phase1_stable_fields_closed,
        dual_credit_method_agrees=dual_credit_method_agrees,
        active_remote_handle_count=active_remote_handle_count,
        active_paid_authorization_count=len(active_paid_authorizations),
        transactions_closed=transactions_closed,
        scheduler_hard_gates_pass=scheduler_hard_gates_pass,
    )
    status = (
        "PASS_DERIVED_PAID_SAFETY_AND_RECOVERY_FLAG_MATCH"
        if paid_actions_allowed and recovery_paid_flag_matches_derived
        else "PASS_DERIVED_PAID_SAFETY_PHASE2_RECOVERY_FLAG_PENDING"
        if paid_actions_allowed
        else "FAIL_STABLE_OR_RUNTIME_PAID_SAFETY_GATES"
    )

    u29c_evidence = u29c_gate["evidence"]
    phase1_set = {
            "updated_at": observed_at,
            "status": "E40_WORK_QUEUE_STABLE_AUTHORITIES_REPAIRED_PHASE2_RECERTIFICATION_REQUIRED",
            "e40_credits": {
                **credit_recomputed,
                "active_remote_image_pay": 0,
                "video_pay": class_credits["video_pay"],
                "audio_pay": class_credits["audio_pay"],
                "image_pay": class_credits["image_pay"],
                "active_remote_video_pay": 0,
            },
            "real_active_handle_count": active_remote_handle_count,
            "task_lane_scheduler": {
                "path": SCHEDULER_REL,
                "observed_sha256": scheduler_sha,
                "episode_terminal": scheduler_episode_terminal,
                "stale_leases_detected": bool(scheduler_gate["stale_or_invalid_active_task_ids"]),
                "status": "DYNAMIC_SNAPSHOT_REOBSERVED_GLOBAL_GATE_PASS"
                if scheduler_hard_gates_pass
                else "DYNAMIC_SNAPSHOT_REOBSERVED_GLOBAL_GATE_FAIL",
                "paid_preflight_revalidation_required": True,
            },
            "latest_e40_u29c_local_depth_layer_candidate": {
                **(queue.get("latest_e40_u29c_local_depth_layer_candidate") or {}),
                "path": u29c_candidate_path,
                "sha256": u29c_candidate_sha,
                "machine_qa": nested(u29c_evidence, "machine_qa.path"),
                "machine_qa_sha256": nested(u29c_evidence, "machine_qa.sha256"),
                "human_review": nested(u29c_evidence, "human_qa.status"),
                "human_qa": nested(u29c_evidence, "human_qa.path"),
                "human_qa_sha256": nested(u29c_evidence, "human_qa.sha256"),
                "status": str(u29c_gate.get("status")),
            },
            "latest_e40_u29b_independent_material_admission_final_chain_hold": {
                **(queue.get("latest_e40_u29b_independent_material_admission_final_chain_hold") or {}),
                "path": u29b_readiness_rel,
                "status": str(u29b_readiness.get("status")),
                "final_chain_slot_enabled": bool(nested(u29b_readiness, "readiness_binding.final_chain_slot_enabled")),
            },
            "work_queue_recovery": {
                **(queue.get("work_queue_recovery") or {}),
                "paid_actions_allowed": False,
                "release_actions_allowed": False,
                "authoritative_certification_path": CERTIFICATION_REL,
                "authoritative_certification_status": status,
                "authoritative_certification_input_work_queue_sha256": queue_sha,
                "dynamic_scheduler_observed_sha256": scheduler_sha,
                "recovery_patch_phase": "PHASE1_STABLE_AUTHORITY_PATCH_PROPOSED_REQUIRES_FRESH_POST_PATCH_CERTIFICATION",
            },
        }
    patch = {
        "schema": "qingshan.e40.work_queue_two_phase_root_review_patch_proposal.v1",
        "requires_root_review": True,
        "write_performed": False,
        "phase_1_stable_authority_repair": {
            "operation": "CAS_MERGE",
            "base_work_queue_sha256": queue_sha,
            "paid_actions_allowed_after_phase": False,
            "release_actions_allowed_after_phase": False,
            "set": phase1_set,
        },
        "phase_2_paid_flag_after_fresh_recertification": {
            "operation": "CAS_MERGE",
            "base_work_queue_sha256": "<PHASE1_RESULT_SHA256>",
            "candidate_allowed_by_current_non_queue_runtime_gates": phase2_candidate_paid_safety,
            "preconditions": [
                "PHASE1_CAS_APPLIED_EXACTLY",
                "FRESH_POST_PHASE1_CERTIFICATION_STABLE_FIELDS_CLOSED",
                "FRESH_DUAL_CREDIT_METHOD_AGREES",
                "FRESH_ACTIVE_REMOTE_HANDLES_EQ_0",
                "FRESH_ACTIVE_PAID_AUTHORIZATIONS_EQ_0",
                "FRESH_TRANSACTION_RECONCILIATION_CLOSED",
                "FRESH_SCHEDULER_PATH_EPISODE_TERMINAL_GLOBAL_GATE_PASS",
                "FRESH_SCHEDULER_SHA_REOBSERVED_AT_PAID_PREFLIGHT",
            ],
            "set": {
                "work_queue_recovery": {
                    "paid_actions_allowed": True,
                    "release_actions_allowed": False,
                    "authoritative_certification_path": "<FRESH_POST_PHASE1_CERTIFICATION_PATH>",
                    "authoritative_certification_status": "PASS_DERIVED_PAID_SAFETY_PHASE2_RECOVERY_FLAG_PENDING",
                    "recovery_patch_phase": "PHASE2_PAID_FLAG_APPLIED_FROM_FRESH_DERIVED_SAFETY_RECEIPT",
                }
            },
        },
    }

    return {
        "schema": "qingshan.e40.work_queue_authoritative_reconstruction_certification.v1",
        "recorded_at": observed_at,
        "episode": "E40",
        "status": status,
        "canonical": {
            "script": {"path": SCRIPT_REL, "sha256": sha256_path(root / SCRIPT_REL), "expected_sha256": EXPECTED_SCRIPT_SHA},
            "manifest": {"path": MANIFEST_REL, "sha256": sha256_path(root / MANIFEST_REL), "expected_sha256": EXPECTED_MANIFEST_SHA},
        },
        "inputs": {
            "work_queue": {"path": QUEUE_REL, "sha256": queue_sha},
            "scheduler": {"path": SCHEDULER_REL, "sha256": scheduler_sha},
            "baseline": {"path": BASELINE_REL, "sha256": baseline_sha, "recorded_at": cutoff},
        },
        "transaction_inventory": inventory,
        "post_baseline_reconciliation": post,
        "credit_recomputation": {
            "baseline_plus_exact_post_transactions": credit_recomputed,
            "media_class_recomputation": class_credits,
            "dual_method_agrees": dual_credit_method_agrees,
        },
        "active_remote_handles": {
            "count": active_remote_handle_count,
            "task_ids": remote_provider_handles,
            "post_baseline_all_terminal": post["all_terminal"],
            "baseline_active_remote_image_pay": base_credits["active_remote_image_pay"],
            "baseline_active_remote_video_pay": base_credits["active_remote_video_pay"],
        },
        "transaction_reconciliation": {
            "closed": transactions_closed,
            "post_baseline_all_terminal": post["all_terminal"],
            "unbound_zero_or_not_charged_reconciled": inventory["unbound_zero_or_not_charged_reconciled"],
            "failures": post["failures"] + inventory["unbound_reconciliation_failures"],
        },
        "model_policy": {
            "only_video_model": "seedance-2.0-fast",
            "only_video_resolution": "720p",
            "forbidden_video_models": ["seedance-2.0-pro", "seedance-2.0-mini", "seedance-2.0"],
            "post_baseline_video_models": sorted(
                {entry["model"] for entry in inventory["entries"] if entry["media"] == "video" and str(entry.get("intent_at") or "") > cutoff}
            ),
        },
        "scheduler_dynamic_observation": {
            "path": SCHEDULER_REL,
            "stored_sha256": queue_scheduler.get("observed_sha256"),
            "observed_sha256": scheduler_sha,
            "sha_drift": scheduler_sha_drift,
            "sha_drift_classification": "WARNING_DYNAMIC_REOBSERVE_AT_EVERY_PAID_PREFLIGHT"
            if scheduler_sha_drift
            else "CURRENT_AT_CERTIFICATION_TIME",
            "sha_is_permanent_execution_critical_field": False,
            "paid_preflight_revalidation_required": True,
            "path_gate_pass": queue_scheduler.get("path") == SCHEDULER_REL,
            "episode_terminal_gate_pass": queue_scheduler.get("episode_terminal") == scheduler_episode_terminal,
            "global_wait_gate": scheduler_gate,
            "hard_gates_pass": scheduler_hard_gates_pass,
        },
        "current_blockers": current_blockers,
        "current_blockers_affect_paid_safety": False,
        "stable_field_certifications": stable_certifications,
        "field_certifications": stable_certifications,
        "stable_field_failures": stable_failures,
        "runtime_gate_failures": runtime_gate_failures,
        "dynamic_warnings": dynamic_warnings,
        "failed_critical_fields": stable_failures + runtime_gate_failures,
        "stable_fields_closed": stable_fields_closed,
        "all_critical_fields_closed": paid_actions_allowed,
        "paid_safety_derivation": {
            "stable_fields_closed": stable_fields_closed,
            "dual_credit_method_agrees": dual_credit_method_agrees,
            "active_remote_handle_count": active_remote_handle_count,
            "active_paid_authorization_count": len(active_paid_authorizations),
            "transactions_closed": transactions_closed,
            "scheduler_hard_gates_pass": scheduler_hard_gates_pass,
            "unrelated_zero_cost_qa_or_current_blockers_excluded": True,
            "derived_value": paid_actions_allowed,
        },
        "work_queue_recovery_paid_flag": queue_recovery_paid_flag,
        "recovery_paid_flag_matches_derived": recovery_paid_flag_matches_derived,
        "paid_actions_allowed": paid_actions_allowed,
        "release_actions_allowed": False,
        "work_queue_write_performed": False,
        "provider_calls": 0,
        "transactions_created": 0,
        "credits_changed": 0,
        "browser_actions": 0,
        "platform_actions": 0,
        "assembly_actions": 0,
        "root_review_patch_proposal": patch,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--observed-at")
    args = parser.parse_args()
    result = build_certification(args.root.resolve(), args.observed_at)
    if args.out:
        out = args.out if args.out.is_absolute() else args.root / args.out
        if out.resolve() == (args.root / QUEUE_REL).resolve():
            raise SystemExit("refusing to write workflow/work_queue.json")
        atomic_json(out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_critical_fields_closed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
