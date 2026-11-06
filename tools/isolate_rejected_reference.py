#!/usr/bin/env python3
"""Find which reference image a provider deterministically refuses, and declare it excluded.

Use when ONE S5 task's request settles as the zero-cost HopsAPI 424 "Provider error" every time while
other tasks pass (device ...1324 E01 S5, 2026-11-06: the place map GSM-NALU-HUT_V1.png).  For each
transmitted NON-identity reference of that task, this submits single-reference Img2Img probes (neutral
prompt, quality low, 1024x1536) through the guarded HopsAPI transport:

* paid only with ``--paid`` AND inside the pipeline's paid step (``paid_stage.sh <EP> --isolate-reference
  <TASK_KEY>``: order check, budget reservation against the episode cap, one paid run per episode) --
  the helper refuses a ``--paid`` run without the paid-step environment;
* every probe is a durable transaction in the episode's image store BEFORE the POST (the budget ledger
  counts it; a bound probe is recovered, never re-POSTed); probes are flagged
  ``reference_isolation_probe`` so they never feed the outage detector;
* at most ``MAX_PROBES`` probes per run; the API key is never printed.

A reference whose every try (``--tries``, default 2) settles as the uncharged 424 while at least one OTHER
reference passes is written to ``$NALU_RUNTIME_ROOT/preproduction/<EP>/provider_reference_exclusions.json``
(tools/provider_reference_exclusions.py).  When every reference fails the provider is down (no
declaration); when none fails the rejection is the prompt, not a reference (no declaration).  Identity
plates are never probed or declared.

Without ``--paid`` it only prints the plan (references, probe count, planned credits) -- no network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import provider_reference_exclusions as pre  # noqa: E402

SCHEMA_REPORT = "nalu.reference_isolation_report.v1"
NEUTRAL_PROMPT = ("Neutral test render. Reproduce the general layout and colours of the reference image as a "
                  "plain, simple illustration. No text, no people.")
PROBE_RESOLUTION = "1024x1536"
PROBE_QUALITY = "low"
DEFAULT_TRIES = 2
MAX_PROBES = 12
POLL_SECONDS = 5
SETTLE_WAIT_SECONDS = 240
PAID_ENV = ("NALU_PAID_ORDER_SEQ", "NALU_PAID_AUTHORIZATION_REF")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _client():
    from tools import hopsapi_image_client as image_client  # noqa: PLC0415
    return image_client


def find_task(manifest: dict[str, Any], task_key: str) -> dict[str, Any]:
    for task in manifest.get("tasks") or []:
        if str(task.get("task_key")) == task_key:
            return task
    raise SystemExit(f"TASK_NOT_IN_MANIFEST:{task_key}")


def candidate_references(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Unique transmitted non-identity files, in transport order, with every role they serve."""
    rows = task.get("reference_image_sequence") or pre.transmitted_bindings(task.get("reference_bindings"))
    identity_paths = {str(row.get("path")) for row in rows if pre.is_identity_binding(row)}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        path = str(row.get("path") or "")
        if not path or path in identity_paths or not pre.is_transmitted(row):
            continue
        item = out.setdefault(path, {"path": path, "sha256": row.get("sha256"), "roles": [], "entity_ids": []})
        item["roles"].append(row.get("role"))
        item["entity_ids"].append(row.get("entity_id"))
    return list(out.values())


def task_rejections(task_key: str, transaction_dir: Path) -> list[dict[str, Any]]:
    """This task's earlier attempts (retired ones included) that settled as the zero-cost 424."""
    client = _client()
    found = []
    for path in sorted(Path(transaction_dir).glob(f"{task_key}__*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(row, dict) and client.is_provider_error_failure(row):
            found.append({"task_id": row.get("task_id"), "transaction": str(path),
                          "request_id": client.provider_request_id(row.get("provider_failure") or row.get("error"))})
    return found


class HopsapiProbeTransport:
    """The real transport: the same prepare/create/query the durable image submitter uses."""

    def __init__(self) -> None:
        self.client = _client()

    def prepare(self, *, prompt: str, path: str, key: str) -> dict[str, Any]:
        return self.client.prepare_request(prompt=prompt, reference_paths=[path], aspect_ratio="2:3",
                                           resolution=PROBE_RESOLUTION, task_key=key, quality=PROBE_QUALITY)

    def intent_fields(self, prepared: dict[str, Any]) -> dict[str, Any]:
        return self.client.intent_fields(prepared)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            from tools.giggle_api_client import durable_generation_context  # noqa: PLC0415
        except ModuleNotFoundError:  # pragma: no cover
            from giggle_api_client import durable_generation_context  # type: ignore  # noqa: PLC0415
        with durable_generation_context():
            return self.client.create_image_task(payload)

    def query(self, task_id: str) -> dict[str, Any]:
        return self.client.query_task(task_id)

    def record_settlement(self, transaction: Path, task_id: str, status: dict[str, Any]) -> None:
        self.client.record_settlement(transaction, task_id, status, now=utc_now())

    def not_charged_error(self) -> type[BaseException]:
        return self.client.hops.HopsapiNotCharged


def probe_key(task_key: str, index: int, attempt: int) -> str:
    return f"REFPROBE-{task_key}-R{index}-T{attempt}"


def run_probe(transport: Any, *, task_key: str, episode: str, ref: dict[str, Any], index: int, attempt: int,
              transaction_dir: Path, sleep: Callable[[float], None] = time.sleep,
              clock: Callable[[], float] = time.monotonic, wait_seconds: int = SETTLE_WAIT_SECONDS) -> dict[str, Any]:
    """One single-reference probe: intent -> ONE create POST -> bind -> poll to settlement.  A probe whose
    transaction is already bound is recovered (polled), never re-POSTed."""
    key = probe_key(task_key, index, attempt)
    fingerprint = hashlib.sha256(json.dumps({"key": key, "ref": ref.get("sha256"), "prompt": NEUTRAL_PROMPT,
                                             "resolution": PROBE_RESOLUTION, "quality": PROBE_QUALITY},
                                            sort_keys=True).encode("utf-8")).hexdigest()
    transaction = transaction_dir / f"{key}__{fingerprint[:16]}.json"
    row: dict[str, Any] | None = None
    if transaction.is_file():
        row = json.loads(transaction.read_text(encoding="utf-8"))
        if row.get("state") != "SUBMITTED_TASK_ID_BOUND":
            if row.get("state") in {"NOT_CHARGED_RETRYABLE"}:
                row = None  # provably no task: a new attempt may POST
            else:
                return {"outcome": "UNRESOLVED_PRIOR_PROBE", "probe_key": key, "transaction": str(transaction),
                        "state": row.get("state")}
    if row is None:
        prepared = transport.prepare(prompt=NEUTRAL_PROMPT, path=ref["path"], key=key)
        row = {"schema": "qingshan.giggle_submit_transaction.v1", "task_key": key, "episode": episode,
               "reference_isolation_probe": True, "isolates_task_key": task_key,
               "probe_reference": {"path": ref["path"], "sha256": ref.get("sha256"), "roles": ref.get("roles"),
                                   "entity_ids": ref.get("entity_ids"), "attempt": attempt},
               "attempt_id": str(uuid.uuid4()), "submission_fingerprint": fingerprint,
               "state": "INTENT_RECORDED", "intent_recorded_at": utc_now(),
               "model": "gpt-image-2", "retry_guard": "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED",
               **transport.intent_fields(prepared)}
        atomic_json(transaction, row)
        try:
            response = transport.create(prepared["payload"])
        except transport.not_charged_error() as exc:
            row.update({"state": "NOT_CHARGED_RETRYABLE", "credit_status": "NOT_CHARGED_RETRYABLE",
                        "response_received_at": utc_now(), "error": str(exc)[:500]})
            atomic_json(transaction, row)
            return {"outcome": "NOT_SENT", "probe_key": key, "transaction": str(transaction), "error": str(exc)[:200]}
        except (Exception, SystemExit) as exc:
            row.update({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "response_lost_at": utc_now(),
                        "error": str(exc)[:500]})
            atomic_json(transaction, row)
            return {"outcome": "RESPONSE_LOST", "probe_key": key, "transaction": str(transaction)}
        row.update({"state": "SUBMITTED_TASK_ID_BOUND", "task_id": str(response["task_id"]),
                    "response_recorded_at": utc_now()})
        atomic_json(transaction, row)
    task_id = str(row["task_id"])
    deadline = clock() + wait_seconds
    client_424 = _client().is_provider_error_failure
    while True:
        try:
            status = transport.query(task_id)
        except Exception as exc:  # noqa: BLE001 - a GET failure is not a verdict
            status = {"remote_status": "unknown", "error": str(exc)[:200]}
        remote = str(status.get("remote_status") or "unknown")
        if remote == "completed" or remote in {"failed", "cancelled"}:
            transport.record_settlement(transaction, task_id, status)
            if remote == "completed":
                return {"outcome": "PASS", "probe_key": key, "task_id": task_id, "transaction": str(transaction),
                        "cost": status.get("cost")}
            rejected = client_424(status)
            return {"outcome": "PROVIDER_424" if rejected else "FAILED_OTHER", "probe_key": key, "task_id": task_id,
                    "transaction": str(transaction), "provider_code": status.get("provider_code"),
                    "request_id": _client().provider_request_id(status.get("error"))}
        if clock() >= deadline:
            # a 424 settles within seconds; still running = accepted by the provider
            return {"outcome": "PASS", "probe_key": key, "task_id": task_id, "transaction": str(transaction),
                    "note": f"still {remote} after {wait_seconds}s; settlement left to the ledger"}
        sleep(POLL_SECONDS)


def decide(results: dict[str, list[dict[str, Any]]], tries: int) -> dict[str, Any]:
    """Which references to declare: every try a 424, while another reference passed."""
    rejected = [path for path, rows in results.items()
                if len(rows) >= tries and all(row["outcome"] == "PROVIDER_424" for row in rows)]
    passed = [path for path, rows in results.items() if any(row["outcome"] == "PASS" for row in rows)]
    if rejected and not passed:
        return {"verdict": "ALL_REFERENCES_REJECTED_PROVIDER_DOWN_OR_PROMPTLESS_REFUSAL", "declare": []}
    if not rejected:
        return {"verdict": "NO_REFERENCE_DETERMINISTICALLY_REJECTED" if passed else "INCONCLUSIVE", "declare": []}
    return {"verdict": "REFERENCE_ISOLATED", "declare": rejected}


def isolate(*, episode: str, task: dict[str, Any], transaction_dir: Path, declaration_path: Path,
            transport: Any, tries: int = DEFAULT_TRIES, declared_by: str = "tools/isolate_rejected_reference.py",
            probe_kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    task_key = str(task["task_key"])
    refs = candidate_references(task)
    if len(refs) * tries > MAX_PROBES:
        raise SystemExit(f"PROBE_CAP:{len(refs)}x{tries}>{MAX_PROBES}")
    results: dict[str, list[dict[str, Any]]] = {}
    for index, ref in enumerate(refs, 1):
        rows = results.setdefault(ref["path"], [])
        for attempt in range(1, tries + 1):
            row = run_probe(transport, task_key=task_key, episode=episode, ref=ref, index=index, attempt=attempt,
                            transaction_dir=transaction_dir, **(probe_kwargs or {}))
            rows.append(row)
            if row["outcome"] != "PROVIDER_424":
                break  # passed (or not a 424): not deterministic, no second try
    decision = decide(results, tries)
    entries = []
    by_path = {ref["path"]: ref for ref in refs}
    for path in decision["declare"]:
        ref = by_path[path]
        rows = results[path]
        entries.append({
            "sha256": ref.get("sha256"), "path": path,
            "reason": "HOPSAPI_DETERMINISTIC_424_SINGLE_REFERENCE",
            "evidence": {"provider": "hopsapi", "provider_code": 424,
                         "request_ids": [row.get("request_id") for row in rows if row.get("request_id")]
                         or [row.get("task_id") for row in rows],
                         "probe_transactions": [row.get("transaction") for row in rows],
                         "single_reference_probe": True, "tries": len(rows),
                         "other_references_passed": [p for p, rs in results.items()
                                                     if any(r["outcome"] == "PASS" for r in rs)],
                         "isolated_for_task": task_key, "roles": ref.get("roles"), "entity_ids": ref.get("entity_ids")},
            "declared_by": declared_by, "declared_at": utc_now(),
        })
    if entries:
        existing = pre.load_declaration(declaration_path, episode=episode)
        atomic_json(declaration_path, pre.merge_declaration(existing, entries, episode=episode))
    return {"schema": SCHEMA_REPORT, "episode": episode, "task_key": task_key, "tries": tries,
            "references": refs, "probes": results, **decision,
            "declaration": str(declaration_path) if entries else None, "declared": entries, "recorded_at": utc_now()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--task-key", "--task", dest="task_key", required=True)
    parser.add_argument("--manifest", required=True, type=Path, help="the S5 keyframe image manifest")
    parser.add_argument("--declaration", type=Path, default=None,
                        help="default: $NALU_RUNTIME_ROOT/preproduction/<EP>/provider_reference_exclusions.json")
    parser.add_argument("--transaction-dir", type=Path, default=None,
                        help="default: <engine>/workflow/tasks/giggle_submit_transactions/<EP>")
    parser.add_argument("--tries", type=int, default=DEFAULT_TRIES)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--paid", action="store_true")
    args = parser.parse_args(argv)
    episode = args.episode.strip().upper()
    if not 1 <= args.tries <= 3:
        raise SystemExit("--tries must be 1..3")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    task = find_task(manifest, args.task_key)
    transaction_dir = args.transaction_dir or ROOT / "workflow" / "tasks" / "giggle_submit_transactions" / episode
    runtime_root = os.environ.get("NALU_RUNTIME_ROOT") or os.environ.get("RUNTIME_ROOT")
    declaration = args.declaration or (Path(runtime_root).expanduser() / "preproduction" / episode / pre.FILE_NAME
                                       if runtime_root else None)
    if declaration is None:
        raise SystemExit("--declaration or NALU_RUNTIME_ROOT is required")
    rejections = task_rejections(args.task_key, transaction_dir)
    refs = candidate_references(task)
    plan = {"schema": SCHEMA_REPORT, "mode": "PLAN", "episode": episode, "task_key": args.task_key,
            "zero_cost_424_attempts": rejections, "references": refs,
            "max_probes": len(refs) * args.tries, "probe_resolution": PROBE_RESOLUTION, "probe_quality": PROBE_QUALITY,
            "planned_credits": _client().estimated_batch_credits(len(refs) * args.tries),
            "declaration": str(declaration)}
    if not rejections:
        plan["refused"] = "TASK_HAS_NO_ZERO_COST_424_ATTEMPT"
        print(json.dumps(plan, ensure_ascii=False))
        return 3
    if not refs or len(refs) * args.tries > MAX_PROBES:
        plan["refused"] = "NO_NON_IDENTITY_REFERENCE" if not refs else f"PROBE_CAP_{MAX_PROBES}"
        print(json.dumps(plan, ensure_ascii=False))
        return 3
    if not args.paid:
        print(json.dumps(plan, ensure_ascii=False))
        return 0
    missing = [name for name in PAID_ENV if not str(os.environ.get(name) or "").strip()]
    if missing:
        raise SystemExit("paid reference isolation runs only inside the pipeline paid step: "
                         f"paid_stage.sh {episode} --isolate-reference {args.task_key} (missing {','.join(missing)})")
    client = _client()
    if client.image_provider() != client.PROVIDER_HOPSAPI:
        raise SystemExit("reference isolation probes are HopsAPI-only (resolved image provider is not hopsapi)")
    if not os.environ.get(client.required_key_env(client.PROVIDER_HOPSAPI), "").strip():
        raise SystemExit(f"{client.required_key_env(client.PROVIDER_HOPSAPI)} is not set")
    report = isolate(episode=episode, task=task, transaction_dir=transaction_dir, declaration_path=declaration,
                     transport=HopsapiProbeTransport(), tries=args.tries)
    report["zero_cost_424_attempts"] = rejections
    out = args.out or transaction_dir.parent.parent / "reference_isolation" / episode / f"{args.task_key}.json"
    atomic_json(out, report)
    print(json.dumps({k: report[k] for k in ("verdict", "declaration", "task_key")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
