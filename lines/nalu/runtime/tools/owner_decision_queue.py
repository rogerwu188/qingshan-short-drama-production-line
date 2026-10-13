#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""owner_decision_queue.py — the line's queue of decisions only the line owner can make.

Why this exists (2026-10-10).  Roger: 「整个生产线冗余度太差，随时随地都会因为某个卡点停下来
等待人工确定」.  run_unattended.sh already refused to start while
``runtime/reports/<EP>_OWNER_DECISION_PENDING.md`` existed, but NOTHING wrote that file — the
instruction to the unattended agent was to write prose there by hand.  So the mechanism was a
convention, not a queue, and it was all-or-nothing: one open question froze the entire episode
even when it concerned a single unit.

Two things change here.

* The blocker is RECORDED as a structured entry (what, why, cost, consequence), so it survives
  the session, can be listed and counted, and cannot be silently dropped.
* The blocker has a SCOPE.  A decision about one unit does not stop the other 57; only a
  line-scope decision stops the line.  The four categories the standing orders say must always
  reach the owner (paid categories outside the order, voice consistency, story/dialogue text,
  publication) are forced to line scope and cannot be narrowed — narrowing those is exactly the
  self-authorisation this queue must not become.

The rendered ``<EP>_OWNER_DECISION_PENDING.md`` is a VIEW of the open entries: the owner still
reads one file, but that file is now generated, always current, and lists everything.

Answering: an entry closes only against an active, source-receipted line-owner order from the
private inbox — the same D-11 machinery paid spending already trusts.  There is deliberately no
way for the agent to answer its own question, because a queue the agent can clear is not a queue.

    owner_decision_queue.py raise --episode E11 --class PAID_CATEGORY_NOT_IN_ORDER \
        --what "首个 BGM（两段纯器乐）" --why "订单 paid_stages 不含 S7" \
        --estimate-credits 16 --if-not-done "本集无配乐交付" [--unit-id E11-VU-004] [--stage S7]
    owner_decision_queue.py list   --episode E11 [--status OPEN]
    owner_decision_queue.py render --episode E11
    owner_decision_queue.py status --episode E11 --blocking-line   # exit 5 when the line must stop
    owner_decision_queue.py answer --episode E11 --id <id> --order-seq 29
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
import nalu_paths as _np  # noqa: E402  portable roots

import roger_gate_acceptance as _rga  # noqa: E402  the order/receipt validator

#: The four categories AGENTS.md §4 and the unattended runner say always reach the owner.  These
#: are forced to line scope: a bug or a future edit must not be able to narrow them into
#: "continue without asking".
MUST_ASK = {
    "PAID_CATEGORY_NOT_IN_ORDER": "订单未覆盖的付费类别（首个配乐、换装 i2i、超守卫重拍、缺陷预算超支）",
    "VOICE_CONSISTENCY": "声线一致性失败（VOICE_OUT_OF_BAND / VOICE_COLLISION，K069）",
    "STORY_TEXT_CHANGE": "剧情与台词文本改动",
    "PUBLICATION": "发布/上传（本部署订单未授权）",
}
#: Categories the line may raise without stopping everything.  They can still be line-scope; the
#: raiser chooses.
OTHER_CLASSES = ("ASSET_AMBIGUITY", "CREATIVE_RETRY", "BUDGET_PROJECTION", "OTHER")
CLASSES = tuple(MUST_ASK) + OTHER_CLASSES
SCOPES = ("line", "stage", "unit")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def queue_path(episode: str) -> Path:
    return Path(_np.RUNTIME_ROOT) / "runtime" / "reports" / f"{episode}_OWNER_DECISIONS.jsonl"


def pending_path(episode: str) -> Path:
    return Path(_np.RUNTIME_ROOT) / "runtime" / "reports" / f"{episode}_OWNER_DECISION_PENDING.md"


def load(episode: str) -> list[dict]:
    """Every entry ever raised, oldest first.  Append-only: an entry is never rewritten in place."""
    path = queue_path(episode)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _append(episode: str, entry: dict) -> None:
    path = queue_path(episode)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def current(episode: str) -> list[dict]:
    """Latest state per id: an answer appends a new row, so the last row for an id wins."""
    latest: dict[str, dict] = {}
    order: list[str] = []
    for row in load(episode):
        key = str(row.get("id") or "")
        if key not in latest:
            order.append(key)
        latest[key] = {**(latest.get(key) or {}), **row}
    return [latest[k] for k in order]


def open_entries(episode: str) -> list[dict]:
    return [row for row in current(episode) if row.get("status") == "OPEN"]


def raise_decision(episode: str, *, kind: str, what: str, why: str, if_not_done: str,
                   estimate_credits: float | None = None, stage: str | None = None,
                   unit_id: str | None = None, scope: str | None = None,
                   raised_by: str = "") -> dict:
    if kind not in CLASSES:
        raise SystemExit(f"REFUSED: unknown --class {kind}; one of {', '.join(CLASSES)}")
    if kind in MUST_ASK:
        # not a default that can be overridden — narrowing one of these is the failure mode
        if scope and scope != "line":
            raise SystemExit(f"REFUSED: {kind} must be line scope; narrowing it is not allowed")
        scope = "line"
    scope = scope or "line"
    if scope not in SCOPES:
        raise SystemExit(f"REFUSED: --scope must be one of {', '.join(SCOPES)}")
    if scope in ("unit", "stage") and not (unit_id or stage):
        raise SystemExit("REFUSED: a non-line scope needs --unit-id or --stage to be actionable")
    if not what.strip() or not why.strip() or not if_not_done.strip():
        raise SystemExit("REFUSED: --what, --why and --if-not-done are all required")
    stamp = _now()
    entry_id = f"{episode}-{stamp[:10].replace('-', '')}-{len(current(episode)) + 1:03d}"
    row = {
        "id": entry_id, "episode": episode, "class": kind, "class_label": MUST_ASK.get(kind, ""),
        "scope": scope, "stage": stage, "unit_id": unit_id,
        "what": what.strip(), "why": why.strip(),
        "estimate_credits": estimate_credits,
        "if_not_done": if_not_done.strip(),
        "raised_at": stamp, "raised_by": raised_by or "unattended operator",
        "status": "OPEN", "answered": None,
    }
    _append(episode, row)
    render_pending(episode)
    return row


def _order_binding(episode: str, order_seq: int) -> dict | None:
    """The active, source-receipted line-owner order, or None.  Reuses the paid path's validator."""
    path = os.environ.get("NALU_SUPERVISOR_ORDERS_PATH") or ""
    if not path:
        return None
    expected_latest = int(os.environ.get("NALU_LATEST_ORDER_SEQ") or 0)
    engine = Path(_np.ENGINE_ROOT)
    orders = _rga._orders(path, expected_latest_seq=expected_latest, engine_root=engine)
    if not orders:
        return None
    issuer = os.environ.get("NALU_LINE_OWNER_ID") or ""
    for row in orders:
        if int(row.get("seq") or 0) != order_seq:
            continue
        if (str(row.get("issued_by") or "") != issuer
                or str(row.get("status") or "") != "active"
                or not _rga._receipt_valid(row, expected_issuer=issuer, engine_root=engine)):
            return None
        return row
    return None


def answer_decision(episode: str, entry_id: str, order_seq: int) -> dict:
    entry = next((r for r in current(episode) if r.get("id") == entry_id), None)
    if entry is None:
        raise SystemExit(f"REFUSED: no decision {entry_id} in {queue_path(episode)}")
    if entry.get("status") != "OPEN":
        raise SystemExit(f"REFUSED: {entry_id} is already {entry.get('status')}")
    order = _order_binding(episode, order_seq)
    if order is None:
        raise SystemExit(
            "REFUSED: no active source-receipted line-owner order with seq="
            f"{order_seq}.  A decision closes only against a recorded order; the operator cannot "
            "answer its own question.")
    receipt = order.get("source_receipt") or {}
    row = {
        "id": entry_id, "episode": episode, "status": "ANSWERED",
        "answered": {
            "by": order.get("issued_by"), "at": _now(),
            "order_seq": order.get("seq"), "order_id": order.get("id"),
            "order_verbatim": order.get("order"),
            "source_receipt": {"path": receipt.get("path"), "sha256": receipt.get("sha256")},
        },
    }
    _append(episode, row)
    render_pending(episode)
    return {**entry, **row}


def render_pending(episode: str) -> Path:
    """Write the one file the owner reads.  Removed when nothing is open, so the guard clears."""
    entries = open_entries(episode)
    path = pending_path(episode)
    if not entries:
        path.unlink(missing_ok=True)
        return path
    line_scope = [r for r in entries if r.get("scope") == "line"]
    other = [r for r in entries if r.get("scope") != "line"]
    out = [f"# {episode} 待线主决定", "",
           f"生成于 {_now()} · 共 {len(entries)} 条：{len(line_scope)} 条阻塞整条线，{len(other)} 条只阻塞局部。",
           "",
           "只读这一个文件即可决定。每条写清：要什么、为什么、估算多少、不做的后果。",
           "回答方式：把它记成一条订单（`record_supervisor_order.py`），再 "
           f"`owner_decision_queue.py answer --episode {episode} --id <id> --order-seq <N>`。",
           ""]
    for title, group in (("阻塞整条线", line_scope), ("只阻塞局部（其余单元可继续）", other)):
        if not group:
            continue
        out += [f"## {title}", ""]
        for row in group:
            where = row.get("unit_id") or row.get("stage") or "-"
            cost = row.get("estimate_credits")
            out += [
                f"### {row['id']} · {row.get('class')}"
                + (f" · {row['class_label']}" if row.get("class_label") else ""),
                "",
                f"- **范围**：{row.get('scope')}（{where}）",
                f"- **要什么**：{row.get('what')}",
                f"- **为什么**：{row.get('why')}",
                f"- **估算**：{cost if cost is not None else '不花钱'}",
                f"- **不做的后果**：{row.get('if_not_done')}",
                f"- **提出**：{row.get('raised_at')} · {row.get('raised_by')}",
                "",
            ]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("raise")
    r.add_argument("--episode", required=True)
    r.add_argument("--class", dest="kind", required=True, choices=CLASSES)
    r.add_argument("--what", required=True)
    r.add_argument("--why", required=True)
    r.add_argument("--if-not-done", required=True)
    r.add_argument("--estimate-credits", type=float)
    r.add_argument("--stage")
    r.add_argument("--unit-id")
    r.add_argument("--scope", choices=SCOPES)
    r.add_argument("--raised-by", default="")

    li = sub.add_parser("list")
    li.add_argument("--episode", required=True)
    li.add_argument("--status")

    re_ = sub.add_parser("render")
    re_.add_argument("--episode", required=True)

    st = sub.add_parser("status")
    st.add_argument("--episode", required=True)
    st.add_argument("--blocking-line", action="store_true",
                    help="exit 5 when a line-scope decision is open (the unattended gate)")

    an = sub.add_parser("answer")
    an.add_argument("--episode", required=True)
    an.add_argument("--id", required=True)
    an.add_argument("--order-seq", type=int, required=True)

    args = ap.parse_args()
    if args.cmd == "raise":
        row = raise_decision(args.episode, kind=args.kind, what=args.what, why=args.why,
                             if_not_done=args.if_not_done, estimate_credits=args.estimate_credits,
                             stage=args.stage, unit_id=args.unit_id, scope=args.scope,
                             raised_by=args.raised_by)
        print(json.dumps({"status": "RAISED", "id": row["id"], "scope": row["scope"],
                          "pending_file": str(pending_path(args.episode))}, ensure_ascii=False))
        return 0
    if args.cmd == "list":
        rows = current(args.episode)
        if args.status:
            rows = [x for x in rows if x.get("status") == args.status]
        print(json.dumps({"episode": args.episode, "count": len(rows), "entries": rows},
                         ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "render":
        print(json.dumps({"pending_file": str(render_pending(args.episode)),
                          "open": len(open_entries(args.episode))}, ensure_ascii=False))
        return 0
    if args.cmd == "answer":
        # do the work first: printing before it made a refused answer look like a successful one
        row = answer_decision(args.episode, args.id, args.order_seq)
        print(json.dumps({"status": "ANSWERED", "id": args.id,
                          "order_seq": (row.get("answered") or {}).get("order_seq")},
                         ensure_ascii=False))
        return 0
    # status
    entries = open_entries(args.episode)
    blocking = [r for r in entries if r.get("scope") == "line"]
    print(json.dumps({"episode": args.episode, "open": len(entries),
                      "blocking_line": len(blocking),
                      "ids": [r["id"] for r in entries],
                      "blocking_ids": [r["id"] for r in blocking],
                      "pending_file": str(pending_path(args.episode))}, ensure_ascii=False))
    if args.blocking_line and blocking:
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
