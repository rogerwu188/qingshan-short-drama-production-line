#!/usr/bin/env python3
"""Read-only per-episode credit budget guard for the nalu line.

The deployment passes a per-episode cap on every check. Severity is HARD_STOP:
image + video + audio for one episode must stay within that cap, and the
orchestrator must estimate against the ledger BEFORE submitting, stopping and
escalating instead of silently degrading quality or skipping a gate. The cap
does not itself authorize paid work; the source-receipted line-owner order is
validated separately by ``materialize_paid_authorization.py``.

Built on the engine, not duplicating it
---------------------------------------
* Video spend and the video-only ceiling come from the engine's own
  `tools/episode_video_generation_guard.evaluate_episode_credit_gate`, which
  already scans `workflow/tasks/**` for `credit_attempts[].actual_charged_credits`
  and already fails closed on unknown cost
  (`SUCCESSFUL_VIDEO_CREDIT_FIELDS_MISSING`).  This tool adds the image and
  audio legs it does not cover and applies the all-media 8000 cap on top.
* The one network call reuses `tools/giggle_credit_statements.STATEMENT_PATH`
  and `tools/giggle_api_client._get` — a plain authenticated GET that is not
  subject to (and cannot reach) the paid-generation fuses in `_request`.
* Release-time closure stays with `tools/giggle_credit_closure_gate.py`
  (`qingshan.giggle_credit_ledger.v1`, gate id GIGGLE-CREDIT-LEDGER-CLOSURE);
  this tool records the balance snapshots that gate needs rather than
  reimplementing its arithmetic.

Money safety
------------
The ONLY endpoint this tool can reach is GET /api/v1/payment/credit-statements,
and only when `--refresh-balance` is passed — at most once per invocation.
`--check` is fully offline by default, because a pre-submit budget gate must
not depend on the network.  `giggle_api_client._request` (the POST path) is
never imported.  The API key is read into the process from the env or from a
`.env` file and is never printed, logged or written to any artifact.
"""

from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import argparse
import json
import os
import re
import uuid
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(os.environ.get("QINGSHAN_ENGINE_ROOT", f"{_np.ENGINE_ROOT}"))
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))
from tools.image_model_policy import ACTIVE_IMAGE_MODEL, image_hard_upper_credits  # noqa: E402  (Roger 2026-10-30 seq=54)

SCHEMA = "nalu.episode_credit_budget_ledger.v1"
DEFAULT_CAP = 8000


def configured_cap() -> int:
    """The per-episode cap in force right now: the live ``qingshan.json`` (written when the paid order is
    recorded) wins over $NALU_EPISODE_CREDIT_CAP, which a long-running session may have inherited from
    before the order existed; a bare --check must not rewrite the ledger's cap back to that stale value."""
    try:
        gen = (json.loads((Path(f"{_np.RUNTIME_ROOT}") / "qingshan.json").read_text(encoding="utf-8"))
               .get("generation") or {})
        cap = gen.get("budget_cap_credits_per_episode") or gen.get("budget_credits_per_episode_cap")
        if isinstance(cap, int) and not isinstance(cap, bool) and cap > 0:
            return cap
    except (OSError, ValueError, AttributeError):
        pass
    return int(os.environ.get("NALU_EPISODE_CREDIT_CAP", DEFAULT_CAP))
DEFAULT_LEDGER = Path(f"{_np.RUNTIME_ROOT}/runtime/budget/ledger.json")
DEFAULT_ENV_FILE = ENGINE_ROOT / ".env"

STATEMENT_PATH = "/api/v1/payment/credit-statements"

# Observed authoritative unit prices, each with its in-repo evidence. Used for
# planning only; the actual charge always comes from the statement ledger.
UNIT_PRICES = {
    "video_minimax_h3_768p_hopsapi": {
        "credits_per_second": 1.56,
        "credits_per_task": 0,
        "evidence": "HopsAPI probe 2026-10-29 (E07-VU-005, 4 s, cost 6.23 = list 8.9/s x 0.175); planning "
                    "rate configurable via HOPSAPI_H3_CREDITS_PER_SECOND / generation.hopsapi_h3_credits_per_second "
                    "(tools/hopsapi_video_client.py); actual charge = per-task cost on the settled query",
    },
    "video_minimax_h3_768p": {
        "credits_per_second": 14,
        "credits_per_task": 6,
        "evidence": "tools/authorize_e48_v5_h3_a4_remaining4.py (E48 observed 14 x seconds + 6 per task); "
                    "lines/nalu/runtime/tools/materialize_paid_authorization.py H3_CREDITS_*",
    },
    "image_gpt_image_2_hopsapi": {
        "credits": 1.2,
        "evidence": "HopsAPI probe 2026-10-30 (E09-S02-04 keyframe, high, 6 refs: cost 0.97; Txt2Img low 0.13); "
                    "planning rate configurable via HOPSAPI_IMAGE_CREDITS_PER_IMAGE / "
                    "generation.hopsapi_image_credits_per_image (tools/hopsapi_image_client.py), batch rounded up; "
                    "actual charge = per-task cost on the settled query",
    },
    "image_gpt_image_2_pro": {
        "credits": 5,
        "hard_upper": 11,
        "evidence": "tools/e40_u12_v3_image_paid_preflight.py:35-36 EXPECTED_IMAGE_PRICE=5 / EXPECTED_UPPER=11; "
                    "retired for new paid submits 2026-10-30 (seq=54)",
    },
    # The active image SKU and its reserve price come from configs/IMAGE_MODEL_CAPABILITY_REGISTRY_v1.json
    # via tools/image_model_policy.image_hard_upper_credits(); bound image tasks are reserved at that figure.
    "image_active": {
        "model": ACTIVE_IMAGE_MODEL,
        "hard_upper": image_hard_upper_credits(),
        "evidence": "registry profile pricing.hard_upper (Roger 2026-10-30 seq=54: 所有图片生成都改为 gptimage2 便宜档)",
    },
    "audio_minmax_speech_2_8_hd": {
        "credits": 2,
        "hard_upper": 2,
        "evidence": "tools/preflight_e40_u12_dia010_exactly_one_tts.py:112-114 refuses a live price above 2",
    },
    "video_seedance_2_0_pro_per_second": {
        "credits": 48,
        "hard_upper": 48,
        "evidence": "tools/build_e39_independent_r3_silent_visual_manifests.py:143-147 credits_per_second=48",
    },
}

# Transaction states that mean "we do not know what this cost". Any of these
# makes headroom uncertifiable, so the check fails closed rather than assuming 0.
UNRESOLVED_TRANSACTION_STATES = {
    "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
    "CHARGE_STATE_UNRESOLVED_BATCH",
    "CHARGED_TASK_ID_MISSING",
    # tools/hopsapi_usage.py: a lost HopsAPI create whose window holds billed tasks no transaction
    # owns; one of them may be ours, so the spend stays unknowable until an operator attributes it
    "NEEDS_MANUAL_ATTRIBUTION",
}
# States that are settled: either bound to a task whose charge is recorded
# elsewhere, or verified as never charged.  CHARGED_WRITTEN_OFF_BY_ORDER is a
# CHARGED_TASK_ID_MISSING row the line owner wrote off (order seq=21, Roger
# 2026-10-01): the charge itself stays counted through the archived
# *_credit_statement.json that proved it, so settling the row never hides spend.
# VERIFIED_ZERO_NO_REMOTE_TASK: a lost HopsAPI create the billing usage API proved created no billed
# task (tools/hopsapi_usage.py reconcile) -- 0 credits.  An ADOPTED one is SUBMITTED_TASK_ID_BOUND.
SETTLED_TRANSACTION_STATES = {"SUBMITTED_TASK_ID_BOUND", "VERIFIED_ZERO_RETRYABLE", "NOT_CHARGED_RETRYABLE",
                              "CHARGED_WRITTEN_OFF_BY_ORDER", "VERIFIED_ZERO_NO_REMOTE_TASK",
                              # tools/hopsapi_usage.py: an unattributable lost POST on the shared fleet key, counted
                              # at its written_off_credits by scan_hopsapi_spend (line owner 2026-11-11)
                              "WRITTEN_OFF_UNATTRIBUTABLE_RETRYABLE"}

VIDEO_TRANSACTION_DIRNAME = "giggle_video_submit_transactions"
IMAGE_TRANSACTION_DIRNAME = "giggle_submit_transactions"
BGM_PROVISIONAL_CREDITS_PER_TASK = Decimal("8")
BGM_PROVISIONAL_STATES = {
    "SUBMITTED_TASK_ID_BOUND",  # legacy provider
    "TASK_ID_BOUND_QUERY_PENDING",
    "TASK_ID_BOUND_COMPLETED_DOWNLOAD_PENDING",
}
BGM_UNRESOLVED_STATES = {
    "INTENT_RECORDED",
    "RESPONSE_LOST",
    "TERMINAL_FAILED",
    "PROVIDER_FAILED",
}
#: S4 voice / voice-over TTS (Giggle text-to-audio) durable store:
#: ``<tasks>/giggle_audio_transactions/<scope>/<EP>/{speech,voice_over}/**.json`` (legacy:
#: ``<tasks>/giggle_audio_transactions/<EP>/``).  Lab E09 2026-10-30: 13 completed S4 speech tasks
#: were invisible to the ledger, so the cap check reported 881.47 / 900 with accounting_complete=true.
AUDIO_TRANSACTION_DIRNAME = "giggle_audio_transactions"
BGM_TRANSACTION_DIRNAME = "giggle_bgm_transactions"
AUDIO_STATEMENT_EVENT = "SingleGenerateAudio"
AUDIO_CHARGED_STATES = {"TERMINAL_COMPLETED", "COMPLETED", "TASK_ID_BOUND_QUERY_PENDING",
                        "TASK_ID_BOUND_COMPLETED_DOWNLOAD_PENDING", "SUBMITTED_TASK_ID_BOUND"}
#: a POST may have happened with no task id bound: spend unknowable, the check fails closed
AUDIO_UNRESOLVED_STATES = {"INTENT_RECORDED", "RESPONSE_LOST", "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION"}
AUDIO_TERMINAL_FAILED_STATES = {"TERMINAL_FAILED", "PROVIDER_FAILED"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def episode_key(value: str) -> str:
    match = re.fullmatch(r"(?:EP|E)?0*([1-9][0-9]*)", value.strip(), re.I)
    if not match:
        raise SystemExit(f"unrecognised episode key: {value}")
    return f"E{int(match.group(1)):02d}"


def number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral() else float(value)


# --------------------------------------------------------------------------- #
# Credentials — loaded into this process only, never echoed
# --------------------------------------------------------------------------- #

def load_api_key(env_file: Path) -> str:
    """Populate GIGGLE_API_KEY in-process. The value is never returned upward."""
    if os.environ.get("GIGGLE_API_KEY", "").strip():
        return "INHERITED_ENV"
    if not env_file.is_file():
        raise SystemExit(f"GIGGLE_API_KEY is not set and {env_file} does not exist")
    mode = env_file.stat().st_mode
    loaded: list[str] = []
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Only the credentials this tool needs; nothing else is imported into
        # the environment, and nothing is exported to any child process.
        if key in {"GIGGLE_API_KEY", "GIGGLE_API_BASE"} and value:
            os.environ.setdefault(key, value)
            loaded.append(key)
    if not os.environ.get("GIGGLE_API_KEY", "").strip():
        raise SystemExit(f"{env_file} contains no GIGGLE_API_KEY")
    return "DOTENV_FILE" + ("_GROUP_OR_WORLD_READABLE" if mode & 0o077 else "")


# --------------------------------------------------------------------------- #
# The single read-only GET
# --------------------------------------------------------------------------- #

BALANCE_KEY_CANDIDATES = (
    "balance", "credit_balance", "credits", "remaining", "remaining_credits",
    "credit_remaining", "available", "available_credits", "total_credit",
    "current_credit", "credit", "quota", "remain",
)


def fetch_balance_snapshot(page_size: int) -> dict[str, Any]:
    """ONE authenticated GET of the credit statement ledger.

    The provider exposes no dedicated balance endpoint anywhere in this engine
    (41 call sites, all of them this one path), so the snapshot records:
      * any balance-shaped scalar the response happens to carry, discovered
        rather than assumed, and
      * the most recent statement rows, which are the authoritative per-task
        charge evidence every reconciler in the repo uses.
    """
    from tools.giggle_api_client import BASE_URL, _get  # noqa: PLC0415

    response = _get(
        STATEMENT_PATH,
        {"credit_type": "", "page": 1, "page_size": page_size, "project_id": ""},
    )
    code = response.get("code")
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    rows = data.get("list") if isinstance(data.get("list"), list) else []
    # Discovered, not assumed: walk the whole envelope except the row list and
    # record every balance-shaped scalar with its full dotted path. The live
    # response carries data.consumption_summary and data.pagination, so a flat
    # top-level-only scan would miss a balance nested inside them.
    discovered: dict[str, Any] = {}

    def walk(node: Any, path: str, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "list":
                    continue
                child = f"{path}.{key}" if path else key
                if isinstance(value, (dict, list)):
                    walk(value, child, depth + 1)
                elif isinstance(value, (int, float, str)) and not isinstance(value, bool):
                    if key.lower() in BALANCE_KEY_CANDIDATES:
                        discovered[child] = value
        elif isinstance(node, list):
            for index, value in enumerate(node[:5]):
                walk(value, f"{path}[{index}]", depth + 1)

    walk(response, "response")
    paid = Decimal("0")
    refunded = Decimal("0")
    malformed = 0
    by_event: dict[str, int] = {}
    for row in rows:
        event = str(row.get("event_type") or "UNKNOWN")
        by_event[event] = by_event.get(event, 0) + 1
        try:
            amount = abs(Decimal(str(row["credit"])))
        except (KeyError, InvalidOperation, TypeError):
            malformed += 1
            continue
        if event == "Pay":
            paid += amount
        elif event == "Refund":
            refunded += amount
    return {
        "recorded_at_utc": utc_now(),
        "endpoint": STATEMENT_PATH,
        "method": "GET",
        "base_url": BASE_URL,
        "request_params": {"credit_type": "", "page": 1, "page_size": page_size, "project_id": ""},
        "response_code": code,
        "ok": code == 200,
        "response_top_level_keys": sorted(response.keys()),
        "data_keys": sorted(data.keys()),
        "statement_row_count": len(rows),
        "rows_by_event_type": dict(sorted(by_event.items())),
        "malformed_credit_rows": malformed,
        "window_paid_credits": number(paid),
        "window_refunded_credits": number(refunded),
        "window_net_credits": number(paid - refunded),
        "provider_balance_fields_discovered": discovered or None,
        # Captured verbatim because they are the only other aggregate the
        # endpoint returns and they are small and non-secret. A balance-like
        # total, if the provider ever exposes one, lives here.
        "consumption_summary": data.get("consumption_summary"),
        "pagination": data.get("pagination"),
        "daily_consumption_row_count": (
            len(data["daily_consumption"]) if isinstance(data.get("daily_consumption"), list) else None
        ),
        "balance_availability": (
            "PROVIDER_BALANCE_FIELD_PRESENT" if discovered
            else "PROVIDER_EXPOSES_NO_BALANCE_FIELD_ON_THIS_ENDPOINT"
        ),
        "newest_rows": [
            {
                key: row.get(key)
                for key in ("created_at", "event_type", "event_description", "model", "model_name", "credit", "project_id")
                if key in row
            }
            for row in rows[:10]
        ],
        "limitation": (
            "Giggle exposes no balance endpoint in this engine; every one of the 41 payment call "
            "sites reads /api/v1/payment/credit-statements. Absolute account balance must come from "
            "the Giggle bill or an operator-entered before/after pair (see "
            "tools/build_giggle_credit_ledger.py:133 and giggle_credit_closure_gate balance_before/after)."
        ),
    }


# --------------------------------------------------------------------------- #
# Durable spend scan (offline)
# --------------------------------------------------------------------------- #

#: Directories the production contract parks superseded/rejected material in (old images, `_raw`, their
#: receipts).  A parked copy is evidence, not a second charge: E02 (2026-10-14) double-counted a credit
#: statement copied into workflow/nalu/E02/_superseded_*_controlled_repair1/ by a controlled repair.
PARKED_DIR_PREFIXES = ("_superseded", "_rejected", "_parked", "_archive")


def _statement_row_key(row: Any) -> tuple[str, ...] | None:
    """Identity of one provider Pay row across archived statements (None: not identifiable)."""
    if not isinstance(row, dict):
        return None
    project_id = str(row.get("project_id") or "")
    try:
        credit = str(abs(Decimal(str(row["credit"]))))
    except (KeyError, InvalidOperation):
        return None
    if not project_id:
        # no provider id: only an exact duplicate of every field is the same row
        return ("", json.dumps(row, sort_keys=True, ensure_ascii=False))
    return (project_id, str(row.get("event_type") or ""), str(row.get("event_description") or ""),
            str(row.get("created_at") or ""), credit)


def _statement_credits(value: Any) -> int | float | None:
    """``charged_credits`` of a batch credit statement as a number.

    The Giggle video submitter persists Decimal amounts as strings ("13.6"); those statements were
    silently skipped, so the budget check under-counted real spend (field E09 2026-11-12: 66.30 cr
    missing while ``accounting_complete=true``).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            amount = Decimal(value.strip())
        except (ArithmeticError, ValueError):
            return None
        return number(amount) if amount.is_finite() else None
    return None


def _is_parked(path: Path) -> bool:
    return any(part.startswith(PARKED_DIR_PREFIXES) for part in path.parts)


def _iter_task_json(root: Path):
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.json")):
        if _is_parked(path.relative_to(root)):
            continue
        try:
            yield path, load_json(path)
        except (OSError, json.JSONDecodeError):
            continue


def _series_scope_id(episode: str, bgm_transactions_dir: Path | None) -> str | None:
    """The series scope whose per-scope stores belong to this episode (None: unknown).

    The pipeline passes ``<giggle_bgm_transactions>/<scope>/<EP>``; a bare ``--check`` (paid_stage.sh)
    passes nothing, so the scope comes from ``runtime/series_scopes.json`` like the pipeline's own."""
    if bgm_transactions_dir is not None:
        directory = Path(bgm_transactions_dir)
        if directory.name == episode and directory.parent.parent.name == BGM_TRANSACTION_DIRNAME:
            return directory.parent.name
    try:
        import nalu_series_scope  # noqa: PLC0415
        return str(nalu_series_scope.scope_id_for(episode))
    except (SystemExit, Exception):  # noqa: BLE001 -- unknown scope: legacy layout only
        return None


def _store_dirs(dirname: str, episode: str, scope_id: str | None) -> list[Path]:
    """Existing scoped (``<store>/<scope>/<EP>``) and legacy (``<store>/<EP>``) store directories."""
    base = ENGINE_ROOT / "workflow" / "tasks" / dirname
    candidates = []
    if scope_id and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", scope_id) and scope_id != episode:
        candidates.append(base / scope_id / episode)
    candidates.append(base / episode)
    return [path for path in candidates if path.is_dir()]


def audio_transaction_dirs(episode: str, *, audio_transactions_dir: Path | None = None,
                           bgm_transactions_dir: Path | None = None) -> list[Path]:
    if audio_transactions_dir is not None:
        return [Path(audio_transactions_dir)]
    return _store_dirs(AUDIO_TRANSACTION_DIRNAME, episode, _series_scope_id(episode, bgm_transactions_dir))


def bgm_transaction_dirs(episode: str, bgm_transactions_dir: Path | None = None) -> list[Path]:
    if bgm_transactions_dir is not None:
        return [Path(bgm_transactions_dir)]
    return _store_dirs(BGM_TRANSACTION_DIRNAME, episode, _series_scope_id(episode, None))


def _iter_store_transactions(directories: list[Path]):
    """Every transaction file under the store directories, parked attempts included.

    A ``_superseded_*`` transaction is a real, separate paid task (a recast reference, a redo), not
    a copy of a live one: the money was spent.  Copies are folded by task id by the callers."""
    for directory in directories:
        for path in sorted(directory.rglob("*.json")) if directory.is_dir() else []:
            try:
                payload = load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                yield path, payload


def _transaction_charge(payload: dict[str, Any]) -> Decimal | None:
    """The actual charge a reconciler wrote onto the transaction itself, if any."""
    credit = payload.get("credit") if isinstance(payload.get("credit"), dict) else {}
    for value in (credit.get("net_charged_credits"), payload.get("actual_charged_credits"),
                  payload.get("provider_cost_credits")):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return Decimal(str(value))
    return None


def audio_task_ids(directories: list[Path]) -> set[str]:
    return {str(payload["task_id"]).strip() for _, payload in _iter_store_transactions(directories)
            if str(payload.get("task_id") or "").strip()}


AUDIO_RECEIPT_NAME = re.compile(r"CREDIT|LEDGER", re.I)


def scan_audio_receipts(episode: str, task_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Per-task exact credit receipts already written for TTS tasks (match by task id).

    S4 reconcilers write ``{task_id, ledger|credit: {net_charged_credits, status}}`` (e.g.
    ``runtime/reports/E01_S4_EXACT_TASK_CREDITS.json``, method EXACT_PROJECT_ID_PAY_MINUS_REFUND).
    Only ``*CREDIT*`` / ``*LEDGER*`` json files of this episode are read; first receipt per task wins."""
    found: dict[str, dict[str, Any]] = {}
    if not task_ids:
        return found
    roots = [ENGINE_ROOT / "workflow" / "nalu" / episode, Path(f"{_np.RUNTIME_ROOT}") / "runtime" / "reports"]
    paths: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.json")):
            if not AUDIO_RECEIPT_NAME.search(path.name):
                continue
            if root.name == "reports" and episode not in path.name:
                continue
            paths.append(path)

    def walk(node: Any, source: Path, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, source, depth + 1)
            return
        if not isinstance(node, dict):
            return
        task_id = str(node.get("task_id") or "").strip()
        if task_id in task_ids and task_id not in found:
            for holder in (node, node.get("ledger"), node.get("credit")):
                if not isinstance(holder, dict):
                    continue
                net = holder.get("net_charged_credits")
                status = str(holder.get("status") or holder.get("statement_status") or "")
                if (isinstance(net, (int, float)) and not isinstance(net, bool)
                        and (not status or status.startswith("PASS"))):
                    found[task_id] = {"credits": Decimal(str(net)), "source": str(source), "status": status}
                    break
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value, source, depth + 1)

    for path in paths:
        try:
            walk(load_json(path), path)
        except (OSError, json.JSONDecodeError):
            continue
    return found


def scan_audio_spend(directories: list[Path], *, statement_net: dict[str, Decimal],
                     attempt_credits: dict[str, Decimal],
                     receipts: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """S4 TTS leg (Giggle text-to-audio), one row per provider task id.

    Charge evidence, best first: the transaction's own reconciled credit; an exact per-task credit
    receipt (``scan_audio_receipts``); the archived Giggle
    statement rows matched by task id (Pay - Refund, ``SingleGenerateAudio``); a ``credit_attempts``
    row carrying the task id; else the observed per-task price, flagged ``ESTIMATED_UNIT_PRICE``
    (spend is counted, but accounting is not complete until a statement replaces the estimate).
    Statement rows / attempts matched here are excluded from the image layers, never counted twice."""
    unit = Decimal(str(UNIT_PRICES["audio_minmax_speech_2_8_hd"]["hard_upper"]))
    exact = Decimal("0")
    estimated = Decimal("0")
    rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path, payload in _iter_store_transactions(directories):
        state = str(payload.get("state") or "UNKNOWN")
        task_id = str(payload.get("task_id") or "").strip()
        if task_id and task_id in seen:
            continue
        if not task_id:
            if state in AUDIO_UNRESOLVED_STATES or state not in AUDIO_TERMINAL_FAILED_STATES:
                unresolved.append({"source": str(path), "state": state, "task_id": None})
            continue
        seen.add(task_id)
        charge = _transaction_charge(payload)
        method = "TRANSACTION_RECONCILED_CREDIT"
        if charge is None and task_id in (receipts or {}):
            charge, method = receipts[task_id]["credits"], "EXACT_TASK_CREDIT_RECEIPT"
        if charge is None and task_id in statement_net:
            charge, method = statement_net[task_id], "GIGGLE_STATEMENT_TASK_ID_MATCH"
        if charge is None and task_id in attempt_credits:
            charge, method = attempt_credits[task_id], "CREDIT_ATTEMPT_TASK_ID_MATCH"
        if charge is None and state in AUDIO_UNRESOLVED_STATES:
            unresolved.append({"source": str(path), "state": state, "task_id": task_id})
            continue
        if charge is None:
            # completed / bound / provider-failed without a statement yet: a failed task is normally
            # refunded, but until a statement shows the refund the per-task price stays reserved.
            charge, method = unit, "ESTIMATED_UNIT_PRICE"
            estimated += charge
        else:
            exact += charge
        rows.append({"source": str(path), "task_id": task_id, "state": state,
                     "capability": payload.get("capability"), "credits": number(charge), "method": method})
    return {
        "transaction_dirs": [str(d) for d in directories],
        "task_count": len(rows),
        "charged_credits": number(exact),
        "estimated_credits": number(estimated),
        "estimated_task_count": sum(1 for row in rows if row["method"] == "ESTIMATED_UNIT_PRICE"),
        "estimate_unit_price_credits": number(unit),
        "rows": rows,
        "unresolved_transactions": unresolved,
    }


def scan_non_video_spend(
    episode: str, *, bgm_transactions_dir: Path | None = None,
    audio_transactions_dir: Path | None = None,
) -> dict[str, Any]:
    """Image and audio spend from the durable transaction / receipt stores.

    Three independent evidence layers, deliberately reported separately because
    Giggle omits the task id from image statement rows, so image evidence is
    batch-level while audio and video evidence is per task id.
    """
    tasks_root = ENGINE_ROOT / "workflow" / "tasks"
    per_task = Decimal("0")
    per_task_rows: list[dict[str, Any]] = []
    unknown_success = 0
    batch_total = Decimal("0")
    batch_rows: list[dict[str, Any]] = []
    bound_image_task_ids: set[str] = set()
    bound_image_rows: list[dict[str, Any]] = []
    # Audio (TTS) task ids: their statement rows / credit attempts belong to the audio leg only.
    audio_dirs = audio_transaction_dirs(episode, audio_transactions_dir=audio_transactions_dir,
                                        bgm_transactions_dir=bgm_transactions_dir)
    audio_ids = audio_task_ids(audio_dirs)
    audio_statement_net: dict[str, Decimal] = {}
    audio_attempt_credits: dict[str, Decimal] = {}

    for path, payload in _iter_task_json(tasks_root):
        if not isinstance(payload, dict):
            continue
        payload_episode = str(payload.get("episode") or "").upper()
        # Layer 1: credit_attempts on non-video task rows.
        for task in payload.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            if str(task.get("tool_type") or "") == "video_generation":
                continue  # owned by episode_video_generation_guard
            task_episode = str(task.get("episode") or payload_episode or "").upper()
            if task_episode and task_episode != episode:
                continue
            for attempt in task.get("credit_attempts") or []:
                if not isinstance(attempt, dict):
                    continue
                credits = attempt.get("actual_charged_credits")
                attempt_task = str(attempt.get("task_id") or "").strip()
                if attempt_task and attempt_task in audio_ids:
                    if isinstance(credits, (int, float)):
                        audio_attempt_credits.setdefault(attempt_task, Decimal(str(credits)))
                    continue  # counted once, by scan_audio_spend
                if isinstance(credits, (int, float)):
                    per_task += Decimal(str(credits))
                    per_task_rows.append({
                        "source": str(path),
                        "task_key": task.get("task_key") or task.get("character_id"),
                        "tool_type": task.get("tool_type"),
                        "task_id": attempt.get("task_id"),
                        "credits": credits,
                        "charge_status": attempt.get("charge_status"),
                    })
                elif attempt.get("success") is True:
                    unknown_success += 1

    # The image submitter's durable idempotency store predates credit_attempts
    # and therefore has many successful task bindings with no per-task cost
    # field.  Ignoring those files undercounts later reroll batches whenever
    # their reconciliation receipt lives in a dedicated runtime outside the
    # engine clone.  For the budget cap, count each unique accepted image task
    # at the observed hard upper price.  This is deliberately conservative and
    # is not presented as release-time exact provider accounting.
    image_tx_dir = tasks_root / IMAGE_TRANSACTION_DIRNAME / episode
    for path in sorted(image_tx_dir.glob("*.json")) if image_tx_dir.is_dir() else []:
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("state") != "SUBMITTED_TASK_ID_BOUND":
            continue
        if is_hopsapi_transaction(payload):
            continue  # HopsAPI image (owner 2026-10-30): per-task cost, counted by scan_hopsapi_spend
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id or task_id in bound_image_task_ids:
            continue
        bound_image_task_ids.add(task_id)
        bound_image_rows.append({
            "source": str(path),
            "task_key": payload.get("task_key"),
            "task_id": task_id,
            "state": payload.get("state"),
        })

    # Layer 2: batch reconciliation statements written next to submit reports.
    seen_statement_rows: set[tuple[str, ...]] = set()
    duplicate_statement_rows: list[dict[str, Any]] = []
    for path in sorted(ENGINE_ROOT.rglob("*_credit_statement.json")):
        if _is_parked(path.relative_to(ENGINE_ROOT)):
            continue
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if episode not in str(path) and str(payload.get("episode") or "").upper() != episode:
            continue
        credits = _statement_credits(payload.get("charged_credits"))
        # One provider Pay row is one charge, however many batch windows matched it.  Overlapping
        # windows of adjacent waves both archived the same row (lab E05 2026-10-26: 1eb26c4b's 48 cr
        # in wave 28's AND wave 29's statement, ledger 1382 vs 1334 provider truth).  Statements are
        # never rewritten: a row already counted from an earlier statement is just not added again.
        rows = payload.get("statement_rows")
        if isinstance(credits, (int, float)) and isinstance(rows, list) and rows:
            keys = [_statement_row_key(row) for row in rows]
            if all(key is not None for key in keys):
                fresh = [(key, row) for key, row in zip(keys, rows) if key not in seen_statement_rows]
                seen_statement_rows.update(key for key, _ in fresh)
                # A Pay/Refund row for a TTS task id is audio evidence, not image spend.
                audio_fresh = [row for _, row in fresh if str(row.get("project_id") or "") in audio_ids]
                for row in audio_fresh:
                    amount = abs(Decimal(str(row["credit"])))
                    signed = -amount if str(row.get("event_type") or "") == "Refund" else amount
                    pid = str(row["project_id"])
                    audio_statement_net[pid] = audio_statement_net.get(pid, Decimal("0")) + signed
                fresh = [(key, row) for key, row in fresh if str(row.get("project_id") or "") not in audio_ids]
                counted = sum((abs(Decimal(str(row["credit"]))) for _, row in fresh), Decimal("0"))
                duplicate_rows = len(rows) - len(fresh)
                if duplicate_rows:
                    duplicate_statement_rows.append({"source": str(path), "duplicate_rows": duplicate_rows,
                                                     "statement_credits": credits, "counted_credits": number(counted)})
                credits = number(counted)
        if isinstance(credits, (int, float)):
            batch_total += Decimal(str(credits))
            batch_rows.append({
                "source": str(path),
                "status": payload.get("status"),
                "event_description": payload.get("event_description"),
                "model": payload.get("model"),
                "matched_count": payload.get("matched_count"),
                "credits": credits,
            })

    # Layer 3: selective BGM (nalu_selective_bgm.py): its own durable store, one file per music task,
    # `credit.net_charged_credits` written by `reconcile` (exact per-task or submit-window isolated; the
    # label is carried so the leg is never mistaken for the exact method).  Separate store → additive.
    bgm_total = Decimal("0")
    bgm_rows: list[dict[str, Any]] = []
    bgm_provisional_total = Decimal("0")
    bgm_provisional_rows: list[dict[str, Any]] = []
    bgm_unresolved_rows: list[dict[str, Any]] = []
    bgm_dir = bgm_transactions_dir or (tasks_root / BGM_TRANSACTION_DIRNAME / episode)
    # A bare --check (no explicit dir) also finds the current per-scope store, not only the legacy one.
    bgm_dirs = bgm_transaction_dirs(episode, bgm_transactions_dir)
    bgm_seen: set[str] = set()
    for path, payload in _iter_store_transactions(bgm_dirs):
        bgm_task = str(payload.get("task_id") or "").strip()
        if bgm_task:
            if bgm_task in bgm_seen:
                continue  # a parked copy of a task already counted
            bgm_seen.add(bgm_task)
        state = str(payload.get("state") or "UNKNOWN")
        if state in BGM_PROVISIONAL_STATES:
            bgm_provisional_total += BGM_PROVISIONAL_CREDITS_PER_TASK
            bgm_provisional_rows.append({
                "source": str(path), "task_id": payload.get("task_id"),
                "state": state, "reserved_credits": number(BGM_PROVISIONAL_CREDITS_PER_TASK),
                "status": "PROVISIONAL_TASK_BOUND_AWAITING_S7_RECONCILIATION",
            })
            continue
        if state in BGM_UNRESOLVED_STATES:
            bgm_unresolved_rows.append({"source": str(path), "task_id": payload.get("task_id"),
                                        "state": state})
            continue
        if state not in {"COMPLETED", "TERMINAL_COMPLETED"}:
            bgm_unresolved_rows.append({"source": str(path), "task_id": payload.get("task_id"),
                                        "state": state})
            continue
        credits = (payload.get("credit") or {}).get("net_charged_credits")
        if isinstance(credits, (int, float)):
            bgm_total += Decimal(str(credits))
            bgm_rows.append({"source": str(path), "task_id": payload.get("task_id"), "credits": credits,
                             "statement_status": (payload.get("credit") or {}).get("statement_status"),
                             "isolation": (payload.get("credit") or {}).get("isolation")})
        else:
            # S6 has completed this paid task but S7 has not fetched its
            # statement yet.  Reserve the observed per-task price so a later
            # paid check cannot undercount it; S7 replaces this reservation
            # with the exact/window-isolated credit evidence.
            bgm_provisional_total += BGM_PROVISIONAL_CREDITS_PER_TASK
            bgm_provisional_rows.append({
                "source": str(path), "task_id": payload.get("task_id"),
                "state": state, "reserved_credits": number(BGM_PROVISIONAL_CREDITS_PER_TASK),
                "status": "PROVISIONAL_COMPLETED_AWAITING_S7_RECONCILIATION",
            })

    audio = scan_audio_spend(audio_dirs, statement_net=audio_statement_net,
                             attempt_credits=audio_attempt_credits,
                             receipts=scan_audio_receipts(episode, audio_ids))
    audio_total = Decimal(str(audio["charged_credits"])) + Decimal(str(audio["estimated_credits"]))

    bound_image_upper = Decimal(len(bound_image_task_ids)) * Decimal(str(
        image_hard_upper_credits()
    ))
    return {
        "per_task_credits": number(per_task),
        "per_task_rows": per_task_rows,
        "successful_attempts_with_unknown_cost": unknown_success,
        "batch_reconciled_credits": number(batch_total),
        "batch_rows": batch_rows,
        "batch_duplicate_statement_rows": duplicate_statement_rows,
        "bound_image_transaction_count": len(bound_image_task_ids),
        "bound_image_transaction_upper_credits": number(bound_image_upper),
        "bound_image_transaction_rows": bound_image_rows,
        "bgm_credits": number(bgm_total),
        "bgm_rows": bgm_rows,
        "bgm_provisional_credits": number(bgm_provisional_total),
        "bgm_provisional_rows": bgm_provisional_rows,
        "bgm_unresolved_transactions": bgm_unresolved_rows,
        "bgm_transactions_dir": str(bgm_dir),
        "bgm_transactions_dirs": [str(d) for d in bgm_dirs],
        "audio": audio,
        "audio_credits": number(audio_total),
        "double_count_policy": (
            "per_task, batch-reconciliation, and accepted image-transaction layers are reported "
            "separately and the largest is used as the non-video subtotal. The transaction layer "
            "uses the observed image hard upper, so it cannot undercount receipts stored outside "
            "the engine clone; summing the layers would double count. The BGM and audio (TTS) "
            "legs are separate stores keyed by provider task id and are additive; statement rows and "
            "credit attempts carrying a TTS task id are moved out of the image layers into the audio leg."
        ),
        "subtotal_credits": number(max(per_task, batch_total, bound_image_upper) + bgm_total
                                   + bgm_provisional_total + audio_total),
    }


HOPSAPI_PROVIDER = "hopsapi"
HOPSAPI_TERMINAL_FAILED = {"failed", "cancelled"}


def is_hopsapi_transaction(payload: dict[str, Any]) -> bool:
    """A video transaction submitted through the HopsAPI router (owner 2026-10-29)."""
    return str(payload.get("provider") or "").lower() == HOPSAPI_PROVIDER \
        or str(payload.get("task_id") or "").startswith("tsk_")


#: fallback exposure of a bound HopsAPI task with no recorded estimate (video 8 s x 20; image 1.2 -> 2)
HOPSAPI_FALLBACK_EXPOSURE = {"video": 160, "image": 2}


def scan_hopsapi_video_spend(episode: str) -> dict[str, Any]:
    """The HopsAPI VIDEO transactions only (kept for callers that ask for that leg alone)."""
    return scan_hopsapi_spend(episode, kinds=("video",))


def scan_hopsapi_spend(episode: str, kinds: tuple[str, ...] = ("video", "image")) -> dict[str, Any]:
    """HopsAPI leg: per-task ``cost`` (credits, same unit as Giggle) from the durable stores, video
    (owner 2026-10-29) and images (gpt-image-2, owner 2026-10-30).

    HopsAPI bills each task at settlement and never appears in Giggle's credit statements, so this leg
    is additive to every Giggle layer.  A bound task with a recorded ``provider_cost_credits`` is
    settled spend; a terminal failure (status 3/4) is 0; any other bound task counts its
    ``estimated_credits`` as exposure until the poller / harvester records the settlement."""
    settled = Decimal("0")
    exposure = Decimal("0")
    by_kind = {kind: {"settled_credits": Decimal("0"), "pending_exposure_credits": Decimal("0")} for kind in kinds}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    sources: list[tuple[str, Path]] = []
    for kind in kinds:
        dirname = VIDEO_TRANSACTION_DIRNAME if kind == "video" else IMAGE_TRANSACTION_DIRNAME
        directory = ENGINE_ROOT / "workflow" / "tasks" / dirname / episode
        sources.extend((kind, path) for path in (sorted(directory.glob("*.json")) if directory.is_dir() else []))
    for kind, path in sources:
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not is_hopsapi_transaction(payload):
            continue
        if str(payload.get("state") or "") == "WRITTEN_OFF_UNATTRIBUTABLE_RETRYABLE":
            written = payload.get("written_off_credits")
            if isinstance(written, (int, float)) and not isinstance(written, bool) and written > 0:
                settled += Decimal(str(written))
                by_kind[kind]["settled_credits"] += Decimal(str(written))
                rows.append({"source": str(path), "kind": kind, "task_key": payload.get("task_key"), "task_id": None,
                             "credits": written, "status": "WRITTEN_OFF_UNATTRIBUTABLE"})
            continue
        if str(payload.get("state") or "") != "SUBMITTED_TASK_ID_BOUND" or not payload.get("task_id"):
            continue
        task_id = str(payload["task_id"])
        if task_id in seen:
            continue
        seen.add(task_id)
        cost = payload.get("provider_cost_credits")
        terminal = str(payload.get("remote_terminal_state") or payload.get("provider_remote_status") or "").lower()
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            settled += Decimal(str(cost))
            by_kind[kind]["settled_credits"] += Decimal(str(cost))
            status = "SETTLED_PROVIDER_COST"
        elif terminal in HOPSAPI_TERMINAL_FAILED:
            cost = 0
            status = "TERMINAL_NOT_CHARGED"
        else:
            estimated = payload.get("estimated_credits")
            cost = (estimated if isinstance(estimated, (int, float)) and estimated > 0
                    else HOPSAPI_FALLBACK_EXPOSURE[kind])
            exposure += Decimal(str(cost))
            by_kind[kind]["pending_exposure_credits"] += Decimal(str(cost))
            status = "BOUND_AWAITING_SETTLEMENT"
        rows.append({"source": str(path), "kind": kind, "task_key": payload.get("task_key"), "task_id": task_id,
                     "credits": cost, "status": status})
    return {"settled_credits": number(settled), "pending_exposure_credits": number(exposure),
            "unsettled_task_count": sum(1 for row in rows if row["status"] == "BOUND_AWAITING_SETTLEMENT"),
            "by_kind": {kind: {key: number(value) for key, value in totals.items()} for kind, totals in by_kind.items()},
            "rows": rows,
            "method": "HOPSAPI_PER_TASK_COST (transaction.provider_cost_credits, written by the video poller "
                      "and the image harvester)"}


def scan_transaction_states(episode: str) -> dict[str, Any]:
    tasks_root = ENGINE_ROOT / "workflow" / "tasks"
    result: dict[str, Any] = {}
    unresolved: list[dict[str, Any]] = []
    for dirname in (IMAGE_TRANSACTION_DIRNAME, VIDEO_TRANSACTION_DIRNAME):
        directory = tasks_root / dirname / episode
        states: dict[str, int] = {}
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            try:
                payload = load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            state = str(payload.get("state") or "UNKNOWN")
            states[state] = states.get(state, 0) + 1
            if state in UNRESOLVED_TRANSACTION_STATES or state not in SETTLED_TRANSACTION_STATES | {"INTENT_RECORDED"}:
                unresolved.append({
                    "transaction": str(path),
                    "task_key": payload.get("task_key"),
                    "state": state,
                })
        result[dirname] = {
            "directory": str(directory),
            "exists": directory.is_dir(),
            "transaction_count": sum(states.values()),
            "states": dict(sorted(states.items())),
        }
    result["unresolved_transactions"] = unresolved
    return result


def reservation_ledger_path(episode: str) -> Path:
    return ENGINE_ROOT / "workflow" / "nalu" / episode / "BUDGET_RESERVATION.jsonl"


RESERVATION_OWNER_ENV = "NALU_BUDGET_RESERVATION_OWNER_PID"
# Transaction states whose POST may have happened with no bound task id yet: a reservation
# whose window holds one of these is never treated as settled (the money may be in flight).
IN_FLIGHT_TRANSACTION_STATES = {"INTENT_RECORDED"} | UNRESOLVED_TRANSACTION_STATES | BGM_UNRESOLVED_STATES


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _pid_alive(pid: int) -> bool:
    if pid <= 1:
        return True  # unknown owner: assume alive (never release on a guess)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # exists but not ours (EPERM) -- alive
    return True


def _reservation_owner() -> dict[str, Any]:
    """The process a reservation belongs to: the paid step's orchestrator.

    ``nalu_pipeline.py`` exports its own pid; otherwise the parent of this CLI process
    (the caller that will submit) owns it.
    """
    raw = os.environ.get(RESERVATION_OWNER_ENV, "").strip()
    try:
        pid = int(raw) if raw else os.getppid()
    except ValueError:
        pid = os.getppid()
    import socket  # noqa: PLC0415
    return {"owner_pid": pid, "owner_host": socket.gethostname()}


def _spend_evidence(episode: str, bgm_transactions_dir: Path | None = None) -> list[dict[str, Any]]:
    """Every durable paid-transaction row of the episode with its intent time and the credits
    the recorded / pending-exposure legs already count for it (``None`` = counts nothing)."""
    tasks_root = ENGINE_ROOT / "workflow" / "tasks"
    directories: list[Path] = sorted(p for p in tasks_root.glob(f"*/{episode}")
                                     if p.is_dir() and p.parent.name != AUDIO_TRANSACTION_DIRNAME)
    if bgm_transactions_dir is not None and bgm_transactions_dir.is_dir() \
            and bgm_transactions_dir not in directories:
        directories.append(bgm_transactions_dir)
    rows: list[dict[str, Any]] = []
    for directory in directories:
        is_bgm = directory.parent.name == "giggle_bgm_transactions" or directory == bgm_transactions_dir
        for path in sorted(directory.glob("*.json")):
            try:
                payload = load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            state = str(payload.get("state") or "UNKNOWN")
            credits: Decimal | None = None
            if is_bgm:
                net = (payload.get("credit") or {}).get("net_charged_credits")
                if state in {"COMPLETED", "TERMINAL_COMPLETED"} and isinstance(net, (int, float)):
                    credits = Decimal(str(net))
                elif state in BGM_PROVISIONAL_STATES or state in {"COMPLETED", "TERMINAL_COMPLETED"}:
                    credits = BGM_PROVISIONAL_CREDITS_PER_TASK
            elif state == "SUBMITTED_TASK_ID_BOUND" and payload.get("task_id"):
                if directory.parent.name == IMAGE_TRANSACTION_DIRNAME and not is_hopsapi_transaction(payload):
                    credits = Decimal(str(image_hard_upper_credits()))
                elif is_hopsapi_transaction(payload) and isinstance(payload.get("provider_cost_credits"), (int, float)):
                    credits = Decimal(str(payload["provider_cost_credits"]))
                else:
                    estimated = payload.get("estimated_credits")
                    credits = (Decimal(str(estimated)) if isinstance(estimated, (int, float)) and estimated > 0
                               else None)
            rows.append({
                "source": str(path), "state": state, "credits": credits,
                "at": _parse_utc(payload.get("intent_recorded_at")),
                "in_flight": state in IN_FLIGHT_TRANSACTION_STATES,
            })
    # S4 TTS store (scoped layout, nested speech/ voice_over/ dirs): counted by scan_audio_spend.
    audio_unit = Decimal(str(UNIT_PRICES["audio_minmax_speech_2_8_hd"]["hard_upper"]))
    for path, payload in _iter_store_transactions(
            audio_transaction_dirs(episode, bgm_transactions_dir=bgm_transactions_dir)):
        state = str(payload.get("state") or "UNKNOWN")
        charge = _transaction_charge(payload)
        credits = (charge if charge is not None
                   else audio_unit if state in AUDIO_CHARGED_STATES and payload.get("task_id") else None)
        rows.append({"source": str(path), "state": state, "credits": credits,
                     "at": _parse_utc(payload.get("intent_recorded_at")),
                     "in_flight": state in AUDIO_UNRESOLVED_STATES})
    return rows


def scan_reservations(episode: str, bgm_transactions_dir: Path | None = None) -> dict[str, Any]:
    """Read active budget reservations (not yet released, and not yet settled).

    A reservation only guards spend that the durable stores cannot see yet.  Once its paid
    step's spend is in those stores (bound / reconciled rows, which ``recorded`` and the pending
    exposure already count), keeping it active counts the same credits twice (lab E02,
    2026-10-24: spend 1069 + 244 of stale reservations).  An unreleased reservation is
    *settled* -- and no longer counted -- when either

    * ``OWNER_ENDED``: its owner process (recorded at reserve time, same host) has exited
      and no transaction intent-recorded since the reservation is still in flight
      (INTENT_RECORDED / unresolved).  Everything the step submitted is then bound,
      reconciled, or blocking the check as unresolved; or
    * ``COVERED_BY_RECORDED_SPEND`` (legacy rows with no owner): the settled transactions
      intent-recorded inside the reservation's window (its ``reserved_at`` up to the next
      reservation's) already count at least its credits, and none in the window is in flight.

    A live owner keeps its reservation whatever the stores say: it may still submit.
    Settled rows are reported in ``settled_reservations``; ``build_report`` appends release
    rows for them (history is never edited).
    """
    ledger = reservation_ledger_path(episode)
    empty = {"active_reservations": [], "active_credits": 0, "settled_reservations": []}
    if not ledger.is_file():
        return empty
    active: dict[str, dict] = {}
    starts: list[datetime] = []
    try:
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rid = row.get("reservation_id")
            if row.get("released_at"):
                active.pop(rid, None)
            elif rid:
                active[rid] = row
                started = _parse_utc(row.get("reserved_at"))
                if started:
                    starts.append(started)
    except (OSError, json.JSONDecodeError):
        pass
    evidence: list[dict[str, Any]] | None = None
    host: str | None = None
    held: list[dict] = []
    settled: list[dict] = []
    for rid, row in active.items():
        started = _parse_utc(row.get("reserved_at"))
        reason = None
        detail: dict[str, Any] = {}
        if started is not None:
            if evidence is None:
                evidence = _spend_evidence(episode, bgm_transactions_dir)
            since = [e for e in evidence if e["at"] is None or e["at"] >= started]
            if isinstance(row.get("owner_pid"), int) and row.get("owner_host"):
                if host is None:
                    import socket  # noqa: PLC0415
                    host = socket.gethostname()
                if (row["owner_host"] == host and not _pid_alive(row["owner_pid"])
                        and not any(e["in_flight"] for e in since)):
                    reason = "OWNER_ENDED"
                    detail = {"owner_pid": row["owner_pid"]}
            elif "owner_pid" not in row:
                later = [s for s in starts if s > started]
                end = min(later) if later else None
                window = [e for e in since if e["at"] is not None and (end is None or e["at"] < end)]
                covered = sum((e["credits"] for e in window if e["credits"] is not None), Decimal("0"))
                if (window and not any(e["in_flight"] for e in window)
                        and not any(e["at"] is None and e["in_flight"] for e in evidence)
                        and covered >= Decimal(str(row.get("credits") or 0))):
                    reason = "COVERED_BY_RECORDED_SPEND"
                    detail = {"covered_credits": number(covered),
                              "window_transactions": [e["source"] for e in window]}
        if reason:
            settled.append({**row, "settle_reason": reason, **detail})
        else:
            held.append(row)
    total = sum((Decimal(str(r.get("credits") or 0)) for r in held), Decimal("0"))
    return {"active_reservations": held, "active_credits": number(total),
            "settled_reservations": settled}


def _latest_credit_statement_mtime(episode: str, *, video: bool) -> datetime | None:
    """Newest mtime of an archived ``*_credit_statement.json`` for this episode, split by category.

    Mirrors the episode filter ``scan_non_video_spend`` already uses (path contains the episode
    code, or the file's own ``episode`` field matches) so this reads the exact same population
    ``recorded_total_credits`` is built from, never a different one.
    """
    latest: datetime | None = None
    for path in ENGINE_ROOT.rglob("*_credit_statement.json"):
        if _is_parked(path.relative_to(ENGINE_ROOT)):
            continue
        is_video = "VIDEO" in path.name.upper()
        if is_video != video:
            continue
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if episode not in str(path) and str(payload.get("episode") or "").upper() != episode:
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if latest is None or mtime > latest:
            latest = mtime
    return latest


def _transaction_bound_at(path: Path, payload: dict[str, Any]) -> datetime:
    """When a bound transaction's charge was POSTed: ``response_recorded_at`` if present and
    parseable, else the transaction file's own mtime (always a safe, available fallback)."""
    raw = str(payload.get("response_recorded_at") or "")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.now(timezone.utc)


def scan_pending_exposure(episode: str) -> Decimal:
    """Estimate pending exposure from SUBMITTED_TASK_ID_BOUND transactions.

    A transaction stays in state ``SUBMITTED_TASK_ID_BOUND`` forever once its generation
    succeeds -- nothing in the normal happy path (unlike the lost-task-id write-off path)
    ever moves it to a settled state.  Its cost is already counted exactly once, for good,
    the moment the submission call's own in-process reconciliation step archives a
    ``*_credit_statement.json`` for that wave: ``recorded_total_credits`` is built by
    scanning every archived statement for the episode (``scan_non_video_spend`` / the video
    guard), not by re-reading transaction files.  Without this check, every unit this
    episode has ever generated keeps being re-added here on every later call, so the
    apparent "pending" total only grows and eventually produces a false
    EPISODE_CREDIT_CAP_WOULD_BE_EXCEEDED long before the cap is actually threatened
    (E12, 2026-10-22: 130 historically-bound transactions inflated this to ~4185 against
    a real outstanding exposure near zero).  A transaction only belongs in this estimate
    while it is genuinely unreconciled: bound more recently than the newest archived
    statement in its own category (video vs image), or bound before any statement in that
    category exists at all yet -- exactly the transient, same-process window this function
    was written for.
    """
    tasks_root = ENGINE_ROOT / "workflow" / "tasks"
    total = Decimal("0")
    latest_statement = {
        True: _latest_credit_statement_mtime(episode, video=True),
        False: _latest_credit_statement_mtime(episode, video=False),
    }
    for dirname in (IMAGE_TRANSACTION_DIRNAME, VIDEO_TRANSACTION_DIRNAME):
        directory = tasks_root / dirname / episode
        if not directory.is_dir():
            continue
        is_video = "video" in dirname
        newest = latest_statement[is_video]
        for path in directory.glob("*.json"):
            try:
                payload = load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            state = str(payload.get("state") or "")
            if isinstance(payload, dict) and is_hopsapi_transaction(payload):
                continue  # HopsAPI leg (video and images): scan_hopsapi_spend (no Giggle statement covers it)
            if state == "SUBMITTED_TASK_ID_BOUND" and payload.get("task_id"):
                if newest is not None and _transaction_bound_at(path, payload) <= newest:
                    continue  # already inside an archived statement that recorded_total_credits counts
                # Read estimated_credits from intent (submitter writes this at INTENT_RECORDED)
                estimated = payload.get("estimated_credits")
                if isinstance(estimated, (int, float)) and estimated > 0:
                    total += Decimal(str(estimated))
                else:
                    # Fallback: conservative upper bound (8s video * 20 cr/s or 11 cr image)
                    if "video" in dirname:
                        total += Decimal("160")
                    else:
                        total += Decimal("11")
    return total


def scan_unevidenced_exposure(episode: str, non_video: dict[str, Any]) -> Decimal:
    """Exposure of SUBMITTED_TASK_ID_BOUND tasks whose charge ``recorded`` does not already count.

    ``scan_pending_exposure`` prices every bound transaction, but a bound task stays in that state
    after its charge is evidenced, so adding it on top of ``recorded`` counted it twice (Twelve
    Gazes E01 S6 resume, 2026-10-22: recorded 822 + pending 822 for the same 35 tasks refused a
    492-credit wave under a 2000 cap).  Here:

    * bound IMAGE tasks are already inside ``recorded`` (the non-video subtotal is at least the
      bound-image upper layer), so they add nothing;
    * bound VIDEO tasks are covered up to the number of rows the SingleGenerateVideo credit
      statements matched -- but only when that batch layer is the one ``recorded`` uses; the rest
      (the most expensive first) stay as exposure, so a bound task with no statement still counts.
    """
    tasks_root = ENGINE_ROOT / "workflow" / "tasks"
    directory = tasks_root / VIDEO_TRANSACTION_DIRNAME / episode
    estimate_rows: list[tuple[str, Decimal]] = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and is_hopsapi_transaction(payload):
            continue  # never matched by a SingleGenerateVideo statement; counted by scan_hopsapi_spend
        if str(payload.get("state") or "") == "SUBMITTED_TASK_ID_BOUND" and payload.get("task_id"):
            estimated = payload.get("estimated_credits")
            estimate_rows.append((str(payload["task_id"]),
                                  Decimal(str(estimated)) if isinstance(estimated, (int, float)) and estimated > 0
                                  else Decimal("160")))
    estimates = [est for _, est in estimate_rows]
    batch_used = (Decimal(str(non_video.get("batch_reconciled_credits") or 0))
                  >= max(Decimal(str(non_video.get("per_task_credits") or 0)),
                         Decimal(str(non_video.get("bound_image_transaction_upper_credits") or 0))))
    matched = 0
    if batch_used:
        for row in non_video.get("batch_rows") or []:
            if (str(row.get("event_description") or "") == "SingleGenerateVideo"
                    and str(row.get("status") or "").startswith("PASS")
                    and isinstance(row.get("matched_count"), int)):
                matched += row["matched_count"]
    # E12 2026-10-30: statement rows carry the video task id as project_id.  A bound task whose own id is
    # on an archived statement row is evidenced exactly; only the rest compete for the id-less batch matches
    # (counting by batch matches alone left 36 charged tasks as exposure: 4506 false credits, cap refused).
    if batch_used:
        charged_ids = _statement_video_task_ids()
        uncovered_rows = [(tid, est) for tid, est in estimate_rows if tid not in charged_ids]
        matched = max(0, matched - (len(estimate_rows) - len(uncovered_rows)))
        estimates = [est for _, est in uncovered_rows]
    uncovered = sorted(estimates, reverse=True)[:max(0, len(estimates) - matched)]
    return sum(uncovered, Decimal("0"))


def _statement_video_task_ids() -> set[str]:
    """Video task ids (project_id) on every archived SingleGenerateVideo statement row of this engine."""
    ids: set[str] = set()
    for path in ENGINE_ROOT.rglob("*_credit_statement.json"):
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        for row in (payload.get("statement_rows") or []) if isinstance(payload, dict) else []:
            if (isinstance(row, dict) and row.get("project_id")
                    and str(row.get("event_description") or "SingleGenerateVideo") == "SingleGenerateVideo"):
                ids.add(str(row["project_id"]))
    return ids


def reserve_credits(episode: str, planned: Decimal, reservation_id: str,
                    cap: Decimal = Decimal(8000)) -> dict[str, Any]:
    """Atomically reserve credits before submission. Returns {"reserved": True/False, ...}."""
    import fcntl  # noqa: PLC0415
    ledger = reservation_ledger_path(episode)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ledger.with_suffix(".lock")
    with lock_path.open("a") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        # Re-scan inside lock
        current_reservations = scan_reservations(episode)
        active_reserved = Decimal(str(current_reservations["active_credits"]))
        # Read recorded spend (no new build_report recursion: use engine gate directly)
        from tools.episode_video_generation_guard import evaluate_episode_credit_gate  # noqa: PLC0415
        video = evaluate_episode_credit_gate(episode)
        video_credits = Decimal(str(video.get("actual_charged_credits_known_total") or 0))
        non_video = scan_non_video_spend(episode, bgm_transactions_dir=None)
        non_video_credits = Decimal(str(non_video["subtotal_credits"]))
        hopsapi = scan_hopsapi_spend(episode)
        recorded = video_credits + non_video_credits + Decimal(str(hopsapi["settled_credits"]))
        pending_exposure = (scan_unevidenced_exposure(episode, non_video)
                            + Decimal(str(hopsapi["pending_exposure_credits"])))
        projected = recorded + active_reserved + pending_exposure + planned
        if projected > cap:
            return {
                "reserved": False,
                "reason": "EPISODE_CREDIT_CAP_WOULD_BE_EXCEEDED",
                "recorded": number(recorded),
                "active_reserved": number(active_reserved),
                "pending_exposure": number(pending_exposure),
                "planned": number(planned),
                "projected": number(projected),
                "cap": number(cap),
            }
        # Write reservation
        reservation = {
            "reservation_id": reservation_id,
            "episode": episode,
            "credits": number(planned),
            "reserved_at": utc_now(),
            "released_at": None,
            **_reservation_owner(),
        }
        with ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(reservation, ensure_ascii=False) + "\n")
        return {
            "reserved": True,
            "reservation_id": reservation_id,
            "credits": number(planned),
            "projected_after_reserve": number(projected),
        }


def release_reservation(episode: str, reservation_id: str, *, reason: str | None = None,
                        evidence: dict[str, Any] | None = None) -> None:
    """Mark a reservation as released (append a release row to the ledger)."""
    import fcntl  # noqa: PLC0415
    ledger = reservation_ledger_path(episode)
    if not ledger.is_file():
        return
    lock_path = ledger.with_suffix(".lock")
    with lock_path.open("a") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        release_row = {
            "reservation_id": reservation_id,
            "episode": episode,
            "credits": 0,
            "reserved_at": None,
            "released_at": utc_now(),
        }
        if reason:
            release_row["release_reason"] = reason
            release_row["auto_release"] = True
        if evidence:
            release_row["release_evidence"] = evidence
        with ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(release_row, ensure_ascii=False) + "\n")


def scan_voice_registry_spend(registry_path: Path | None) -> dict[str, Any]:
    if registry_path is None or not registry_path.is_file():
        return {"registry": str(registry_path) if registry_path else None, "present": False, "credits": 0, "rows": []}
    payload = load_json(registry_path)
    total = Decimal("0")
    rows = []
    for row in payload.get("major_roles") or []:
        credits = row.get("actual_charged_credits")
        if isinstance(credits, (int, float)):
            total += Decimal(str(credits))
            rows.append({
                "entity_id": row.get("entity_id"),
                "credits": credits,
                "credit_status": row.get("credit_status"),
            })
    return {"registry": str(registry_path), "present": True, "credits": number(total), "rows": rows}


# --------------------------------------------------------------------------- #

def build_report(
    *,
    episode: str,
    cap: int,
    planned: Decimal | None,
    balance: dict[str, Any] | None,
    voice_registry: Path | None,
    strict: bool,
    bgm_transactions_dir: Path | None = None,
    reserve_if_pass: bool = False,
    reservation_id: str | None = None,
    audio_transactions_dir: Path | None = None,
) -> dict[str, Any]:
    from tools.episode_video_generation_guard import evaluate_episode_credit_gate  # noqa: PLC0415

    video = evaluate_episode_credit_gate(episode)
    video_credits = Decimal(str(video.get("actual_charged_credits_known_total") or 0))
    non_video = scan_non_video_spend(
        episode, bgm_transactions_dir=bgm_transactions_dir,
        audio_transactions_dir=audio_transactions_dir,
    )
    non_video_credits = Decimal(str(non_video["subtotal_credits"]))
    voices = scan_voice_registry_spend(voice_registry)
    transactions = scan_transaction_states(episode)
    reservations_scan = scan_reservations(episode, bgm_transactions_dir)
    active_reserved = Decimal(str(reservations_scan["active_credits"]))
    # Settled reservations (their spend is already in the stores) get an append-only release row.
    for settled in reservations_scan["settled_reservations"]:
        release_reservation(episode, settled["reservation_id"], reason=settled["settle_reason"],
                            evidence={k: settled[k] for k in ("owner_pid", "covered_credits")
                                      if k in settled})

    # Pending exposure: SUBMITTED_TASK_ID_BOUND tasks whose charge recorded does not already count
    hopsapi = scan_hopsapi_spend(episode)
    hopsapi_settled = Decimal(str(hopsapi["settled_credits"]))
    hopsapi_pending = Decimal(str(hopsapi["pending_exposure_credits"]))
    bound_exposure = scan_pending_exposure(episode) + hopsapi_pending
    pending_exposure = scan_unevidenced_exposure(episode, non_video) + hopsapi_pending

    recorded = video_credits + non_video_credits + hopsapi_settled
    projected = recorded + active_reserved + pending_exposure + (planned or Decimal("0"))
    headroom = Decimal(cap) - recorded - active_reserved - pending_exposure

    failures: list[str] = []
    if planned is not None and projected > Decimal(cap):
        failures.append(
            f"EPISODE_CREDIT_CAP_WOULD_BE_EXCEEDED:recorded={number(recorded)}"
            f":active_reserved={number(active_reserved)}:pending_exposure={number(pending_exposure)}"
            f":planned={number(planned)}:projected={number(projected)}:cap={cap}"
        )
    if recorded > Decimal(cap):
        failures.append(f"EPISODE_CREDIT_CAP_ALREADY_EXCEEDED:{number(recorded)}>{cap}")
    if non_video["successful_attempts_with_unknown_cost"]:
        failures.append(
            f"NON_VIDEO_SUCCESSFUL_SPEND_WITH_UNKNOWN_COST:{non_video['successful_attempts_with_unknown_cost']}"
        )
    if non_video["audio"]["unresolved_transactions"]:
        failures.append(
            f"AUDIO_UNRESOLVED_TRANSACTIONS:{len(non_video['audio']['unresolved_transactions'])}"
        )
    if non_video["bgm_unresolved_transactions"]:
        failures.append(
            f"BGM_UNRESOLVED_TRANSACTIONS:{len(non_video['bgm_unresolved_transactions'])}"
        )
    if transactions["unresolved_transactions"]:
        failures.append(f"UNRECONCILED_TRANSACTIONS:{len(transactions['unresolved_transactions'])}")
    if video.get("status") != "PASS":
        failures.append(f"ENGINE_VIDEO_CREDIT_GATE_{video.get('status')}")
    if strict and balance is not None and not balance.get("ok"):
        failures.append("BALANCE_SNAPSHOT_REQUEST_FAILED")

    # Atomic reservation if requested and check passes
    reservation_result: dict[str, Any] | None = None
    if reserve_if_pass and planned is not None and not failures:
        rid = reservation_id or str(uuid.uuid4())
        reservation_result = reserve_credits(episode, planned, rid, Decimal(cap))
        if not reservation_result.get("reserved"):
            # Reservation failed after check passed: re-read and report
            failures.append(f"RESERVATION_FAILED:{reservation_result.get('reason')}")

    status = "PASS" if not failures else "BLOCKED"
    return {
        "schema": SCHEMA,
        "episode": episode,
        "recorded_at_utc": utc_now(),
        "authority": (
            "RUNTIME_CONFIGURED_EPISODE_CAP (HARD_STOP; paid provider access "
            "is separately validated against a source-receipted line-owner order)"
        ),
        "cap_credits": cap,
        "status": status,
        "failures": failures,
        "spend": {
            "video_credits": number(video_credits),
            "hopsapi_video_credits": hopsapi["by_kind"]["video"]["settled_credits"],
            "hopsapi_image_credits": hopsapi["by_kind"]["image"]["settled_credits"],
            "hopsapi_credits": number(hopsapi_settled),
            "non_video_credits": number(non_video_credits),
            "audio_credits": non_video["audio_credits"],
            "audio_estimated_credits": non_video["audio"]["estimated_credits"],
            "bgm_credits": number(Decimal(str(non_video["bgm_credits"]))
                                  + Decimal(str(non_video["bgm_provisional_credits"]))),
            "recorded_total_credits": number(recorded),
            "active_reserved_credits": number(active_reserved),
            "pending_exposure_credits": number(pending_exposure),
            "bound_exposure_credits": number(bound_exposure),
            "planned_credits": number(planned) if planned is not None else None,
            "projected_total_credits": number(projected) if planned is not None else None,
            "headroom_credits": number(headroom),
            "accounting_complete": (
                bool(video.get("actual_total_complete"))
                and not non_video["successful_attempts_with_unknown_cost"]
                and not non_video["bgm_provisional_rows"]
                and not non_video["bgm_unresolved_transactions"]
                and not non_video["audio"]["estimated_task_count"]
                and not non_video["audio"]["unresolved_transactions"]
                and not transactions["unresolved_transactions"]
                and not hopsapi["unsettled_task_count"]
            ),
        },
        "hopsapi_spend": hopsapi,
        "hopsapi_video_spend": scan_hopsapi_video_spend(episode),
        "engine_video_gate": {
            "tool": "tools/episode_video_generation_guard.evaluate_episode_credit_gate",
            "status": video.get("status"),
            "configured_limit_credits": video.get("configured_limit_credits"),
            "effective_limit_credits": video.get("effective_limit_credits"),
            "actual_charged_credits_known_total": video.get("actual_charged_credits_known_total"),
            "successful_attempt_count": video.get("successful_attempt_count"),
            "successful_unknown_credit_count": video.get("successful_unknown_credit_count"),
            "pending_attempt_count": video.get("pending_attempt_count"),
            "failures": video.get("failures"),
            "note": (
                "This is the engine's VIDEO-ONLY ceiling (default 6000, env "
                "QINGSHAN_EPISODE_VIDEO_CREDIT_LIMIT, or workflow/credit_scopes/<EP>_VIDEO_CREDIT_SCOPE.json). "
                "The nalu 8000 cap covers image + video + audio together and is enforced here on top of it."
            ),
        },
        "non_video_spend": non_video,
        "voice_registry_spend": voices,
        "durable_transaction_stores": transactions,
        "budget_reservations": reservations_scan,
        "reservation_result": reservation_result,
        "unit_prices": UNIT_PRICES,
        "balance_snapshot": balance,
        "release_closure": {
            "tool": "tools/giggle_credit_closure_gate.py --ledger <qingshan.giggle_credit_ledger.v1> --require-actual-credits",
            "gate_id": "GIGGLE-CREDIT-LEDGER-CLOSURE",
            "note": "That gate asserts balance_before - balance_after == actual_credits_total. Those two integers must be entered from the Giggle bill; no endpoint in this engine returns them.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--cap", type=int, default=None, help="Defaults to the live qingshan.json cap (see configured_cap).")
    parser.add_argument("--check", action="store_true", help="Pre-submit gate. Exits 2 when the cap would be exceeded or spend is unreconciled.")
    parser.add_argument("--planned-credits", type=float, default=None)
    parser.add_argument(
        "--refresh-balance",
        action="store_true",
        help="Perform the ONE read-only GET of /api/v1/payment/credit-statements. Omit for a fully offline run.",
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--voice-registry", default=os.environ.get("QINGSHAN_VOICE_REGISTRY") or "")
    parser.add_argument(
        "--bgm-transactions-dir",
        type=Path,
        help=("absolute private BGM transaction directory. Current portable runs pass "
              "<workflow/tasks/giggle_bgm_transactions>/<scope>/<episode>; omission is legacy replay only."),
    )
    parser.add_argument(
        "--audio-transactions-dir",
        type=Path,
        help=("absolute S4 TTS transaction directory (<workflow/tasks/giggle_audio_transactions>/<scope>/<episode>). "
              "Default: the episode's series-scope store plus the legacy <episode> store."),
    )
    parser.add_argument("--out", help="Also write this run's report here (the ledger always gets an entry).")
    parser.add_argument("--strict-balance", action="store_true", help="Treat a failed balance request as a blocking failure.")
    parser.add_argument(
        "--reserve",
        action="store_true",
        help=("Take an atomic reservation for --planned-credits when the check passes.  "
              "The reservation row is written under flock and rescanned inside the lock, so two "
              "racing processes cannot both admit the same headroom.  Use --release-reservation "
              "with the printed reservation_id once the spend is bound or proven not charged."),
    )
    parser.add_argument(
        "--release-reservation",
        help="Release a reservation by id (append a release row; never edit history).",
    )
    args = parser.parse_args()
    if args.cap is None:
        args.cap = configured_cap()

    episode = episode_key(args.episode)
    if args.bgm_transactions_dir is not None and not args.bgm_transactions_dir.is_absolute():
        raise SystemExit("--bgm-transactions-dir must be an absolute private path")
    if args.audio_transactions_dir is not None and not args.audio_transactions_dir.is_absolute():
        raise SystemExit("--audio-transactions-dir must be an absolute path")
    if args.release_reservation:
        release_reservation(episode, args.release_reservation)
        print(json.dumps({"status": "RELEASED", "episode": episode,
                          "reservation_id": args.release_reservation}, ensure_ascii=False))
        return 0
    planned = Decimal(str(args.planned_credits)) if args.planned_credits is not None else None
    if args.check and planned is None:
        raise SystemExit("--check requires --planned-credits (use 0 to audit recorded spend only)")
    if args.reserve and planned is None:
        raise SystemExit("--reserve requires --planned-credits")

    balance = None
    key_source = None
    if args.refresh_balance:
        key_source = load_api_key(Path(args.env_file))
        balance = fetch_balance_snapshot(args.page_size)
        balance["api_key_source"] = key_source
        balance["api_key_disclosure"] = "The key was loaded into this process only. It is not printed, logged, written to any artifact, or exported to any child process."

    report = build_report(
        episode=episode,
        cap=args.cap,
        planned=planned,
        balance=balance,
        voice_registry=Path(args.voice_registry) if args.voice_registry else None,
        strict=args.strict_balance,
        bgm_transactions_dir=args.bgm_transactions_dir,
        reserve_if_pass=bool(args.reserve),
        audio_transactions_dir=args.audio_transactions_dir,
    )
    report["mode"] = "CHECK" if args.check else "RECORD"
    report["network_calls_made"] = 1 if args.refresh_balance else 0

    ledger_path = Path(args.ledger)
    ledger = load_json(ledger_path) if ledger_path.is_file() else {
        "schema": "nalu.episode_credit_budget_ledger_log.v1",
        "cap_credits_per_episode": args.cap,
        "authority": report["authority"],
        "money_rules": "Only GET /api/v1/payment/credit-statements is ever called, at most once per invocation, and only with --refresh-balance. No generation endpoint is reachable from this tool.",
        "entries": [],
        "latest_balance_snapshot": None,
    }
    ledger["cap_credits_per_episode"] = args.cap
    ledger["updated_at_utc"] = utc_now()
    ledger.setdefault("entries", []).append({
        "recorded_at_utc": report["recorded_at_utc"],
        "episode": episode,
        "mode": report["mode"],
        "status": report["status"],
        "cap_credits": args.cap,
        "recorded_total_credits": report["spend"]["recorded_total_credits"],
        "planned_credits": report["spend"]["planned_credits"],
        "projected_total_credits": report["spend"]["projected_total_credits"],
        "headroom_credits": report["spend"]["headroom_credits"],
        "accounting_complete": report["spend"]["accounting_complete"],
        "reservation_result": report.get("reservation_result"),
        "failures": report["failures"],
        "balance_snapshot": balance,
        "network_calls_made": report["network_calls_made"],
    })
    if balance:
        ledger["latest_balance_snapshot"] = balance
    atomic_json(ledger_path, ledger)
    if args.out:
        atomic_json(Path(args.out), report)

    print(json.dumps({
        "status": report["status"],
        "episode": episode,
        "cap_credits": args.cap,
        "recorded_total_credits": report["spend"]["recorded_total_credits"],
        "audio_credits": report["spend"].get("audio_credits"),
        "audio_estimated_credits": report["spend"].get("audio_estimated_credits"),
        "bgm_credits": report["spend"].get("bgm_credits"),
        "planned_credits": report["spend"]["planned_credits"],
        "projected_total_credits": report["spend"]["projected_total_credits"],
        "headroom_credits": report["spend"]["headroom_credits"],
        "accounting_complete": report["spend"]["accounting_complete"],
        "active_reserved_credits": report["spend"].get("active_reserved_credits"),
        # nalu_pipeline.paid_step reads the reservation id from this line to release it once
        # the step exits 0; without it every pipeline reservation stayed active forever.
        "reservation_result": report.get("reservation_result"),
        "auto_released_reservations": [r["reservation_id"] for r in
                                       (report.get("budget_reservations") or {}).get("settled_reservations") or []],
        "balance_availability": (balance or {}).get("balance_availability"),
        "window_net_credits": (balance or {}).get("window_net_credits"),
        "failures": report["failures"],
        "network_calls_made": report["network_calls_made"],
        "ledger": str(ledger_path),
    }, ensure_ascii=False))
    if args.check and report["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
