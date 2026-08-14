#!/usr/bin/env python3
"""Keep a local evidence gate live without treating the gate itself as approval."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path


def scan(root: Path, tokens: list[str], excluded: Path) -> list[dict]:
    hits = []
    if not root.exists():
        return hits
    for path in sorted(root.rglob("*")):
        if path.resolve() == excluded.resolve():
            continue
        if "EVIDENCE_GATE" in path.name:
            continue
        if not path.is_file() or path.suffix.lower() not in {".json", ".md", ".txt", ".yaml", ".yml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if all(token in text for token in tokens):
            hits.append({"path": str(path), "tokens": tokens})
    return hits


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--episode", required=True)
    p.add_argument("--root", action="append", required=True)
    p.add_argument("--token", action="append", required=True)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--interval", type=int, default=60)
    args = p.parse_args()
    while True:
        hits = []
        for raw in args.root:
            hits.extend(scan(Path(raw), args.token, args.out))
        receipt = {
            "schema": "qingshan.evidence_gate_watch.v1",
            "episode": args.episode,
            "status": "APPROVED_EVIDENCE_FOUND" if hits else "BLOCKED_MISSING_APPROVED_EVIDENCE",
            "required_tokens": args.token,
            "search_roots": args.root,
            "approved_evidence_hits": hits,
            "watch_pid": __import__("os").getpid(),
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "next_trigger": "rerun B3 preflight and start the white-carp reveal wave when both tokens occur in an approved evidence file",
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if hits:
            return 0
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
