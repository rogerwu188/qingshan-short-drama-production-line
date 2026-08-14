#!/usr/bin/env python3
"""pre_send_negative_claim_recheck.py — SM-METHOD-004, wired.

WHY THIS EXISTS
---------------
CL2X-1027 established SM-METHOD-004: any *negative status claim* in a mailbox
entry — "has not replied", "has not responded", "has not consumed the order",
"heartbeat has not landed", "still STALL" — must be re-sampled at the last
moment before sending, never carried over from the round-opening snapshot.

CL2X-1028, the very next round, published exactly such a claim ("Writer R194
heartbeat has not landed") that was already false at publish time: the mailbox
mtime was 13:30, the sample was ~13:27, the send was ~13:33.

Recurrence interval: one round. The shortest possible.

Root cause was not judgement. It was that the rule lived only as prose in a
mailbox entry, and nothing in the round procedure re-sampled anything. That is
the same disease this supervisor has reported at the production line for six
consecutive rounds — "a gate that is written but never wired up is the same as
no gate" — turned on itself.

So: this file. Run it immediately before every mailbox send. It re-samples the
things negative claims are made about, and prints them with a wall-clock stamp
so a stale claim cannot be shipped quietly.

USAGE
-----
    python3 tools/pre_send_negative_claim_recheck.py
    python3 tools/pre_send_negative_claim_recheck.py --draft codex_docs/CLAUDE_TO_CODEX.md

With --draft, the file's first entry is scanned for negative-claim phrasing and
each hit is printed next to the freshly sampled value, so the two can be
compared by eye before sending. The script never edits anything and never
blocks: it is an evidence-freshness printer, not a gate. Its only job is to
make "I sampled this 6 minutes ago" impossible to do without noticing.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys

REPO_CANDIDATES = [
    "/sessions/*/mnt/qingshan_short_drama",
    os.path.expanduser("~/qingshan_short_drama"),
    ".",
]

# Phrases that assert a negative state about another agent. Deliberately broad:
# a false positive costs one line of output, a false negative costs a wrong
# claim published to every downstream reader.
NEGATIVE_CLAIM_PATTERNS = [
    r"未落", r"未回", r"未接", r"未取", r"未响应", r"未消费", r"未接线", r"未修",
    r"零回执", r"仍是?\s*R\d+", r"顶条仍", r"无新增", r"无响应", r"静默",
    r"STALL", r"未提交", r"未交付", r"至今无", r"从未",
    r"has not", r"no reply", r"no response", r"still R\d+", r"not landed",
]


def _repo_root() -> str:
    import glob

    for pat in REPO_CANDIDATES:
        for hit in sorted(glob.glob(pat)):
            if os.path.isdir(os.path.join(hit, "codex_docs")):
                return hit
    raise SystemExit("could not locate the qingshan repo root")


def _now() -> str:
    return _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _mtime(path: str) -> str:
    try:
        return _dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m-%d %H:%M:%S")
    except OSError:
        return "MISSING"


def _first_line(path: str, limit: int = 160) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.readline().rstrip("\n")[:limit]
    except OSError:
        return "MISSING"


def _last_matching_line(path: str, pattern: str, limit: int = 160) -> str:
    """Last line matching pattern — for mailboxes where one party appends at the tail."""
    rx = re.compile(pattern)
    found = "none"
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if rx.match(line):
                    found = line.rstrip("\n")[:limit]
    except OSError:
        return "MISSING"
    return found


def sample_mailboxes(root: str) -> dict:
    c2c = os.path.join(root, "codex_docs", "CLAUDE_TO_CODEX.md")
    c2cl = os.path.join(root, "workflow", "CODEX_TO_CLAUDE.md")
    out = {
        "CLAUDE_TO_CODEX.md": {
            "mtime": _mtime(c2c),
            "top_entry": _first_line(c2c),
        },
        # Mixed ordering: Writer heartbeats are prepended at the top, codex X2CL
        # entries are appended at the tail. Both ends must be read (M-086).
        "CODEX_TO_CLAUDE.md": {
            "mtime": _mtime(c2cl),
            "top_entry_writer_heartbeat": _first_line(c2cl),
            "tail_entry_codex_x2cl": _last_matching_line(c2cl, r"^#\s*\[?X2CL"),
        },
    }
    return out


def sample_orders(root: str) -> dict:
    out = {}
    for rel in ("workflow/SUPERVISOR_ORDERS.json", "SUPERVISOR_ORDERS.json"):
        p = os.path.join(root, rel)
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                out["latest_order_seq"] = d.get("latest_order_seq")
            except Exception as exc:  # noqa: BLE001
                out["error"] = f"{type(exc).__name__}: {exc}"
            out["path"] = rel
            out["mtime"] = _mtime(p)
            break
    wq = os.path.join(root, "workflow", "work_queue.json")
    if os.path.exists(wq):
        try:
            out["work_queue_updated_at"] = json.load(open(wq, encoding="utf-8")).get("updated_at")
        except Exception as exc:  # noqa: BLE001
            out["work_queue_error"] = f"{type(exc).__name__}: {exc}"
        out["work_queue_mtime"] = _mtime(wq)
    return out


def sample_writer_progress(root: str) -> dict:
    p = os.path.join(root, "workflow", "claude_writer_agent", "PROGRESS.json")
    if not os.path.exists(p):
        return {"path": "MISSING"}
    info = {"mtime": _mtime(p)}
    try:
        d = json.load(open(p, encoding="utf-8"))
        rounds = d if isinstance(d, list) else d.get("rounds") or d.get("progress") or []
        if isinstance(rounds, list) and rounds:
            head = rounds[0]
            info["top_round"] = head if isinstance(head, str) else str(head)[:200]
        else:
            info["top_round"] = str(d)[:200]
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def sample_s3(root: str) -> dict:
    """Re-list the relay channels by LastModified. Returns a note on failure.

    Deliberately best-effort: this printer must never be the reason a send is
    skipped. A missing S3 reading is reported as such rather than silently
    omitted, because "channel had no new items" and "I could not check the
    channel" are the exact two things that must not look alike.
    """
    try:
        sys.path.insert(0, f"/tmp/qslibs.uid{os.getuid()}")
        import boto3  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"status": f"UNAVAILABLE ({type(exc).__name__}) — report as 'not checked', never as 'nothing new'", "detail": str(exc)[:120]}

    bucket = os.environ.get("S3_RELAY_BUCKET")
    endpoint = os.environ.get("S3_RELAY_ENDPOINT")
    prefix = (os.environ.get("S3_RELAY_PREFIX") or "").rstrip("/")
    if not bucket or not endpoint:
        return {"status": "UNAVAILABLE (credentials not sourced) — report as 'not checked'"}

    cli = boto3.client("s3", endpoint_url=endpoint, region_name="auto")
    out = {}
    for ch in ("c2sc", "sc2c", "claude"):
        pre = f"{prefix}/{ch}/" if prefix else f"{ch}/"
        objs, token = [], None
        try:
            while True:
                kw = {"Bucket": bucket, "Prefix": pre}
                if token:
                    kw["ContinuationToken"] = token
                r = cli.list_objects_v2(**kw)
                objs += r.get("Contents", [])
                if not r.get("IsTruncated"):
                    break
                token = r["NextContinuationToken"]
        except Exception as exc:  # noqa: BLE001
            out[ch] = {"status": f"ERROR {type(exc).__name__}"}
            continue
        objs.sort(key=lambda o: o["LastModified"])
        out[ch] = {
            "count": len(objs),
            "newest": (
                {
                    "last_modified": objs[-1]["LastModified"].isoformat(),
                    "key": objs[-1]["Key"].split("/")[-1][:80],
                }
                if objs
                else None
            ),
        }
    return out


def scan_draft(path: str) -> list[tuple[int, str, str]]:
    """Find negative-claim phrasing in the draft's first entry."""
    hits: list[tuple[int, str, str]] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
    except OSError:
        return hits
    # First entry only: up to the second top-level heading.
    end = len(lines)
    for i, ln in enumerate(lines[1:], start=1):
        if ln.startswith("# "):
            end = i
            break
    for i, ln in enumerate(lines[:end], start=1):
        for pat in NEGATIVE_CLAIM_PATTERNS:
            m = re.search(pat, ln)
            if m:
                hits.append((i, m.group(0), ln.strip()[:150]))
                break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--draft", help="mailbox file whose first entry should be scanned for negative claims")
    ap.add_argument("--json", action="store_true", help="emit the sample as JSON")
    args = ap.parse_args()

    root = _repo_root()
    sample = {
        "resampled_at": _now(),
        "repo_root": root,
        "mailboxes": sample_mailboxes(root),
        "orders": sample_orders(root),
        "writer_progress": sample_writer_progress(root),
        "s3_channels": sample_s3(root),
    }

    if args.json:
        print(json.dumps(sample, ensure_ascii=False, indent=2))
    else:
        print("=" * 72)
        print(f"SM-METHOD-004 pre-send re-sample  @ {sample['resampled_at']}")
        print("=" * 72)
        for name, info in sample["mailboxes"].items():
            print(f"\n[{name}]  mtime={info['mtime']}")
            for k, v in info.items():
                if k != "mtime":
                    print(f"   {k}: {v}")
        print(f"\n[orders] {json.dumps(sample['orders'], ensure_ascii=False)}")
        print(f"[writer PROGRESS] {json.dumps(sample['writer_progress'], ensure_ascii=False)[:400]}")
        print(f"\n[s3 channels] {json.dumps(sample['s3_channels'], ensure_ascii=False, indent=2)}")

    if args.draft:
        hits = scan_draft(args.draft)
        print("\n" + "=" * 72)
        print(f"negative-claim phrases in first entry of {args.draft}: {len(hits)}")
        print("=" * 72)
        for line_no, phrase, text in hits:
            print(f"  L{line_no} [{phrase}] {text}")
        if hits:
            print(
                "\n  ^ compare each of these against the freshly sampled values above.\n"
                "    CL2X-1028 shipped one of these on a 6-minute-stale sample."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
