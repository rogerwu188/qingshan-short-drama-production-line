#!/usr/bin/env python3
"""record_paid_production_order.py — the line-owner interface that writes ONE paid-production order.

``materialize_paid_authorization.py`` (D-11) refuses every paid submit unless a private, source-receipted
order of kind ``PAID_PRODUCTION_AUTHORIZATION`` exists.  The line owner writes it through this tool after
saying so in chat.  Since 2026-09-22 (SUPERVISOR_ORDERS seq=54, Roger: 「修改这个要求及代码，无需我本人同意」)
the operator may also transcribe an order the owner has ALREADY given — passing ``--recorded-by`` plus
``--authorizing-order-ref``, which name who typed it and where the owner said it, so the receipt never
claims the owner sat at the keyboard.  Transcription only: the words stay verbatim, and widening the
scope (more episodes, a higher cap, publication) still needs the owner to say so first.  Like
``record_supervisor_order.py`` the shape is fixed and auditable: ``--order`` is the owner's reply
verbatim, every other field is typed, and the receipt is bound by SHA-256 so the row cannot be edited
afterwards without breaking the binding.

    record_paid_production_order.py \
        --orders   $NALU_RUNTIME_ROOT/runtime/SUPERVISOR_ORDERS.json \
        --owner-id roger --order "同意 E01 付费生产" \
        --episode E01 [--episode E02 ...] --stages S3,S4,S5,S6 --cap 8000 \
        --rights-basis "<owner's rights statement, verbatim>" \
        [--rights-scope "..."] [--publication-allowed] [--work "佛本是道"]

Prints the ``authorization`` block to put into ``$NALU_RUNTIME_ROOT/qingshan.json`` (or the equivalent
``NALU_*`` environment variables).  Never touches the public engine checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nalu_paths as _np  # noqa: E402

ORDERS_SCHEMA = "supervisor_orders_v1"
RECEIPT_SCHEMA = "qingshan.line_owner_order_source_receipt.v1"
KIND = "PAID_PRODUCTION_AUTHORIZATION"
SD2 = "seedance-2.0-pro"
STAGES = ("S3", "S4", "S5", "S6")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orders", required=True, help="absolute path of the PRIVATE orders inbox (outside the engine)")
    ap.add_argument("--owner-id", required=True, help="line owner id; must equal NALU_LINE_OWNER_ID")
    ap.add_argument("--order", required=True, help="the owner's reply, verbatim")
    ap.add_argument("--episode", action="append", required=True, help="repeatable; exact episode ids")
    ap.add_argument("--stages", default="S3,S4,S5,S6", help="explicit subset of S3..S6")
    ap.add_argument("--cap", type=int, default=8000, help="budget cap credits per episode")
    ap.add_argument("--rights-basis", required=True, help="owner's rights statement, verbatim")
    ap.add_argument("--rights-scope", default="")
    ap.add_argument("--publication-allowed", action="store_true")
    ap.add_argument("--work", default="")
    ap.add_argument("--receipt-dir", default="", help="default: <orders dir>/order_receipts")
    ap.add_argument("--recorded-by", default="",
                    help="who typed this in.  Default: the line owner.  An operator materialising the "
                         "owner's already-given standing order says so here and must also pass "
                         "--authorizing-order-ref.")
    ap.add_argument("--authorizing-order-ref", default="",
                    help="where the owner gave the order being transcribed (e.g. "
                         "'SUPERVISOR_ORDERS.json seq=3 + seq=54').  Required with --recorded-by.")
    a = ap.parse_args()

    engine = Path(f"{_np.ENGINE_ROOT}").resolve()
    orders_path = Path(a.orders).expanduser()
    if not orders_path.is_absolute():
        print(json.dumps({"status": "FAIL", "error": "ORDERS_PATH_MUST_BE_ABSOLUTE"})); return 2
    orders_path = orders_path.resolve()
    try:
        orders_path.relative_to(engine)
        print(json.dumps({"status": "FAIL", "error": f"ORDERS_PATH_MUST_BE_OUTSIDE_PUBLIC_ENGINE_ROOT:{orders_path}"})); return 2
    except ValueError:
        pass
    stages = [s.strip() for s in a.stages.split(",") if s.strip()]
    if not stages or any(s not in STAGES for s in stages):
        print(json.dumps({"status": "FAIL", "error": "STAGES_MUST_BE_SUBSET_OF_S3_S4_S5_S6"})); return 2
    if not a.order.strip() or not a.rights_basis.strip():
        print(json.dumps({"status": "FAIL", "error": "ORDER_AND_RIGHTS_BASIS_MUST_BE_VERBATIM_NONEMPTY"})); return 2
    if a.recorded_by.strip() and not a.authorizing_order_ref.strip():
        print(json.dumps({"status": "FAIL", "error": "RECORDED_BY_REQUIRES_AUTHORIZING_ORDER_REF"})); return 2

    payload = json.loads(orders_path.read_text(encoding="utf-8")) if orders_path.is_file() else {
        "_schema": ORDERS_SCHEMA, "_purpose": "private line-owner orders inbox (never in the public engine)",
        "orders": [], "latest_order_seq": 0}
    if payload.get("_schema") != ORDERS_SCHEMA:
        print(json.dumps({"status": "FAIL", "error": f"ORDERS_SCHEMA_INVALID:{payload.get('_schema')}"})); return 2
    rows = payload.setdefault("orders", [])
    seqs = [int(r.get("seq")) for r in rows if isinstance(r, dict) and isinstance(r.get("seq"), int)]
    seq = (max(seqs) if seqs else 0) + 1
    episodes = sorted(dict.fromkeys(a.episode))
    now = utc_now()
    order_id = f"{a.owner_id.upper()}-{datetime.now().strftime('%Y%m%d')}-{'-'.join(episodes)}-PAID"

    receipt_dir = Path(a.receipt_dir).expanduser().resolve() if a.receipt_dir else orders_path.parent / "order_receipts"
    receipt_path = receipt_dir / f"order_seq{seq:03d}_{order_id}.receipt.json"
    recorded_by = a.recorded_by.strip() or "the line owner"
    write_json(receipt_path, {
        "schema": RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": a.owner_id,
        "order_seq": seq, "order_id": order_id, "verbatim": a.order, "recorded_at_utc": now,
        "recorded_by": f"record_paid_production_order.py run by {recorded_by} "
                       "(owner's words verbatim; nothing inferred)",
        "authorizing_order_ref": a.authorizing_order_ref.strip() or None,
    })
    row = {
        "seq": seq, "id": order_id, "type": "PAID_PRODUCTION_AUTHORIZATION", "status": "active",
        "issued_by": a.owner_id, "ts_utc": now, "ts_pdt": None, "to": "nalu production line",
        "work": a.work or None, "order": a.order,
        "recorded_by": recorded_by,
        "authorizing_order_ref": a.authorizing_order_ref.strip() or None,
        "source_receipt": {"path": str(receipt_path), "sha256": sha256_file(receipt_path)},
        "decision": {
            "kind": KIND, "paid_requests_allowed": True, "paid_stages": stages,
            "episode_scope": episodes, "budget_cap_credits_per_episode": a.cap,
            "video_model": SD2, "rights_basis": a.rights_basis, "rights_declared_by": a.owner_id,
            "rights_scope": a.rights_scope, "publication_allowed": bool(a.publication_allowed),
        },
        "conditions": [
            {"id": "PAID_REQUESTS_EXPLICITLY_AUTHORIZED", "severity": "AUTHORIZATION",
             "text": f"Paid provider requests are authorised for {', '.join(episodes)} in stages {', '.join(stages)}."},
            {"id": "BUDGET_CAP_PER_EPISODE", "severity": "HARD_STOP",
             "text": f"Budget cap {a.cap} credits per episode; the offline ledger guard stops any paid step that would exceed {a.cap}."},
            {"id": "VIDEO_MODEL_SD2_ONLY", "severity": "HARD_STOP",
             "text": f"Video generation uses {SD2} only; no fast/mini substitutes."},
            {"id": "RIGHTS_BASIS_DECLARED", "severity": "AUTHORIZATION",
             "text": "Rights basis declared by the line owner (verbatim in decision.rights_basis); the engine records it and does not verify it."},
            {"id": "NO_PLATFORM_PUBLICATION", "severity": "HARD_STOP",
             "text": "No platform publication." if not a.publication_allowed else "Publication allowed by the owner."},
        ],
    }
    rows.append(row)
    payload["latest_order_seq"] = seq
    payload["updated_at_utc"] = now
    write_json(orders_path, payload)
    print(json.dumps({
        "status": "PASS", "orders": str(orders_path), "seq": seq, "order_id": order_id, "receipt": str(receipt_path),
        "qingshan_json_authorization": {"supervisor_orders_path": str(orders_path), "paid_order_seq": seq,
                                        "latest_order_seq": seq, "line_owner_id": a.owner_id},
        "env_equivalent": {"NALU_SUPERVISOR_ORDERS_PATH": str(orders_path), "NALU_PAID_ORDER_SEQ": str(seq),
                           "NALU_LATEST_ORDER_SEQ": str(seq), "NALU_LINE_OWNER_ID": a.owner_id},
        "note": "latest_order_seq changes whenever another order is appended; update the authorization block then.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
