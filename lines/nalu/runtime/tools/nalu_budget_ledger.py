#!/usr/bin/env python3
"""Read-only per-episode credit budget guard for the nalu line.

Standing order: SUPERVISOR_ORDERS.json seq=3, condition 2
`BUDGET_CAP_8000_PER_EPISODE`, severity HARD_STOP — image + video + audio for
one episode must total <= 8000 credits, and the orchestrator must estimate
against the ledger BEFORE submitting, stopping and escalating instead of
silently degrading quality or skipping a gate.

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
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(os.environ.get("QINGSHAN_ENGINE_ROOT", f"{_np.ENGINE_ROOT}"))
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

SCHEMA = "nalu.episode_credit_budget_ledger.v1"
DEFAULT_CAP = 8000
DEFAULT_LEDGER = Path(f"{_np.RUNTIME_ROOT}/runtime/budget/ledger.json")
DEFAULT_ENV_FILE = ENGINE_ROOT / ".env"

STATEMENT_PATH = "/api/v1/payment/credit-statements"

# Observed authoritative unit prices, each with its in-repo evidence. Used for
# planning only; the actual charge always comes from the statement ledger.
UNIT_PRICES = {
    "image_gpt_image_2_pro": {
        "credits": 5,
        "hard_upper": 11,
        "evidence": "tools/e40_u12_v3_image_paid_preflight.py:35-36 EXPECTED_IMAGE_PRICE=5 / EXPECTED_UPPER=11",
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
}
# States that are settled: either bound to a task whose charge is recorded
# elsewhere, or verified as never charged.
SETTLED_TRANSACTION_STATES = {"SUBMITTED_TASK_ID_BOUND", "VERIFIED_ZERO_RETRYABLE", "NOT_CHARGED_RETRYABLE"}

VIDEO_TRANSACTION_DIRNAME = "giggle_video_submit_transactions"
IMAGE_TRANSACTION_DIRNAME = "giggle_submit_transactions"


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

def _iter_task_json(root: Path):
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.json")):
        try:
            yield path, load_json(path)
        except (OSError, json.JSONDecodeError):
            continue


def scan_non_video_spend(episode: str) -> dict[str, Any]:
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
    for path in sorted(ENGINE_ROOT.rglob("*_credit_statement.json")):
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if episode not in str(path) and str(payload.get("episode") or "").upper() != episode:
            continue
        credits = payload.get("charged_credits")
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
    bgm_unknown = 0
    for path in sorted((tasks_root / "giggle_bgm_transactions" / episode).glob("*.json")):
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("state") != "COMPLETED":
            continue
        credits = (payload.get("credit") or {}).get("net_charged_credits")
        if isinstance(credits, (int, float)):
            bgm_total += Decimal(str(credits))
            bgm_rows.append({"source": str(path), "task_id": payload.get("task_id"), "credits": credits,
                             "statement_status": (payload.get("credit") or {}).get("statement_status"),
                             "isolation": (payload.get("credit") or {}).get("isolation")})
        else:
            bgm_unknown += 1

    bound_image_upper = Decimal(len(bound_image_task_ids)) * Decimal(str(
        UNIT_PRICES["image_gpt_image_2_pro"]["hard_upper"]
    ))
    return {
        "per_task_credits": number(per_task),
        "per_task_rows": per_task_rows,
        "successful_attempts_with_unknown_cost": unknown_success + bgm_unknown,
        "batch_reconciled_credits": number(batch_total),
        "batch_rows": batch_rows,
        "bound_image_transaction_count": len(bound_image_task_ids),
        "bound_image_transaction_upper_credits": number(bound_image_upper),
        "bound_image_transaction_rows": bound_image_rows,
        "bgm_credits": number(bgm_total),
        "bgm_rows": bgm_rows,
        "double_count_policy": (
            "per_task, batch-reconciliation, and accepted image-transaction layers are reported "
            "separately and the largest is used as the non-video subtotal. The transaction layer "
            "uses the observed image hard upper, so it cannot undercount receipts stored outside "
            "the engine clone; summing the layers would double count."
        ),
        "subtotal_credits": number(max(per_task, batch_total, bound_image_upper) + bgm_total),
    }


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
) -> dict[str, Any]:
    from tools.episode_video_generation_guard import evaluate_episode_credit_gate  # noqa: PLC0415

    video = evaluate_episode_credit_gate(episode)
    video_credits = Decimal(str(video.get("actual_charged_credits_known_total") or 0))
    non_video = scan_non_video_spend(episode)
    non_video_credits = Decimal(str(non_video["subtotal_credits"]))
    voices = scan_voice_registry_spend(voice_registry)
    transactions = scan_transaction_states(episode)

    recorded = video_credits + non_video_credits
    projected = recorded + (planned or Decimal("0"))
    headroom = Decimal(cap) - recorded

    failures: list[str] = []
    if planned is not None and projected > Decimal(cap):
        failures.append(
            f"EPISODE_CREDIT_CAP_WOULD_BE_EXCEEDED:recorded={number(recorded)}"
            f":planned={number(planned)}:projected={number(projected)}:cap={cap}"
        )
    if recorded > Decimal(cap):
        failures.append(f"EPISODE_CREDIT_CAP_ALREADY_EXCEEDED:{number(recorded)}>{cap}")
    if non_video["successful_attempts_with_unknown_cost"]:
        failures.append(
            f"NON_VIDEO_SUCCESSFUL_SPEND_WITH_UNKNOWN_COST:{non_video['successful_attempts_with_unknown_cost']}"
        )
    if transactions["unresolved_transactions"]:
        failures.append(f"UNRECONCILED_TRANSACTIONS:{len(transactions['unresolved_transactions'])}")
    if video.get("status") != "PASS":
        failures.append(f"ENGINE_VIDEO_CREDIT_GATE_{video.get('status')}")
    if strict and balance is not None and not balance.get("ok"):
        failures.append("BALANCE_SNAPSHOT_REQUEST_FAILED")

    status = "PASS" if not failures else "BLOCKED"
    return {
        "schema": SCHEMA,
        "episode": episode,
        "recorded_at_utc": utc_now(),
        "authority": "SUPERVISOR_ORDERS.json seq=3 condition 2 BUDGET_CAP_8000_PER_EPISODE (HARD_STOP)",
        "cap_credits": cap,
        "status": status,
        "failures": failures,
        "spend": {
            "video_credits": number(video_credits),
            "non_video_credits": number(non_video_credits),
            "recorded_total_credits": number(recorded),
            "planned_credits": number(planned) if planned is not None else None,
            "projected_total_credits": number(projected) if planned is not None else None,
            "headroom_credits": number(headroom),
            "accounting_complete": (
                bool(video.get("actual_total_complete"))
                and not non_video["successful_attempts_with_unknown_cost"]
                and not transactions["unresolved_transactions"]
            ),
        },
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
    parser.add_argument("--cap", type=int, default=int(os.environ.get("NALU_EPISODE_CREDIT_CAP", DEFAULT_CAP)))
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
    parser.add_argument("--out", help="Also write this run's report here (the ledger always gets an entry).")
    parser.add_argument("--strict-balance", action="store_true", help="Treat a failed balance request as a blocking failure.")
    args = parser.parse_args()

    episode = episode_key(args.episode)
    planned = Decimal(str(args.planned_credits)) if args.planned_credits is not None else None
    if args.check and planned is None:
        raise SystemExit("--check requires --planned-credits (use 0 to audit recorded spend only)")

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
        "planned_credits": report["spend"]["planned_credits"],
        "projected_total_credits": report["spend"]["projected_total_credits"],
        "headroom_credits": report["spend"]["headroom_credits"],
        "accounting_complete": report["spend"]["accounting_complete"],
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
