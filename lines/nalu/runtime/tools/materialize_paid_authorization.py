#!/usr/bin/env python3
"""Materialise the paid-submission authority fields from a standing supervisor order.

Resolves open decision **D-11**.

The problem
-----------
Every nalu paid submit needs authority the compilers deliberately refuse to
fabricate.  ``tools/submit_giggle_image_manifest.py::validate_submission_authority``
(:159-178) demands, *only on the real paid path* — ``--precheck-only`` skips it, so a
green precheck is not proof a paid run will start:

* manifest ``provider_post_allowed is True``
* manifest ``maximum_new_submissions >= len(selected tasks)``
* manifest ``authorization_ref`` non-empty
* every selected task ``status == "READY_TO_SUBMIT"``,
  ``provider_post_allowed is True``, ``maximum_new_submissions == 1``
* **exactly one** registered ``machine_gate_reports`` entry whose ``gate_id`` is
  ``GIGGLE-REROLL-COST-GUARD`` and whose ``reviewed_manifest_sha256`` equals the
  SHA256 of the manifest file *as submitted*.

``tools/submit_giggle_character_asset_plan.py`` additionally requires
``quality == "pro"`` and every ``machine_gate_reports`` entry ``status == PASS``.
``tools/submit_giggle_video_manifest_v2.py`` routes its authority through
``tools/production_video_submission_gate.py`` plus ``validate_gate`` on every
registered report.

What this tool does
-------------------
1. Reads a deployment-private ``SUPERVISOR_ORDERS.json`` supplied with ``--orders``
   and locates ``--order-seq``.  The caller must also name the line owner and the
   latest sequence it observed.  **Refuses** stale, duplicate or malformed order
   files; the public engine checkout is never an authority source.
2. Validates the active order and its source receipt rather than trusting prose:
   issuer, verbatim text, receipt bytes, exact episode list, per-episode cap,
   rights declaration and an explicit ``paid_requests_allowed: true`` decision
   must all agree.  Any mismatch is a refusal, not a warning.
3. Checks every model named by the manifest/plan.  A video manifest must be
   ``seedance-2.0-pro`` on every task; any other ``seedance-*`` variant, or
   ``MiniMax-H3`` anywhere, is a refusal (order condition 1).  Image batches keep
   ``gpt-image-2-pro`` — the engine's only image route — which condition 1 does not
   govern; any other image model is refused unless ``--allow-image-model`` is given.
4. Prices the batch (images ``--image-credits`` each, video
   ``--video-credits-per-second`` × total ``duration_seconds``) and runs
   ``runtime/tools/nalu_budget_ledger.py --check`` offline.  Planned credits over the
   cap, or a non-PASS ledger verdict, is a refusal.
5. Writes the materialised copy with the authority fields set, then computes that
   file's SHA256 and **actually runs** ``tools/reroll_cost_guard.py`` against
   ``configs/reroll_cost_guard_policy_v1_20260716.json`` and the live nalu ledger,
   wrapping its verbatim result in a ``GIGGLE-REROLL-COST-GUARD`` gate report bound
   to that exact SHA.  The guard's own output carries neither ``gate_id`` nor
   ``reviewed_manifest_sha256`` nor a bare ``PASS`` status (it returns
   ``PASS_AUTO_REROLL_ALLOWED``), so the wrapper supplies exactly those three
   binding fields and embeds the raw result plus the argv used, unedited, as
   evidence.  The guard is run as a **cost-envelope probe**, not as a claim that a
   reroll happened: ``guard_semantics`` and ``rerolls_consumed: 0`` say so in the
   report.
6. Re-imports the submitters' own validators (pure functions, no network, no POST)
   and asserts they now pass, recording the verdict.

Money safety
------------
No network call, no POST, no ``GIGGLE_API_KEY`` read.  Writes only the materialised
copies and its own reports; the source manifest/plan is left untouched unless
``--in-place`` is passed.  ``provider_post_allowed: true`` in a file is still only
one of the pipeline's two locks — ``qingshan.json`` ``generation.paid_requests_enabled``
and the orchestrator's ``--paid`` remain independently required.

CLI
---
    materialize_paid_authorization.py \
      --episode E01 --stage S3 --order-seq 1 --expected-latest-seq 1 \
      --line-owner-id <deployment owner id> \
      --manifest <image or video manifest .json> \
      [--plan <character_asset_plan.json>] \
      [--out-dir <dir>]            default: alongside each input
      [--suffix _PAID_AUTHORIZED]  materialised-copy filename suffix
      [--in-place]                 overwrite the inputs instead of copying
      [--task-key K]…              price/authorise only these task keys
      [--cap 8000] [--image-credits 11] [--video-credits-per-second 20]
      --orders <private SUPERVISOR_ORDERS.json> [--policy <reroll policy json>]
      [--ledger <budget ledger json>] [--engine-root …] [--python …]
      [--allow-image-model] [--report <path>]

Exit codes: 0 authority materialised and self-verified, 2 bad input,
5 refused (order missing / condition mismatch / wrong model / over cap),
6 materialised but the submitter's own validator still refuses.
"""

from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_ENGINE_ROOT = Path(f"{_np.ENGINE_ROOT}")
# 2026-09-22 (device-2 finding #21): a StoryClaw project engine is a worktree without its own
# .qingshan-venv; the interpreter is selected by NALU_VENV_PYTHON (installer contract), else the
# interpreter already running the pipeline.
_ENGINE_VENV_PYTHON = DEFAULT_ENGINE_ROOT / ".qingshan-venv/bin/python"
DEFAULT_PYTHON = Path(
    os.environ.get("NALU_VENV_PYTHON")
    or (str(_ENGINE_VENV_PYTHON) if _ENGINE_VENV_PYTHON.exists() else sys.executable)
)
DEFAULT_POLICY = DEFAULT_ENGINE_ROOT / "configs/reroll_cost_guard_policy_v1_20260716.json"
RUNTIME_ROOT = Path(f"{_np.RUNTIME_ROOT}")
DEFAULT_LEDGER = RUNTIME_ROOT / "runtime/budget/ledger.json"
BUDGET_TOOL = Path(f"{_np.TOOLS_DIR}") / "nalu_budget_ledger.py"  # port fix 2026-09-15

GUARD_GATE_ID = "GIGGLE-REROLL-COST-GUARD"
SD2 = "seedance-2.0-pro"
IMAGE_MODEL = "gpt-image-2-pro"
FORBIDDEN_MODEL = re.compile(
    r"(seedance-2\.0-(?!pro\b)[a-z0-9.]+|seedance-2\.0\b(?!-pro)|minimax-h3|\bh3\b)",
    re.IGNORECASE,
)
ORDERS_SCHEMA = "supervisor_orders_v1"
RECEIPT_SCHEMA = "qingshan.line_owner_order_source_receipt.v1"
PAID_DECISION_KIND = "PAID_PRODUCTION_AUTHORIZATION"
REQUIRED_CONDITIONS = {
    "VIDEO_MODEL_SD2_ONLY",
    "PAID_REQUESTS_EXPLICITLY_AUTHORIZED",
    "RIGHTS_BASIS_DECLARED",
}
CAP_CONDITION_IDS = {"BUDGET_CAP_PER_EPISODE", "BUDGET_CAP_8000_PER_EPISODE"}


class Refused(RuntimeError):
    """The standing order does not authorise this submission."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _required_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise Refused(f"{label}_MISSING")
    return text


def _private_path(path: Path, *, engine_root: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(engine_root.expanduser().resolve())
    except ValueError:
        return resolved
    raise Refused(f"{label}_MUST_BE_OUTSIDE_PUBLIC_ENGINE_ROOT:{resolved}")


def _source_receipt(order: dict[str, Any], *, expected_owner: str,
                    engine_root: Path, require_private: bool) -> dict[str, Any]:
    binding = order.get("source_receipt")
    if not isinstance(binding, dict):
        raise Refused("ORDER_SOURCE_RECEIPT_BINDING_MISSING")
    raw_path = _required_text(binding.get("path"), "ORDER_SOURCE_RECEIPT_PATH")
    receipt_path = Path(raw_path).expanduser()
    if not receipt_path.is_absolute():
        raise Refused("ORDER_SOURCE_RECEIPT_PATH_MUST_BE_ABSOLUTE")
    receipt_path = (_private_path(receipt_path, engine_root=engine_root,
                                  label="ORDER_SOURCE_RECEIPT")
                    if require_private else receipt_path.resolve())
    if not receipt_path.is_file():
        raise Refused(f"ORDER_SOURCE_RECEIPT_FILE_MISSING:{receipt_path}")
    expected_sha = _required_text(binding.get("sha256"), "ORDER_SOURCE_RECEIPT_SHA256")
    actual_sha = sha256_file(receipt_path)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or expected_sha != actual_sha:
        raise Refused(f"ORDER_SOURCE_RECEIPT_SHA256_MISMATCH:{expected_sha}!={actual_sha}")
    receipt = load_json(receipt_path)
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        raise Refused(f"ORDER_SOURCE_RECEIPT_SCHEMA_INVALID:{(receipt or {}).get('schema') if isinstance(receipt, dict) else type(receipt).__name__}")
    if receipt.get("status") != "CONFIRMED":
        raise Refused(f"ORDER_SOURCE_RECEIPT_NOT_CONFIRMED:{receipt.get('status')}")
    if str(receipt.get("issued_by") or "") != expected_owner:
        raise Refused("ORDER_SOURCE_RECEIPT_ISSUER_MISMATCH")
    receipt_seq = receipt.get("order_seq")
    if isinstance(receipt_seq, bool) or not isinstance(receipt_seq, int) \
            or receipt_seq != order.get("seq"):
        raise Refused("ORDER_SOURCE_RECEIPT_SEQ_MISMATCH")
    if str(receipt.get("order_id") or "") != str(order.get("id") or ""):
        raise Refused("ORDER_SOURCE_RECEIPT_ID_MISMATCH")
    if str(receipt.get("verbatim") or "") != str(order.get("order") or ""):
        raise Refused("ORDER_SOURCE_RECEIPT_VERBATIM_MISMATCH")
    recorded_at = _required_text(receipt.get("recorded_at_utc"),
                                 "ORDER_SOURCE_RECEIPT_RECORDED_AT_UTC")
    return {"path": str(receipt_path), "sha256": actual_sha,
            "schema": RECEIPT_SCHEMA, "status": "CONFIRMED",
            "recorded_at_utc": recorded_at}


# --------------------------------------------------------------------------- #
# order
# --------------------------------------------------------------------------- #
def read_order(orders_path: Path, seq: int, episode: str, cap: int, *,
               expected_owner: str, expected_latest_seq: int,
               paid_stage: str | None = None,
               engine_root: Path = DEFAULT_ENGINE_ROOT,
               require_private: bool = True) -> dict[str, Any]:
    expected_owner = _required_text(expected_owner, "LINE_OWNER_ID")
    if expected_latest_seq < 1 or seq < 1:
        raise Refused("ORDER_SEQ_AND_EXPECTED_LATEST_SEQ_MUST_BE_POSITIVE")
    if not re.fullmatch(r"E\d+", episode):
        raise Refused(f"EPISODE_UNPARSEABLE:{episode}")
    orders_path = ( _private_path(orders_path, engine_root=engine_root,
                                  label="SUPERVISOR_ORDERS")
                   if require_private else orders_path.expanduser().resolve())
    if not orders_path.is_file():
        raise Refused(f"SUPERVISOR_ORDERS_FILE_MISSING:{orders_path}")
    orders = load_json(orders_path)
    if not isinstance(orders, dict) or orders.get("_schema") != ORDERS_SCHEMA:
        raise Refused(f"SUPERVISOR_ORDERS_SCHEMA_INVALID:{(orders or {}).get('_schema') if isinstance(orders, dict) else type(orders).__name__}")
    rows = orders.get("orders")
    if not isinstance(rows, list):
        raise Refused("SUPERVISOR_ORDERS_ROWS_NOT_A_LIST")
    seqs: list[int] = []
    for row in rows:
        if not isinstance(row, dict) or isinstance(row.get("seq"), bool) or not isinstance(row.get("seq"), int):
            raise Refused("SUPERVISOR_ORDER_SEQ_INVALID")
        seqs.append(row["seq"])
    if len(seqs) != len(set(seqs)):
        raise Refused("SUPERVISOR_ORDER_SEQ_DUPLICATE")
    latest = orders.get("latest_order_seq")
    if isinstance(latest, bool) or not isinstance(latest, int):
        raise Refused("SUPERVISOR_ORDERS_LATEST_SEQ_INVALID")
    if latest != expected_latest_seq:
        raise Refused(f"SUPERVISOR_ORDERS_LATEST_SEQ_MISMATCH:{latest}!={expected_latest_seq}")
    if (max(seqs) if seqs else 0) != latest:
        raise Refused("SUPERVISOR_ORDERS_LATEST_SEQ_DOES_NOT_MATCH_ROWS")
    match = [row for row in rows if row["seq"] == seq]
    if len(match) != 1:
        raise Refused(
            f"ORDER_SEQ_{seq}_DOES_NOT_EXIST (present: "
            f"{sorted(seqs)})"
        )
    order = match[0]
    order_id = _required_text(order.get("id"), "ORDER_ID")
    if order.get("status") != "active":
        raise Refused(f"ORDER_NOT_ACTIVE:{order.get('status')}")
    if str(order.get("issued_by") or "") != expected_owner:
        raise Refused(f"ORDER_ISSUER_MISMATCH:{order.get('issued_by')}!={expected_owner}")
    verbatim = _required_text(order.get("order"), "ORDER_VERBATIM")
    receipt = _source_receipt(order, expected_owner=expected_owner,
                              engine_root=engine_root, require_private=require_private)
    decision = order.get("decision")
    if not isinstance(decision, dict) or decision.get("kind") != PAID_DECISION_KIND:
        raise Refused(f"ORDER_PAID_DECISION_KIND_INVALID:{(decision or {}).get('kind') if isinstance(decision, dict) else type(decision).__name__}")
    if decision.get("paid_requests_allowed") is not True:
        raise Refused("ORDER_DOES_NOT_EXPLICITLY_AUTHORIZE_PAID_REQUESTS")
    paid_stages = decision.get("paid_stages")
    if (not isinstance(paid_stages, list) or not paid_stages
            or any(stage not in {"S3", "S4", "S5", "S6"} for stage in paid_stages)):
        raise Refused("ORDER_PAID_STAGES_MUST_BE_EXPLICIT_SUBSET_OF_S3_TO_S6")
    if paid_stage is not None and paid_stage not in paid_stages:
        raise Refused(f"ORDER_DOES_NOT_AUTHORIZE_PAID_STAGE:{paid_stage}")
    scope = decision.get("episode_scope")
    if not isinstance(scope, list) or not scope or any(not isinstance(x, str) for x in scope):
        raise Refused("ORDER_EPISODE_SCOPE_MUST_BE_NONEMPTY_EXPLICIT_LIST")
    if episode not in scope:
        raise Refused(f"EPISODE_OUT_OF_ORDER_SCOPE:{episode}")
    if isinstance(decision.get("budget_cap_credits_per_episode"), bool) or \
            decision.get("budget_cap_credits_per_episode") != cap:
        raise Refused(f"ORDER_CAP_MISMATCH:{decision.get('budget_cap_credits_per_episode')}!={cap}")
    if str(decision.get("video_model") or "") != SD2:
        raise Refused("ORDER_VIDEO_MODEL_DOES_NOT_NAME_seedance-2.0-pro")
    rights_basis = _required_text(decision.get("rights_basis"), "ORDER_RIGHTS_BASIS")
    if str(decision.get("rights_declared_by") or "") != expected_owner:
        raise Refused("ORDER_RIGHTS_DECLARER_MISMATCH")
    conditions = order.get("conditions")
    if not isinstance(conditions, list) or any(not isinstance(row, dict) for row in conditions):
        raise Refused("ORDER_CONDITIONS_INVALID")
    condition_ids = {str(row.get("id") or "") for row in conditions}
    missing = sorted(REQUIRED_CONDITIONS - condition_ids)
    if missing:
        raise Refused(f"ORDER_MISSING_REQUIRED_CONDITIONS:{','.join(missing)}")
    cap_rows = [row for row in conditions if row.get("id") in CAP_CONDITION_IDS]
    if len(cap_rows) != 1:
        raise Refused("ORDER_REQUIRES_EXACTLY_ONE_BUDGET_CAP_CONDITION")
    cap_condition = cap_rows[0]
    declared_caps = {int(value) for value in re.findall(r"\d{3,6}", str(cap_condition.get("text") or ""))}
    if cap not in declared_caps:
        raise Refused(
            f"ORDER_CAP_MISMATCH: --cap {cap} is not the cap the order declares "
            f"({sorted(declared_caps)})"
        )
    sd2_condition = next(
        row for row in conditions if row.get("id") == "VIDEO_MODEL_SD2_ONLY"
    )
    if SD2 not in str(sd2_condition.get("text") or ""):
        raise Refused("ORDER_SD2_CONDITION_DOES_NOT_NAME_seedance-2.0-pro")
    return {
        "seq": seq,
        "id": order_id,
        "type": order.get("type"),
        "ts_pdt": order.get("ts_pdt"),
        "issued_by": expected_owner,
        "verbatim": verbatim,
        "orders_file": str(orders_path),
        "orders_file_sha256": sha256_file(orders_path),
        "latest_order_seq": latest,
        "source_receipt": receipt,
        "condition_ids": sorted(condition_ids),
        "episode_scope": list(scope),
        "cap_credits": cap,
        "rights_basis": rights_basis,
        "rights_declared_by": expected_owner,
        "rights_scope": str(decision.get("rights_scope") or "").strip(),
        "publication_allowed": decision.get("publication_allowed") is True,
        "paid_requests_allowed": True,
        "paid_stages": list(paid_stages),
        "authorized_stage": paid_stage,
    }


# --------------------------------------------------------------------------- #
# model + pricing
# --------------------------------------------------------------------------- #
def is_video(document: dict[str, Any]) -> bool:
    schema = str(document.get("schema") or "")
    if "video" in schema:
        return True
    return any(task.get("duration_seconds") for task in document.get("tasks") or [])


def check_models(document: dict[str, Any], tasks: list[dict[str, Any]], *,
                 video: bool, allow_image_model: bool) -> dict[str, Any]:
    named = [str(document.get("model") or "")] + [str(task.get("model") or "") for task in tasks]
    named += [str((document.get("format_contract") or {}).get("model") or "")]
    named = [value for value in named if value]
    for value in named:
        if FORBIDDEN_MODEL.search(value):
            raise Refused(f"MODEL_FORBIDDEN_BY_ORDER_CONDITION_1:{value}")
    if video:
        offenders = sorted({
            str(task.get("model") or "MISSING") for task in tasks
            if str(task.get("model") or "") != SD2
        })
        if offenders:
            raise Refused(f"VIDEO_MODEL_IS_NOT_{SD2}:{','.join(offenders)}")
    else:
        offenders = sorted({
            str(task.get("model") or "MISSING") for task in tasks
            if str(task.get("model") or "") != IMAGE_MODEL
        })
        if offenders and not allow_image_model:
            raise Refused(
                f"IMAGE_MODEL_IS_NOT_{IMAGE_MODEL}:{','.join(offenders)} "
                "(pass --allow-image-model only with a named authorisation)"
            )
    return {"models_named": sorted(set(named)), "video": video, "sd2_only_enforced": video}


def price(tasks: list[dict[str, Any]], *, video: bool, image_credits: int,
          video_credits_per_second: int) -> dict[str, Any]:
    if video:
        seconds = sum(float(task.get("duration_seconds") or 0) for task in tasks)
        return {
            "basis": "VIDEO_SECONDS", "seconds": seconds,
            "credits_per_second": video_credits_per_second,
            "planned_credits": int(round(seconds * video_credits_per_second)),
            "task_count": len(tasks),
        }
    return {
        "basis": "IMAGE_TASKS", "task_count": len(tasks),
        "credits_per_task": image_credits,
        "planned_credits": len(tasks) * image_credits,
    }


def budget_check(python: Path, episode: str, planned: int, cap: int,
                 ledger: Path) -> dict[str, Any]:
    argv = [
        str(python), str(BUDGET_TOOL), "--check", "--episode", episode,
        "--planned-credits", str(planned), "--cap", str(cap), "--ledger", str(ledger),
    ]
    completed = subprocess.run(argv, capture_output=True, text=True,
                               cwd=str(DEFAULT_ENGINE_ROOT))
    if completed.returncode != 0 and "--ledger" in completed.stderr:
        argv = [value for value in argv if value not in {"--ledger", str(ledger)}]
        completed = subprocess.run(argv, capture_output=True, text=True,
                                   cwd=str(DEFAULT_ENGINE_ROOT))
    try:
        verdict = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        verdict = {"status": "UNPARSEABLE", "stdout": completed.stdout[-1000:],
                   "stderr": completed.stderr[-1000:]}
    return {"argv": argv, "returncode": completed.returncode, "verdict": verdict}


# --------------------------------------------------------------------------- #
# cost guard
# --------------------------------------------------------------------------- #
def run_cost_guard(python: Path, engine_root: Path, *, policy: Path, ledger: Path,
                   probe_id: str, total_paid_tasks: int, out_raw: Path) -> dict[str, Any]:
    argv = [
        str(python), str(engine_root / "tools/reroll_cost_guard.py"),
        "--policy", str(policy), "--ledger", str(ledger),
        "--shot-id", probe_id,
        "--reroll-number", "1",
        "--failure-tier", "BLOCK",
        "--failure-reason", "PAID_SUBMISSION_COST_ENVELOPE_PROBE",
        "--failure-class", "CANDIDATE_QA_FAILURE",
        "--total-paid-tasks", str(max(total_paid_tasks, 1)),
        "--out", str(out_raw),
    ]
    completed = subprocess.run(argv, capture_output=True, text=True, cwd=str(engine_root))
    raw = load_json(out_raw) if out_raw.is_file() else {}
    return {
        "argv": argv, "returncode": completed.returncode,
        "raw_result_path": str(out_raw), "raw_result": raw,
        "stdout": completed.stdout.strip()[-2000:],
        "stderr": completed.stderr.strip()[-2000:],
    }


def guard_gate_report(*, episode: str, manifest_path: Path, manifest_sha: str,
                      guard: dict[str, Any], order: dict[str, Any],
                      pricing: dict[str, Any], budget: dict[str, Any],
                      policy: Path, ledger: Path) -> dict[str, Any]:
    raw = guard.get("raw_result") or {}
    guard_pass = str(raw.get("status") or "").startswith("PASS_")
    within_cap = pricing["planned_credits"] <= order["cap_credits"]
    ledger_pass = str((budget.get("verdict") or {}).get("status") or "") == "PASS"
    return {
        "schema": "qingshan.reroll_cost_guard_gate_report.v1",
        "gate_id": GUARD_GATE_ID,
        "component": "GIGGLE_PAID_SUBMISSION_COST_ENVELOPE",
        "status": "PASS" if (guard_pass and within_cap and ledger_pass) else "FAIL",
        "episode": episode,
        "reviewed_manifest": str(manifest_path),
        "reviewed_manifest_sha256": manifest_sha,
        "guard_semantics": (
            "COST_ENVELOPE_PROBE_NOT_AN_ACTUAL_REROLL: tools/reroll_cost_guard.py was run "
            "with reroll_number=1 and failure_tier=BLOCK to prove the policy would still "
            "permit one paid reroll after this batch. No reroll is being requested and none "
            "is consumed by this submission."
        ),
        "rerolls_consumed": 0,
        "authorization_ref": order["id"],
        "authorization_order": order,
        "policy": {"path": str(policy), "sha256": sha256_file(policy)},
        "ledger": {"path": str(ledger),
                   "sha256": sha256_file(ledger) if ledger.is_file() else None},
        "cost_envelope": {
            **pricing,
            "cap_credits": order["cap_credits"],
            "within_cap": within_cap,
        },
        "budget_ledger_check": budget,
        "reroll_cost_guard_run": {
            "argv": guard["argv"], "returncode": guard["returncode"],
            "raw_result_path": guard["raw_result_path"],
            "raw_result": raw,
            "note": (
                "reroll_cost_guard.py emits neither gate_id nor reviewed_manifest_sha256 and "
                "its PASS status is 'PASS_AUTO_REROLL_ALLOWED', so this wrapper supplies only "
                "those three binding fields required by "
                "submit_giggle_image_manifest.validate_submission_authority. The raw result "
                "above is the tool's verbatim output."
            ),
        },
        "failures": [] if (guard_pass and within_cap and ledger_pass) else [
            row for row in [
                None if guard_pass else {"check": "reroll_cost_guard",
                                         "reason": raw.get("status"),
                                         "guard_failures": raw.get("failures")},
                None if within_cap else {"check": "cost_envelope",
                                         "reason": "PLANNED_CREDITS_EXCEED_CAP"},
                None if ledger_pass else {"check": "nalu_budget_ledger",
                                          "reason": (budget.get("verdict") or {}).get("status")},
            ] if row
        ],
        "recorded_at": utc_now(),
        "recorded_by": "runtime/tools/materialize_paid_authorization.py",
    }


# --------------------------------------------------------------------------- #
# materialisation
# --------------------------------------------------------------------------- #
def target_path(source: Path, out_dir: Path | None, suffix: str, in_place: bool) -> Path:
    if in_place:
        return source
    directory = out_dir or source.parent
    return directory / f"{source.stem}{suffix}{source.suffix}"


def materialise_manifest(document: dict[str, Any], tasks: list[dict[str, Any]],
                         *, order: dict[str, Any], guard_report_path: Path,
                         episode: str) -> dict[str, Any]:
    document["authorization_ref"] = order["id"]
    document["provider_post_allowed"] = True
    document["maximum_new_submissions"] = max(len(tasks), 1)
    document["paid_authorization"] = {
        "materialised_by": "runtime/tools/materialize_paid_authorization.py",
        "materialised_at": utc_now(),
        "order_seq": order["seq"], "order_id": order["id"],
        "latest_order_seq": order["latest_order_seq"],
        "issued_by": order["issued_by"],
        "paid_stages": order["paid_stages"],
        "authorized_stage": order.get("authorized_stage"),
        "orders_file": order["orders_file"],
        "orders_file_sha256": order["orders_file_sha256"],
        "source_receipt": order["source_receipt"],
        "episode": episode,
        "second_lock_still_required": (
            "qingshan.json generation.paid_requests_enabled must be true AND the orchestrator "
            "must be run with --paid. This field authorises nothing on its own."
        ),
    }
    keys = {task.get("task_key") for task in tasks}
    for task in document.get("tasks") or []:
        if task.get("task_key") not in keys:
            continue
        task["status"] = "READY_TO_SUBMIT"
        task["provider_post_allowed"] = True
        task["maximum_new_submissions"] = 1
        task["authorization_ref"] = order["id"]
        task.pop("blocking_note", None)
    reports = [
        value for value in (document.get("machine_gate_reports") or [])
        if Path(str(value)).name != guard_report_path.name
    ]
    reports.append(str(guard_report_path))
    document["machine_gate_reports"] = reports
    return document


def materialise_plan(plan: dict[str, Any], *, order: dict[str, Any],
                     guard_report_path: Path, episode: str) -> dict[str, Any]:
    rows = plan.get("new_asset_groups") or []
    plan["authorization_ref"] = order["id"]
    plan["provider_post_allowed"] = True
    plan["maximum_new_submissions"] = max(len(rows), 1)
    plan["paid_authorization"] = {
        "materialised_by": "runtime/tools/materialize_paid_authorization.py",
        "materialised_at": utc_now(),
        "order_seq": order["seq"], "order_id": order["id"],
        "latest_order_seq": order["latest_order_seq"],
        "issued_by": order["issued_by"],
        "paid_stages": order["paid_stages"],
        "authorized_stage": order.get("authorized_stage"),
        "orders_file": order["orders_file"],
        "orders_file_sha256": order["orders_file_sha256"],
        "source_receipt": order["source_receipt"], "episode": episode,
    }
    for row in rows:
        row["status"] = "READY_TO_SUBMIT"
        row["provider_post_allowed"] = True
        row["maximum_new_submissions"] = 1
        row["authorization_ref"] = order["id"]
    reports = [
        value for value in (plan.get("machine_gate_reports") or [])
        if Path(str(value)).name != guard_report_path.name
    ]
    reports.append(str(guard_report_path))
    plan["machine_gate_reports"] = reports
    return plan


# --------------------------------------------------------------------------- #
# self-verification with the submitter's own validator
# --------------------------------------------------------------------------- #
def load_submitter(engine_root: Path, name: str):
    path = engine_root / "tools" / name
    if str(engine_root) not in sys.path:
        sys.path.insert(0, str(engine_root))
    spec = importlib.util.spec_from_file_location(f"nalu_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_image_authority(engine_root: Path, manifest_path: Path,
                           task_keys: list[str] | None) -> dict[str, Any]:
    module = load_submitter(engine_root, "submit_giggle_image_manifest.py")
    manifest = load_json(manifest_path)
    tasks = manifest.get("tasks") or []
    if task_keys:
        tasks = [task for task in tasks if task.get("task_key") in set(task_keys)]
    try:
        gates = [module.validate_gate(value) for value in manifest.get("machine_gate_reports") or []]
        module.validate_submission_authority(manifest, tasks, gates, manifest_path)
    except Exception as exc:  # the validator raises ValueError on refusal
        return {"validator": "submit_giggle_image_manifest.validate_submission_authority",
                "status": "REFUSED", "reason": f"{type(exc).__name__}: {exc}"}
    return {"validator": "submit_giggle_image_manifest.validate_submission_authority",
            "status": "PASS", "selected_tasks": len(tasks)}


def verify_plan_authority(engine_root: Path, plan_path: Path) -> dict[str, Any]:
    plan = load_json(plan_path)
    failures = []
    if plan.get("quality") != "pro":
        failures.append("PLAN_QUALITY_NOT_PRO")
    if not plan.get("new_asset_groups"):
        failures.append("PLAN_HAS_NO_ROWS")
    if not plan.get("authorization_ref"):
        failures.append("PLAN_AUTHORIZATION_REF_EMPTY")
    for value in plan.get("machine_gate_reports") or []:
        path = Path(value) if Path(value).is_absolute() else engine_root / value
        if not path.is_file():
            failures.append(f"GATE_MISSING:{value}")
        elif load_json(path).get("status") != "PASS":
            failures.append(f"GATE_NOT_PASS:{value}")
    for row in plan.get("new_asset_groups") or []:
        prompt = Path(row.get("prompt_file") or "")
        if not prompt.is_absolute():
            prompt = engine_root / prompt
        if not prompt.is_file() or sha256_file(prompt) != row.get("prompt_sha256"):
            failures.append(f"PROMPT_BINDING:{row.get('id')}")
        if row.get("status") != "READY_TO_SUBMIT":
            failures.append(f"ROW_NOT_READY:{row.get('id')}")
    return {"validator": "submit_giggle_character_asset_plan.py main() preconditions",
            "status": "PASS" if not failures else "REFUSED", "failures": failures}


# --------------------------------------------------------------------------- #
def process(source: Path, *, kind: str, args: argparse.Namespace,
            order: dict[str, Any], python: Path, engine_root: Path,
            policy: Path, ledger: Path, out_dir: Path | None) -> dict[str, Any]:
    document = load_json(source)
    destination = target_path(source, out_dir, args.suffix, args.in_place)
    guard_dir = destination.parent / f"{destination.stem}_authority"
    guard_report_path = guard_dir / f"{args.episode}_GIGGLE_REROLL_COST_GUARD_GATE.json"
    guard_raw_path = guard_dir / f"{args.episode}_reroll_cost_guard_raw.json"

    if kind == "plan":
        rows = document.get("new_asset_groups") or []
        pricing = price(rows, video=False, image_credits=args.image_credits,
                        video_credits_per_second=args.video_credits_per_second)
        pricing["basis"] = "IDENTITY_PLAN_ROWS"
        model_report = {"models_named": [IMAGE_MODEL], "video": False,
                        "note": "submit_giggle_character_asset_plan.py hardcodes "
                                "gpt-image-2-pro / 2K at its call site (:219,:225)."}
        video = False
    else:
        all_tasks = document.get("tasks") or []
        if not all_tasks:
            raise Refused("MANIFEST_HAS_ZERO_TASKS")
        tasks = all_tasks
        if args.task_key:
            requested = set(args.task_key)
            unknown = sorted(requested - {task.get("task_key") for task in all_tasks})
            if unknown:
                raise Refused(f"UNKNOWN_TASK_KEYS:{','.join(unknown)}")
            tasks = [task for task in all_tasks if task.get("task_key") in requested]
        video = is_video(document)
        model_report = check_models(document, tasks, video=video,
                                    allow_image_model=args.allow_image_model)
        pricing = price(tasks, video=video, image_credits=args.image_credits,
                        video_credits_per_second=args.video_credits_per_second)

    if pricing["planned_credits"] > order["cap_credits"]:
        raise Refused(
            f"PLANNED_CREDITS_EXCEED_CAP:{pricing['planned_credits']}>{order['cap_credits']}"
        )
    budget = budget_check(python, args.episode, pricing["planned_credits"],
                          order["cap_credits"], ledger)
    if str((budget.get("verdict") or {}).get("status") or "") != "PASS":
        raise Refused(
            "NALU_BUDGET_LEDGER_CHECK_NOT_PASS:"
            + str((budget.get("verdict") or {}).get("status"))
            + " " + json.dumps((budget.get("verdict") or {}).get("failures") or [],
                               ensure_ascii=False)
        )

    if kind == "plan":
        document = materialise_plan(document, order=order,
                                    guard_report_path=guard_report_path,
                                    episode=args.episode)
    else:
        document = materialise_manifest(document, tasks, order=order,
                                        guard_report_path=guard_report_path,
                                        episode=args.episode)
    dump_json(destination, document)
    manifest_sha = sha256_file(destination)

    guard = run_cost_guard(
        python, engine_root, policy=policy, ledger=ledger,
        probe_id=str(document.get("batch_id") or document.get("episode") or args.episode),
        total_paid_tasks=pricing.get("task_count") or 1, out_raw=guard_raw_path,
    )
    report = guard_gate_report(
        episode=args.episode, manifest_path=destination, manifest_sha=manifest_sha,
        guard=guard, order=order, pricing=pricing, budget=budget,
        policy=policy, ledger=ledger,
    )
    dump_json(guard_report_path, report)

    verification: dict[str, Any]
    if kind == "plan":
        verification = verify_plan_authority(engine_root, destination)
    elif not video:
        verification = verify_image_authority(engine_root, destination, args.task_key or None)
    else:
        verification = {
            "validator": "submit_giggle_video_manifest_v2 authority",
            "status": "NOT_APPLICABLE_AUTHORITY_LIVES_IN_BACKLOTOS_GATE",
            "note": ("submit_giggle_video_manifest_v2.py routes its authority through "
                     "tools/production_video_submission_gate.py and validate_gate on every "
                     "registered report; there is no standalone validate_submission_authority "
                     "to call. Run the submitter with --precheck-only to exercise it."),
        }
    return {
        "kind": kind, "source": str(source), "source_sha256": sha256_file(source),
        "materialised": str(destination), "materialised_sha256": manifest_sha,
        "is_video": video, "models": model_report, "cost_envelope": pricing,
        "budget_ledger_check": budget,
        "guard_gate_report": str(guard_report_path),
        "guard_gate_status": report["status"],
        "guard_raw_status": (guard.get("raw_result") or {}).get("status"),
        "authority_fields": {
            "authorization_ref": document.get("authorization_ref"),
            "provider_post_allowed": document.get("provider_post_allowed"),
            "maximum_new_submissions": document.get("maximum_new_submissions"),
            "machine_gate_reports": document.get("machine_gate_reports"),
        },
        "self_verification": verification,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--episode", required=True)
    parser.add_argument("--stage", required=True, choices=("S3", "S4", "S5", "S6"))
    parser.add_argument("--order-seq", type=int, required=True)
    parser.add_argument("--expected-latest-seq", type=int, required=True,
                        help="latest_order_seq observed by the line owner interface")
    parser.add_argument("--line-owner-id", required=True,
                        help="exact issued_by identity configured for this deployment")
    parser.add_argument("--manifest")
    parser.add_argument("--plan")
    parser.add_argument("--out-dir")
    parser.add_argument("--suffix", default="_PAID_AUTHORIZED")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--task-key", action="append", default=[])
    parser.add_argument("--cap", type=int, default=8000)
    parser.add_argument("--image-credits", type=int, default=11)
    parser.add_argument("--video-credits-per-second", type=int, default=20)
    parser.add_argument("--orders", required=True,
                        help="deployment-private SUPERVISOR_ORDERS.json (outside engine checkout)")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--engine-root", default=str(DEFAULT_ENGINE_ROOT))
    parser.add_argument("--python", default=str(DEFAULT_PYTHON))
    parser.add_argument("--allow-image-model", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()

    if not args.manifest and not args.plan:
        raise SystemExit("at least one of --manifest / --plan is required")
    engine_root = Path(args.engine_root).resolve()
    # Never resolve() the interpreter: .qingshan-venv/bin/python is a symlink and
    # resolving it silently leaves the virtualenv.
    python = Path(args.python)
    policy = Path(args.policy).resolve()
    ledger = Path(args.ledger).resolve()
    if not policy.is_file():
        raise SystemExit(f"--policy not found: {policy}")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else None

    envelope: dict[str, Any] = {
        "schema": "nalu.paid_authorization_materialisation_report.v2",
        "episode": args.episode, "stage": args.stage, "order_seq": args.order_seq,
        "recorded_at": utc_now(),
        "network_calls_made": 0,
        "giggle_api_key_read": False,
        "giggle_api_key_present_in_env": bool(os.environ.get("GIGGLE_API_KEY", "").strip()),
        "results": [],
    }
    try:
        order = read_order(
            Path(args.orders), args.order_seq, args.episode, args.cap,
            expected_owner=args.line_owner_id,
            expected_latest_seq=args.expected_latest_seq,
            paid_stage=args.stage,
            engine_root=engine_root,
            require_private=True,
        )
        envelope["order"] = order
        for flag, kind in (("plan", "plan"), ("manifest", "manifest")):
            value = getattr(args, flag)
            if not value:
                continue
            source = Path(value).resolve()
            if not source.is_file():
                raise Refused(f"{flag.upper()}_NOT_FOUND:{source}")
            envelope["results"].append(process(
                source, kind=kind, args=args, order=order, python=python,
                engine_root=engine_root, policy=policy, ledger=ledger, out_dir=out_dir,
            ))
    except Refused as exc:
        envelope["status"] = "REFUSED"
        envelope["refusal"] = str(exc)
        report_path = Path(args.report).resolve() if args.report else \
            RUNTIME_ROOT / "runtime/reports" / f"{args.episode}_paid_authorization_refusal.json"
        dump_json(report_path, envelope)
        print(json.dumps({"status": "REFUSED", "refusal": str(exc),
                          "report": str(report_path)}, ensure_ascii=False, indent=2))
        return 5

    refused = [
        row for row in envelope["results"]
        if row["guard_gate_status"] != "PASS"
        or row["self_verification"]["status"] not in {"PASS", "NOT_APPLICABLE_AUTHORITY_LIVES_IN_BACKLOTOS_GATE"}
    ]
    envelope["status"] = "PASS" if not refused else "MATERIALISED_BUT_VALIDATOR_REFUSES"
    report_path = Path(args.report).resolve() if args.report else \
        RUNTIME_ROOT / "runtime/reports" / f"{args.episode}_paid_authorization.json"
    dump_json(report_path, envelope)
    print(json.dumps({
        "status": envelope["status"],
        "order": {"seq": order["seq"], "id": order["id"],
                  "latest_order_seq": order["latest_order_seq"],
                  "issued_by": order["issued_by"],
                  "authorized_stage": order["authorized_stage"],
                  "episode_scope": order["episode_scope"], "cap_credits": order["cap_credits"]},
        "results": [
            {
                "kind": row["kind"], "materialised": row["materialised"],
                "materialised_sha256": row["materialised_sha256"],
                "planned_credits": row["cost_envelope"]["planned_credits"],
                "guard_gate_status": row["guard_gate_status"],
                "guard_raw_status": row["guard_raw_status"],
                "guard_gate_report": row["guard_gate_report"],
                "self_verification": row["self_verification"],
            }
            for row in envelope["results"]
        ],
        "report": str(report_path),
    }, ensure_ascii=False, indent=2))
    return 0 if envelope["status"] == "PASS" else 6


if __name__ == "__main__":
    sys.exit(main())
