#!/usr/bin/env python3
"""review_dispatch.py — run a machine review (vlm_review_protocol request) as N parallel, unit-scoped
workers, then merge one answers file (Roger 2026-10-30, 提速闭环 3b).

Measured problem (scratchpad throughput/01_baseline_E12.md): E12 answered 1033 review items in 80
requests; the request→submit latency summed to 104 h and the gaps after REVIEW_REQUIRED runs to 164 h,
because every review was answered serially inside one interactive Claude Code session whose context
carried the whole episode.

What this tool does (no provider call, no money, no production state change):
  1. ``shard``  — split one request's ``items`` into K shards of at most --items-per-shard items
                  (one shard = one unit by default), each shard a self-contained request file carrying
                  only its own items plus the shared questionnaire / answer_rules / closed vocabulary.
  2. ``run``    — start up to --workers worker processes in parallel.  A worker is any command
                  template that reads a shard request and writes a shard answers file in the
                  ``nalu.vlm_review_answers.v1`` shape (e.g. a headless `claude -p` call with a
                  unit-scoped prompt, or a deterministic fill script).  The template receives
                  {shard} and {out}.  With --replay <answers.json> the "worker" copies the recorded
                  answers for the shard's items (offline measurement / tests); --replay-latency-ms
                  sleeps that long per item so the parallel speed-up can be measured without a model.
  3. ``merge``  — concatenate shard answers into ONE answers file bound to the ORIGINAL request
                  (request_path / request_sha256), refusing when any item is missing or duplicated.
                  Submission still goes through vlm_review_protocol.py submit, i.e. through the same
                  validation and the same gates as before; this tool never submits.

Workers see only their shard: the context a review needs is the unit's expectations and media, not
the episode.  Review correctness is unchanged — the questionnaire, enum answers, observation
minimum and defect rules are copied verbatim into each shard.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SHARED_KEYS = ("schema", "request_id", "kind", "episode", "created_at", "created_by", "visual_post_qa_profile",
               "visual_post_qa_policy", "reviewer_contract", "questionnaire", "observed_fields",
               "identity_measurement_decision", "answer_rules", "answers_schema", "next_commands")
ANSWERS_SCHEMA = "nalu.vlm_review_answers.v1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shard_request(request: dict[str, Any], *, items_per_shard: int = 1) -> list[dict[str, Any]]:
    items = list(request.get("items") or [])
    shared = {k: request[k] for k in SHARED_KEYS if k in request}
    shards = []
    for i in range(0, len(items), max(1, items_per_shard)):
        chunk = items[i:i + items_per_shard]
        shards.append({**shared, "items": chunk, "item_count": len(chunk),
                       "shard": {"index": len(shards), "item_ids": [it["item_id"] for it in chunk],
                                 "parent_request_id": request.get("request_id"), "parent_item_count": len(items)}})
    return shards


def merge_answers(request_path: Path, shard_answers: list[dict[str, Any]], *, reviewer: str,
                  review_method: str = "CLAUDE_VLM_STRUCTURED_REVIEW") -> dict[str, Any]:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    wanted = [it["item_id"] for it in request.get("items") or []]
    got: dict[str, dict[str, Any]] = {}
    for sa in shard_answers:
        for it in sa.get("items") or []:
            if it["item_id"] in got:
                raise ValueError(f"DUPLICATE_ITEM_ACROSS_SHARDS:{it['item_id']}")
            got[it["item_id"]] = it
    missing = [u for u in wanted if u not in got]
    extra = [u for u in got if u not in wanted]
    if missing or extra:
        raise ValueError(f"SHARD_COVERAGE_MISMATCH:missing={missing}:extra={extra}")
    return {"schema": ANSWERS_SCHEMA, "request_id": request.get("request_id"), "kind": request.get("kind"),
            "episode": request.get("episode"), "reviewer": reviewer, "review_method": review_method,
            "reviewed_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "request_path": str(request_path), "request_sha256": sha256_file(request_path),
            "items": [got[u] for u in wanted], "_refusal": None,
            "dispatch": {"shards": len(shard_answers), "items": len(wanted)}}


def _replay_worker(shard_path: Path, out_path: Path, replay: dict[str, Any], latency_ms: int) -> dict[str, Any]:
    shard = json.loads(shard_path.read_text(encoding="utf-8"))
    by_id = {it["item_id"]: it for it in replay.get("items") or []}
    rows = []
    for it in shard["items"]:
        if latency_ms:
            time.sleep(latency_ms / 1000.0)
        if it["item_id"] not in by_id:
            raise ValueError(f"REPLAY_HAS_NO_ANSWER_FOR:{it['item_id']}")
        rows.append(by_id[it["item_id"]])
    payload = {"schema": ANSWERS_SCHEMA, "items": rows, "shard": shard.get("shard")}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


def _cmd_worker(template: str, shard_path: Path, out_path: Path, timeout: int) -> dict[str, Any]:
    argv = [a.format(shard=str(shard_path), out=str(out_path)) for a in shlex.split(template)]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not out_path.is_file():
        raise RuntimeError(f"WORKER_FAILED:{shard_path.name}:rc={r.returncode}:{(r.stderr or r.stdout)[-400:]}")
    return json.loads(out_path.read_text(encoding="utf-8"))


def run(request_path: Path, work_dir: Path, *, workers: int, items_per_shard: int, worker_cmd: str | None,
        replay: Path | None, replay_latency_ms: int, reviewer: str, timeout: int) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    shards = shard_request(request, items_per_shard=items_per_shard)
    paths = []
    for s in shards:
        p = work_dir / f"shard_{s['shard']['index']:03d}.request.json"
        p.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        paths.append(p)
    replay_doc = json.loads(replay.read_text(encoding="utf-8")) if replay else None
    t0 = time.monotonic()
    results: list[dict[str, Any]] = [None] * len(paths)  # type: ignore[list-item]

    def one(i: int) -> dict[str, Any]:
        out = paths[i].with_name(paths[i].name.replace(".request.json", ".answers.json"))
        if replay_doc is not None:
            return _replay_worker(paths[i], out, replay_doc, replay_latency_ms)
        if not worker_cmd:
            raise ValueError("WORKER_CMD_OR_REPLAY_REQUIRED")
        return _cmd_worker(worker_cmd, paths[i], out, timeout)

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for i, res in zip(range(len(paths)), pool.map(one, range(len(paths)))):
            results[i] = res
    wall = time.monotonic() - t0
    merged = merge_answers(request_path, results, reviewer=reviewer)
    merged["dispatch"].update({"workers": workers, "items_per_shard": items_per_shard, "wall_seconds": round(wall, 3),
                               "mode": "REPLAY" if replay_doc is not None else "WORKER_CMD"})
    out = work_dir / "merged_answers.json"
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    merged["merged_answers_path"] = str(out)
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--request", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--items-per-shard", type=int, default=1)
    ap.add_argument("--worker-cmd", help="template with {shard} and {out}, e.g. \"python fill.py --shard {shard} --out {out}\"")
    ap.add_argument("--replay", help="recorded answers.json: offline worker (tests / measurement)")
    ap.add_argument("--replay-latency-ms", type=int, default=0)
    ap.add_argument("--reviewer", default="claude-code-nalu-vlm")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()
    try:
        merged = run(Path(args.request), Path(args.work_dir), workers=args.workers, items_per_shard=args.items_per_shard,
                     worker_cmd=args.worker_cmd, replay=Path(args.replay) if args.replay else None,
                     replay_latency_ms=args.replay_latency_ms, reviewer=args.reviewer, timeout=args.timeout)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "MERGED", **merged["dispatch"], "merged_answers_path": merged["merged_answers_path"],
                      "submit_with": "vlm_review_protocol.py submit --request <request> --answers <merged_answers_path>"},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
