#!/usr/bin/env python3
"""batch_preauthorization.py — per-episode PRE-authorised paid batches (Roger 2026-10-30, 提速闭环 3a).

Problem measured on E12 (scratchpad throughput/01_baseline_E12.md): 15 separate paid launches and
DRY_PLANNED stops cost 34.45 h of HUMAN_AUTH_WAIT, because every paid wave needed the line owner to
start a `--paid` run even though the standing D-11 order already covered the episode.

Model.  The line owner's PAID_PRODUCTION_AUTHORIZATION order (private inbox, D-11) may carry one
extra decision block::

    "batch_preauthorization": {
        "max_credits_per_batch": 2000,      # one wave / one paid stage invocation; JSON null = no batch limit
        "max_units_per_batch": 20,          # JSON null = no batch limit (Roger 2026-10-30 「不设上限」)
        "escalate_on": {"reroll": true, "unit_cost_over_p95": true},
        "unit_cost_p95_credits": 104        # optional fixed P95; else measured from the episode's bound tasks
    }

``evaluate`` returns ALLOW when the batch is inside every limit and contains no escalation case, else
ESCALATE with explicit reason codes.  It ADDS a check on top of D-11, the budget ledger cap, the
K041 whole-batch prompt gate and the durable transaction store; it never relaxes any of them, and
it never decides anything when the order has no ``batch_preauthorization`` block (returns
NOT_CONFIGURED so the caller behaves exactly as before: a human starts every paid run).

Escalation cases (each one is reported, never silently allowed):
  * BATCH_CREDITS_OVER_LIMIT      planned credits of this batch > max_credits_per_batch
  * BATCH_UNITS_OVER_LIMIT        task count > max_units_per_batch
  * REROLL:<task_key>             the task key already has a SUBMITTED_TASK_ID_BOUND transaction in the
                                  durable store (a re-render) and escalate_on.reroll is true
  * UNIT_COST_OVER_P95:<key>:<c>  a single task's estimated credits exceed P95 and escalate_on.unit_cost_over_p95 is true

No network, no credential read, no file writes except the optional --report.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

SCHEMA = "nalu.batch_preauthorization_verdict.v1"
ALLOW, ESCALATE, NOT_CONFIGURED = "ALLOW", "ESCALATE", "NOT_CONFIGURED"
BOUND = "SUBMITTED_TASK_ID_BOUND"


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    k = max(0, min(len(xs) - 1, math.ceil(q * len(xs)) - 1))
    return float(xs[k])


def bound_task_history(tx_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """task_key -> bound transactions already in the durable store (a prior paid take)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for f in glob.glob(str(tx_dir / "*.json")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if d.get("state") == BOUND and d.get("task_key"):
            out.setdefault(str(d["task_key"]), []).append(d)
    return out


def evaluate(order_decision: dict[str, Any], tasks: list[dict[str, Any]], *, planned_credits: int,
             tx_dir: Path | None, credits_of: Any = None) -> dict[str, Any]:
    """Pure decision.  ``tasks`` are the manifest rows about to be priced/authorised; ``credits_of(task)``
    returns the per-task estimated credits (defaults to task['estimated_credits'])."""
    policy = order_decision.get("batch_preauthorization") if isinstance(order_decision, dict) else None
    if not isinstance(policy, dict):
        return {"schema": SCHEMA, "status": NOT_CONFIGURED, "reasons": [], "policy": None}
    credits_of = credits_of or (lambda t: int(t.get("estimated_credits") or 0))
    reasons: list[str] = []
    # Roger 2026-10-30 「自动预授权，不设上限」: a limit written as JSON null means "no batch limit"
    # (the per-episode cap in the same order and the budget ledger still guard every POST).  The key
    # must still be PRESENT: an absent key or a non-positive number is a malformed policy and
    # escalates, so "unlimited" is always an explicit choice in the owner's order.
    def _limit(key: str) -> tuple[int | None, bool]:
        if key not in policy:
            return None, False
        value = policy.get(key)
        if value is None:
            return None, True            # explicit null = unlimited
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None, False
        return (n, True) if n > 0 else (None, False)
    max_credits, credits_ok = _limit("max_credits_per_batch")
    max_units, units_ok = _limit("max_units_per_batch")
    esc = policy.get("escalate_on") or {}
    if not credits_ok or not units_ok:
        reasons.append("POLICY_LIMITS_MUST_BE_POSITIVE_OR_NULL")
    if max_credits is not None and planned_credits > max_credits:
        reasons.append(f"BATCH_CREDITS_OVER_LIMIT:{planned_credits}>{max_credits}")
    if max_units is not None and len(tasks) > max_units:
        reasons.append(f"BATCH_UNITS_OVER_LIMIT:{len(tasks)}>{max_units}")
    history = bound_task_history(tx_dir) if tx_dir else {}
    if esc.get("reroll", True):
        for t in tasks:
            key = str(t.get("task_key") or t.get("unit_id") or "")
            if key in history:
                reasons.append(f"REROLL:{key}:prior_bound_takes={len(history[key])}")
    p95 = policy.get("unit_cost_p95_credits")
    measured_p95 = percentile([int(x.get("estimated_credits") or 0) for rows in history.values() for x in rows], 0.95)
    if p95 is None:
        p95 = measured_p95
    if esc.get("unit_cost_over_p95", True) and p95:
        for t in tasks:
            c = credits_of(t)
            if c > p95:
                reasons.append(f"UNIT_COST_OVER_P95:{t.get('task_key') or t.get('unit_id')}:{c}>{p95:g}")
    return {"schema": SCHEMA, "status": ALLOW if not reasons else ESCALATE, "reasons": reasons,
            "policy": {"max_credits_per_batch": max_credits, "max_units_per_batch": max_units, "escalate_on": esc,
                       "unit_cost_p95_credits": p95, "p95_source": "ORDER" if policy.get("unit_cost_p95_credits") is not None else "MEASURED_BOUND_TASKS"},
            "batch": {"planned_credits": planned_credits, "task_count": len(tasks),
                      "task_keys": [str(t.get("task_key") or t.get("unit_id")) for t in tasks]}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--order-decision", required=True, help="json file holding the order's decision block")
    ap.add_argument("--manifest", required=True, help="video/image transaction manifest (tasks[])")
    ap.add_argument("--tx-dir", help="durable transaction store dir for this episode")
    ap.add_argument("--planned-credits", type=int, required=True)
    ap.add_argument("--report")
    args = ap.parse_args()
    decision = json.loads(Path(args.order_decision).read_text(encoding="utf-8"))
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    tasks = manifest.get("tasks") or manifest.get("items") or []
    verdict = evaluate(decision, tasks, planned_credits=args.planned_credits,
                       tx_dir=Path(args.tx_dir) if args.tx_dir else None)
    if args.report:
        Path(args.report).write_text(json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=1))
    return 0 if verdict["status"] in (ALLOW, NOT_CONFIGURED) else 5


if __name__ == "__main__":
    sys.exit(main())
