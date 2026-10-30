#!/usr/bin/env python3
"""Submit a SHA-bound character-asset plan concurrently (HopsAPI gpt-image-2, or Giggle as rollback).

Image provider (owner 2026-10-30): ``image_provider`` resolved by tools/hopsapi_image_client.py
(env NALU_IMAGE_PROVIDER > qingshan.json generation.image_provider > hopsapi when HOPSAPI_API_KEY
is set).  The submission fingerprint is the logical request and does not include the provider, so a
bound take is recovered (never re-POSTed) whichever provider is active now."""

from __future__ import annotations

import argparse
import base64
import glob as _glob
import hashlib
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from tools.giggle_api_client import _request, dns_failed_before_connect, durable_generation_context
    from tools.giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from tools.visual_culture_contract import validate_visual_culture_contract
    from tools.provider_request_digest import request_digest, SCHEMA as DIGEST_SCHEMA
    from tools import hopsapi_image_client as image_client
except ModuleNotFoundError:
    from giggle_api_client import _request, dns_failed_before_connect, durable_generation_context
    from giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from visual_culture_contract import validate_visual_culture_contract
    from provider_request_digest import request_digest, SCHEMA as DIGEST_SCHEMA
    import hopsapi_image_client as image_client


ROOT = Path(__file__).resolve().parents[1]


def portable_path(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise.

    Report writing must never be able to fail after validation has passed and,
    for a paid run, after the provider has already been charged.  Mirrors
    tools/submit_giggle_image_manifest.py:51-56.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


class DuplicateSubmissionBlocked(RuntimeError):
    """A prior charged or unresolved character-asset intent cannot be repeated."""


class PreIntentFailure(RuntimeError):
    """A row failed before its intent record was written: no POST, no charge, no transaction file.

    Lab E08 2026-10-29: such a failure was recorded with the transaction path the row WOULD have
    used, the reconciliation loop then read that never-written file and the FileNotFoundError
    masked the original error.  Same convention as the video submitter
    (state submit_failed_before_intent, credit 0, NOT_CHARGED_NO_INTENT_RECORDED)."""

    def __init__(self, original: BaseException):
        self.original = original
        super().__init__(f"{type(original).__name__}: {original}")


BOUND_STATE = "SUBMITTED_TASK_ID_BOUND"


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # unique temporary per writer: two workers rewriting one file must never race on one ".part"
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def submission_fingerprint(row: dict, model: str, resolution: str) -> str:
    contract = {
        "character_id": row.get("id"),
        "prompt_sha256": row.get("prompt_sha256"),
        "reference_image_sha256s": list(row.get("reference_image_sha256s") or []),
        "model": model,
        "aspect_ratio": "9:16",
        "resolution": resolution,
    }
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()


def transaction_path(transaction_dir: Path, row: dict, model: str, resolution: str) -> Path:
    fingerprint = submission_fingerprint(row, model, resolution)
    return transaction_dir / f"{row['id']}__{fingerprint[:16]}.json"


def safe_name(value: str) -> str:
    """tools/harvest_giggle_image_batch.safe: the harvested image is <episode>_<safe(task_key)>_<task_id>.png."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "task"


def own_transactions(transaction_dir: Path, task_key: str) -> list[tuple[Path, dict]]:
    """Transactions of exactly ``task_key``.  ``CHAR-X__*.json`` also matches the view rows
    ``CHAR-X__FRONT_NEUTRAL_HEADSHOT__*.json``; those belong to other rows and are never touched."""
    rows: list[tuple[Path, dict]] = []
    if not transaction_dir.is_dir():
        return rows
    for path in sorted(transaction_dir.glob(f"{_glob.escape(task_key)}__*.json")):
        if path.stem.rsplit("__", 1)[0] != task_key:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and str(payload.get("task_key") or task_key) == task_key:
            rows.append((path, payload))
    return rows


def harvested_binding(row: dict, transaction_dir: Path, plates_dir: Path | None, *,
                      current_fingerprint: str) -> dict | None:
    """A bound, already HARVESTED take of this row under another fingerprint (None if none).

    Lab E08 2026-10-29: the multi-view sheet's reference list grows once the headshot is harvested,
    so a normal S3 re-entry recomputed a new fingerprint for a sheet that was paid for, bound and on
    disk, and planned/POSTed it again.  Mirrors tools/video_live_binding.py: same task_key (subject
    + asset role) + SUBMITTED_TASK_ID_BOUND + its harvested image on disk => that take is reused,
    whatever the recomputed fingerprint.  Only an explicit ``supersedes_submission_fingerprints``
    entry on the row (a deliberate regeneration) lets a new POST through; parking/removing the
    image does too.  ``superseded_by`` markers are ignored: they were written before a POST that
    may never have happened."""
    if plates_dir is None or not Path(plates_dir).is_dir():
        return None
    task_key = str(row["id"])
    supersedes = {str(v) for v in row.get("supersedes_submission_fingerprints") or [] if v}
    found: list[dict] = []
    for path, tx in own_transactions(transaction_dir, task_key):
        fingerprint = str(tx.get("submission_fingerprint") or "")
        task_id = str(tx.get("task_id") or "")
        if tx.get("state") != BOUND_STATE or not task_id or fingerprint == current_fingerprint:
            continue
        if fingerprint in supersedes or fingerprint[:16] in supersedes:
            continue
        episode = str(tx.get("episode") or row.get("episode") or "")
        image = Path(plates_dir) / f"{episode}_{safe_name(task_key)}_{task_id}.png"
        if not image.is_file():
            continue
        found.append({"path": path, "transaction": tx, "image": image})
    if not found:
        return None
    found.sort(key=lambda item: str(item["transaction"].get("response_recorded_at") or ""))
    return found[-1]


def prior_submission(row: dict, transaction_dir: Path, model: str, resolution: str,
                     plates_dir: Path | None = None) -> dict | None:
    path = transaction_path(transaction_dir, row, model, resolution)
    current_fingerprint = submission_fingerprint(row, model, resolution)
    char_id = row["id"]

    if not path.is_file():
        binding = harvested_binding(row, transaction_dir, plates_dir, current_fingerprint=current_fingerprint)
        if binding is not None:
            tx = binding["transaction"]
            return {
                "task_key": char_id, "character_id": char_id,
                "task_id": tx["task_id"], "status": "SUBMITTED",
                "receipt": tx.get("receipt"),
                "transaction": portable_path(binding["path"]), "recovered_from_transaction": True,
                "reused_harvested_binding": True, "harvested_image": portable_path(binding["image"]),
                "unposted_fingerprint": current_fingerprint,
            }
        # Plan §5.4: supersede this row's old transactions when its contract changes and a new
        # intent is about to be recorded (never another row's, never a harvested take).
        for old_tx_path, old_tx in own_transactions(transaction_dir, char_id):
            old_fp = old_tx.get("submission_fingerprint")
            if old_fp and old_fp != current_fingerprint and not old_tx.get("superseded_by"):
                old_tx["superseded_by"] = current_fingerprint
                old_tx["superseded_at"] = utc_now()
                atomic_json(old_tx_path, old_tx)
        return None
    transaction = json.loads(path.read_text(encoding="utf-8"))
    if transaction.get("submission_fingerprint") != current_fingerprint:
        raise DuplicateSubmissionBlocked(f"{char_id} transaction fingerprint mismatch")
    if image_client.retire_terminal_failed(path, transaction) is not None:
        # a HopsAPI task that settled failed/cancelled (status 3/4, not charged, no image): the
        # record is kept beside it for the ledger and this fingerprint may POST a new attempt
        return None
    if transaction.get("state") == "SUBMITTED_TASK_ID_BOUND" and transaction.get("task_id"):
        return {
            "task_key": char_id, "character_id": char_id,
            "task_id": transaction["task_id"], "status": "SUBMITTED",
            "receipt": transaction.get("receipt"),
            "transaction": portable_path(path), "recovered_from_transaction": True,
        }
    if transaction.get("state") in {
        "INTENT_RECORDED", "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
        "CHARGED_TASK_ID_MISSING", "CHARGE_STATE_UNRESOLVED_BATCH",
    }:
        raise DuplicateSubmissionBlocked(
            f"{char_id} duplicate submit blocked by {transaction.get('state')}"
        )
    return None


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def resolved_reference_images(row: dict) -> list[Path]:
    values = list(row.get("reference_images") or [])
    expected = list(row.get("reference_image_sha256s") or [])
    if len(values) != len(expected):
        raise ValueError(f"{row['id']} reference image path/SHA count mismatch")
    if len(values) > 9:
        raise ValueError(f"{row['id']} has more than 9 reference images")
    paths = [resolve(str(value)) for value in values]
    for path, wanted in zip(paths, expected):
        if not path.is_file():
            raise ValueError(f"{row['id']} missing reference image: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != str(wanted):
            raise ValueError(f"{row['id']} reference image SHA mismatch: {path}")
    return paths


def submit(row: dict, output_dir: Path, transaction_dir: Path, model: str, resolution: str,
           plates_dir: Path | None = None, provider: str | None = None) -> dict:
    try:
        return _submit(row, output_dir, transaction_dir, model, resolution, plates_dir, provider)
    except _IntentRecorded as marker:
        raise marker.original
    except PreIntentFailure:
        raise
    except (Exception, SystemExit) as exc:
        raise PreIntentFailure(exc) from exc


class _IntentRecorded(Exception):
    """Internal: an exception raised AFTER the intent record was written (charge question open)."""

    def __init__(self, original: BaseException):
        self.original = original
        super().__init__(str(original))


def _submit(row: dict, output_dir: Path, transaction_dir: Path, model: str, resolution: str,
            plates_dir: Path | None, provider: str | None = None) -> dict:
    recovered = prior_submission(row, transaction_dir, model, resolution, plates_dir)
    if recovered:
        return recovered
    provider = provider or image_client.image_provider()
    prompt_path = resolve(row["prompt_file"])
    actual_sha = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    if actual_sha != row["prompt_sha256"]:
        raise ValueError(f"{row['id']} prompt SHA mismatch")
    references = resolved_reference_images(row)
    prompt_text = prompt_path.read_text(encoding="utf-8")

    # Plan §7.1: bind review to the semantic request about to be sent.
    ref_shas = [hashlib.sha256(p.read_bytes()).hexdigest() for p in references]
    computed_digest = request_digest(
        prompt_text=prompt_text, model=model, aspect_ratio="9:16", resolution=resolution,
        reference_sha256=ref_shas, reference_roles=["identity_reference"] * len(ref_shas)
    )
    declared_digest = row.get("reviewed_request_sha256")
    if declared_digest and declared_digest != computed_digest:
        raise RuntimeError(
            f"{row['id']}: reviewed_request_sha256 mismatch. "
            f"The request about to be sent (digest {computed_digest[:16]}) does not match "
            f"the reviewed version ({declared_digest[:16]}). Zero POST."
        )

    if provider == image_client.PROVIDER_HOPSAPI:
        return _submit_hopsapi(row, output_dir, transaction_dir, model, resolution, prompt_text, references)

    payload = {
        "prompt": prompt_text,
        "generate_count": 1,
        "model": model,
        "aspect_ratio": "9:16",
        "resolution": resolution,
        "watermark": False,
    }
    endpoint = "/api/v1/generation/text-to-image"
    if references:
        endpoint = "/api/v1/generation/image-to-image"
        payload["reference_images"] = [
            {"base64": base64.b64encode(path.read_bytes()).decode("ascii")}
            for path in references
        ]
    transaction = transaction_path(transaction_dir, row, model, resolution)
    intent = {
        "schema": "qingshan.giggle_submit_transaction.v1",
        "episode": str(row.get("episode") or "UNKNOWN"), "task_key": row["id"], "attempt_id": str(uuid.uuid4()),
        "submission_fingerprint": submission_fingerprint(row, model, resolution),
        "state": "INTENT_RECORDED", "intent_recorded_at": utc_now(),
        "model": model, "prompt_sha256": row["prompt_sha256"],
        "reference_image_sha256s": list(row.get("reference_image_sha256s") or []),
        "endpoint": endpoint,
        "retry_guard": "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED",
    }
    atomic_json(transaction, intent)
    try:
        return _post_after_intent(row, output_dir, transaction, intent, endpoint, payload)
    except (Exception, SystemExit) as exc:
        raise _IntentRecorded(exc) from exc


def _submit_hopsapi(row: dict, output_dir: Path, transaction_dir: Path, model: str, resolution: str,
                    prompt_text: str, references: list[Path]) -> dict:
    """HopsAPI gpt-image-2: preprocess + upload references (free, pre-intent) -> intent -> ONE create
    POST -> bind.  Failures are classified per attempt (there is no Giggle statement to reconcile):
    not sent / explicitly refused without a task id is NOT_CHARGED_RETRYABLE; anything after the
    request may have arrived is RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION and is never resent."""
    prepared = image_client.prepare_request(prompt=prompt_text, reference_paths=references,
                                            aspect_ratio="9:16", resolution=resolution, task_key=row["id"])
    transaction = transaction_path(transaction_dir, row, model, resolution)
    intent = {
        "schema": "qingshan.giggle_submit_transaction.v1",
        "episode": str(row.get("episode") or "UNKNOWN"), "task_key": row["id"], "attempt_id": str(uuid.uuid4()),
        "submission_fingerprint": submission_fingerprint(row, model, resolution),
        "state": "INTENT_RECORDED", "intent_recorded_at": utc_now(),
        "model": model, "prompt_sha256": row["prompt_sha256"],
        "reference_image_sha256s": list(row.get("reference_image_sha256s") or []),
        "endpoint": "hopsapi:/router/task/create",
        "retry_guard": "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED",
        **image_client.intent_fields(prepared),
    }
    atomic_json(transaction, intent)
    try:
        return _post_hopsapi_after_intent(row, output_dir, transaction, intent, prepared["payload"])
    except (Exception, SystemExit) as exc:
        raise _IntentRecorded(exc) from exc


def _post_hopsapi_after_intent(row: dict, output_dir: Path, transaction: Path, intent: dict,
                               payload: dict) -> dict:
    previous_context = os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT")
    os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = "1"
    try:
        with durable_generation_context():
            response = image_client.create_image_task(payload)
    except image_client.hops.HopsapiNotCharged as exc:
        intent.update({"state": "NOT_CHARGED_RETRYABLE", "credit_status": "NOT_CHARGED_RETRYABLE",
                       "response_received_at": utc_now(), "error": str(exc),
                       "provider_response": exc.response, "provider_http_status": exc.http_status,
                       "retry_guard": "RETRY_ALLOWED_NEW_ATTEMPT",
                       "reconciliation_evidence": {"method": "HOPSAPI_CREATE_PROVABLY_CREATED_NO_TASK", "credit": 0}})
        atomic_json(transaction, intent)
        raise RuntimeError(f"{row['id']} HopsAPI create declined (not charged): {exc}") from None
    except (Exception, SystemExit) as exc:
        intent.update({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "error": str(exc),
                       "response_lost_at": utc_now(),
                       "operator_note": "HopsAPI has no idempotency key: check the HopsAPI console for a task "
                                        "created at intent_recorded_at before any new POST"})
        atomic_json(transaction, intent)
        raise
    finally:
        if previous_context is None:
            os.environ.pop("QINGSHAN_DURABLE_SUBMITTER_CONTEXT", None)
        else:
            os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = previous_context
    task_id = str(response["task_id"])
    receipt_path = output_dir / f"{row['id']}_submit_response.json"
    atomic_json(receipt_path, response)
    intent.update({"state": BOUND_STATE, "task_id": task_id, "receipt": portable_path(receipt_path),
                   "provider_response": response, "response_recorded_at": utc_now()})
    atomic_json(transaction, intent)
    return {"task_key": row["id"], "character_id": row["id"], "task_id": task_id, "status": "SUBMITTED",
            "provider": image_client.PROVIDER_HOPSAPI, "receipt": portable_path(receipt_path),
            "transaction": portable_path(transaction), "recovered_from_transaction": False}


def _post_after_intent(row: dict, output_dir: Path, transaction: Path, intent: dict, endpoint: str,
                       payload: dict) -> dict:
    previous_context = os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT")
    os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = "1"
    try:
        # both durable-context signals: the env var (nalu line, e13) and the API client's
        # ContextVar (Codex line); the client accepts either, each line's test checks one.
        with durable_generation_context():
            response = _request(endpoint, payload)
    except (Exception, SystemExit) as exc:
        if dns_failed_before_connect(exc):
            # the host name never resolved: no connection, no request, no charge
            intent.update({"state": "NOT_CHARGED_RETRYABLE", "error": str(exc), "response_lost_at": utc_now(),
                           "retry_guard": "RETRY_ALLOWED_NEW_ATTEMPT",
                           "reconciliation_evidence": {"method": "DNS_RESOLUTION_FAILED_BEFORE_CONNECT"}})
        else:
            intent.update({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "error": str(exc),
                           "response_lost_at": utc_now()})
        atomic_json(transaction, intent)
        raise
    finally:
        if previous_context is None:
            os.environ.pop("QINGSHAN_DURABLE_SUBMITTER_CONTEXT", None)
        else:
            os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = previous_context
    task_id = (response.get("data") or {}).get("task_id")
    if not task_id:
        # keep the provider body (code/msg) so a charged-but-unbound row can be diagnosed;
        # the image-manifest submitter already records it the same way
        intent.update({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "error": "response has no task_id", "provider_response": response, "response_lost_at": utc_now()})
        atomic_json(transaction, intent)
        raise RuntimeError(f"{row['id']} response has no task_id: code={response.get('code')!r} msg={str(response.get('msg'))[:200]!r}")
    receipt_path = output_dir / f"{row['id']}_submit_response.json"
    atomic_json(receipt_path, response)
    intent.update({"state": "SUBMITTED_TASK_ID_BOUND", "task_id": task_id, "receipt": portable_path(receipt_path), "response_recorded_at": utc_now()})
    atomic_json(transaction, intent)
    return {"task_key": row["id"], "character_id": row["id"], "task_id": task_id, "status": "SUBMITTED", "receipt": portable_path(receipt_path), "transaction": portable_path(transaction), "recovered_from_transaction": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--precheck-only", action="store_true")
    parser.add_argument("--plates-dir", default=None,
                        help="harvested image dir; a bound take whose image is here is reused, never re-POSTed")
    args = parser.parse_args()
    plan_path = resolve(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    rows = plan.get("new_asset_groups") or []
    if not rows:
        raise SystemExit("character asset plan contains zero new_asset_groups")
    if plan.get("quality") != "pro":
        raise SystemExit("character asset plan must use pro quality")
    for row in rows:
        row.setdefault("episode", plan.get("episode"))
    gate_paths = plan.get("machine_gate_reports") or []
    if not gate_paths:
        raise SystemExit("character asset plan has no machine_gate_reports")
    for gate_value in gate_paths:
        gate_path = resolve(gate_value)
        if not gate_path.is_file() or json.loads(gate_path.read_text(encoding="utf-8")).get("status") != "PASS":
            raise SystemExit(f"character asset gate is not PASS: {gate_value}")
    for row in rows:
        prompt_path = resolve(row.get("prompt_file", ""))
        if not prompt_path.is_file() or hashlib.sha256(prompt_path.read_bytes()).hexdigest() != row.get("prompt_sha256"):
            raise SystemExit(f"invalid prompt binding: {row.get('id')}")
        culture = validate_visual_culture_contract(row, prompt_text=prompt_path.read_text(encoding="utf-8"))
        if culture["status"] != "PASS":
            raise SystemExit(f"visual culture gate failed for {row.get('id')}: {','.join(culture['failures'])}")
        try:
            resolved_reference_images(row)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    provider = image_client.image_provider()
    if not args.precheck_only:
        key_env = image_client.required_key_env(provider)
        if not os.environ.get(key_env, "").strip():
            raise SystemExit(f"{key_env} is not set")
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt_dir = out.parent / f"{out.stem}_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    episode_key = str(plan.get("episode") or "UNKNOWN").replace("/", "-")
    transaction_dir = ROOT / "workflow" / "tasks" / "giggle_submit_transactions" / episode_key
    transaction_dir.mkdir(parents=True, exist_ok=True)
    results, failures = [], []
    submit_started_at = datetime.now(timezone.utc)
    if args.precheck_only:
        results = [{"character_id": row["id"], "status": "PRECHECK_PASS"} for row in rows]
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            plates_dir = resolve(args.plates_dir) if args.plates_dir else None
            futures = {pool.submit(submit, row, receipt_dir, transaction_dir, "gpt-image-2-pro", "2K", plates_dir,
                                   provider): row for row in rows}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    results.append(future.result())
                except PreIntentFailure as exc:
                    # no intent was recorded by this attempt: no transaction to read or rewrite
                    failures.append({"character_id": row["id"], "status": "SUBMIT_FAILED_BEFORE_INTENT",
                                     "state": "submit_failed_before_intent", "error": str(exc),
                                     "credit": 0, "credit_status": "NOT_CHARGED_NO_INTENT_RECORDED"})
                except (Exception, SystemExit) as exc:
                    failures.append({"character_id": row["id"], "status": "SUBMIT_FAILED", "error": f"{type(exc).__name__}: {exc}", "transaction": portable_path(transaction_path(transaction_dir, row, "gpt-image-2-pro", "2K"))})
    credit_reconciliation = None
    ambiguity_resolution = "NOT_APPLICABLE"
    if not args.precheck_only:
        newly_submitted = sum(not row.get("recovered_from_transaction") for row in results)
        recovered = sum(bool(row.get("recovered_from_transaction")) for row in results)
        posted_failures = [f for f in failures if f.get("transaction")]
        maximum_possible = newly_submitted + len(posted_failures)
        if provider == image_client.PROVIDER_HOPSAPI:
            # Billed per task (``cost`` on the settled query, written onto the transaction by the
            # harvester and counted by the budget ledger), never through Giggle's statements.  Each
            # failure was classified at its own attempt; read that state back, never overwrite it.
            for failure in posted_failures:
                path = resolve(failure["transaction"])
                tx = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
                failure["provider"] = image_client.PROVIDER_HOPSAPI
                failure["credit_status"] = ("NOT_CHARGED_NO_INTENT_RECORDED" if not tx
                                            else str(tx.get("state") or "UNKNOWN"))
                if not tx or tx.get("state") == "NOT_CHARGED_RETRYABLE":
                    failure["credit"] = 0
            credit_reconciliation = {
                "status": "PASS_BOUNDED", "provider": image_client.PROVIDER_HOPSAPI,
                "method": "HOPSAPI_PER_TASK_COST_RECORDED_AT_SETTLEMENT", "charged_credits": None,
                "newly_bound_task_ids": sorted(str(r["task_id"]) for r in results
                                               if not r.get("recovered_from_transaction")),
                "estimated_credits": image_client.estimated_batch_credits(newly_submitted),
                "note": "cost is known at status 2: harvest_giggle_image_batch.py writes provider_cost_credits "
                        "onto each transaction and nalu_budget_ledger.py counts it; until then the estimate is exposure",
            }
            ambiguity_resolution = ("NO_AMBIGUOUS_SUBMISSIONS" if not posted_failures
                                    else "HOPSAPI_PER_ATTEMPT_CLASSIFIED")
            matched = newly_submitted
        elif maximum_possible == 0:
            credit_reconciliation = {"status": "PASS_REUSED_TRANSACTIONS", "matched_count": 0, "charged_credits": 0}
            matched = 0
        else:
            for attempt in range(7):
                credit_reconciliation = reconcile_rows(fetch_pay_statements(), start=submit_started_at - timedelta(seconds=10), end=datetime.now(timezone.utc) + timedelta(seconds=10), expected_count=maximum_possible, event_description="SingleGenerateImage", model="gpt-image-2-pro")
                matched = int(credit_reconciliation.get("matched_count", 0))
                if matched >= newly_submitted or attempt == 6:
                    break
                time.sleep(5)
            if newly_submitted <= matched <= maximum_possible:
                credit_reconciliation["status"] = "PASS_BOUNDED"
        if provider != image_client.PROVIDER_HOPSAPI:
            extra_charges = matched - newly_submitted
            if not posted_failures and failures:
                ambiguity_resolution = "PRE_INTENT_FAILURES_NOT_CHARGED"
                failure_state = None
            elif posted_failures and extra_charges == 0:
                ambiguity_resolution = "ALL_RESPONSE_LOSSES_VERIFIED_NOT_CHARGED"
                failure_state = "VERIFIED_ZERO_RETRYABLE"
            elif posted_failures:
                ambiguity_resolution = "CHARGED_OR_UNRESOLVED_RESPONSE_LOSS_QUARANTINED"
                failure_state = "CHARGE_STATE_UNRESOLVED_BATCH"
            else:
                ambiguity_resolution = "NO_AMBIGUOUS_SUBMISSIONS"
                failure_state = None
            for failure in posted_failures:
                path = resolve(failure["transaction"])
                if not path.is_file():
                    # never invent or crash on a transaction this run did not write; keep the real error
                    failure["transaction_missing"] = True
                    continue
                transaction = json.loads(path.read_text(encoding="utf-8"))
                transaction.update({"state": failure_state, "ledger_reconciled_at": utc_now(), "batch_known_task_ids": newly_submitted, "batch_ledger_pay_rows": matched})
                atomic_json(path, transaction)
        atomic_json(out.parent / f"{out.stem}_credit_statement.json", credit_reconciliation)
    generation_pass = len(results) == len(rows) and not failures
    cost_pass = args.precheck_only or (credit_reconciliation or {}).get("status") in {"PASS", "PASS_BOUNDED", "PASS_REUSED_TRANSACTIONS"}
    report = {
        "schema": "qingshan.character_asset_submit.v1",
        "episode": plan.get("episode"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "plan": portable_path(plan_path),
        "model": "gpt-image-2-pro",
        "resolution": "2K",
        "image_provider": provider,
        "provider_model": image_client.MODEL if provider == image_client.PROVIDER_HOPSAPI else "gpt-image-2-pro",
        "concurrency": max(1, args.concurrency),
        "precheck_only": args.precheck_only,
        "status": "PASS" if generation_pass and cost_pass else "FAIL",
        "results": sorted(results, key=lambda row: row["character_id"]),
        "failures": sorted(failures, key=lambda row: row["character_id"]),
        "credit_reconciliation": credit_reconciliation,
        "ambiguity_resolution": ambiguity_resolution,
        "transaction_dir": portable_path(transaction_dir),
        "duplicate_submit_policy": "TASK_FINGERPRINT_TRANSACTION_GUARD",
        "credits": {"pay": (credit_reconciliation or {}).get("charged_credits", 0) if not args.precheck_only else 0, "refund": 0, "net": (credit_reconciliation or {}).get("charged_credits", 0) if not args.precheck_only else 0, "cap": 10000}
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "result_count": len(results), "failure_count": len(failures)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
