#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompt_batch_finalize.py — incremental exact-materialisation QA for final video prompts.

At S6 the strict grouped compile (real keyframes, real start-frame evidence) renders the FINAL
provider prompt of every unit.  Its SHA differs from the batch-approved PLANNED prompt (e13
planning compile) whenever the materialised anchors change any text.  tools/episode_prompt_batch_gate.py
then requires, per task, ``prompt_batch_finalization: {path, sha256}`` pointing to a receipt with
``status PASS``, ``execution_id``, ``unit_id``, ``artifact_kind video_prompt``,
``planned_prompt_sha256``, ``final_prompt_sha256`` and ``scope INCREMENTAL_EXACT_MATERIALIZATION_QA``.

``diff``     — for every unit, compare planned vs final text and write a unified diff digest for a
               Claude reviewer (only the changed lines; identical prompts are listed as UNCHANGED).
``receipts`` — from the reviewer's answers, write one receipt per unit whose text changed and
               attach ``prompt_batch_finalization`` to that unit's task in the video transaction
               manifest.  Units whose final SHA equals the planned SHA need no receipt.

The gate verifies evidence; this tool records it.  A unit the reviewer did not PASS gets no
receipt, and the submitter then fails closed on FINAL_PROMPT_NOT_BOUND_TO_BATCH.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)

import argparse
import difflib
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ENGINE = Path(f"{_np.ENGINE_ROOT}")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(ENGINE.resolve()))


def load_ctx(ep: str, execution_id: str):
    pre = ENGINE / "workflow/nalu" / ep / "preproduction"
    batch = json.loads((pre / f"{ep}_PROMPT_BATCH_V1.json").read_text(encoding="utf-8"))
    assert batch["execution_id"] == execution_id, "execution id mismatch"
    tx_path = pre / f"{ep}_VIDEO_TRANSACTION_MANIFEST_V1.json"
    tx = json.loads(tx_path.read_text(encoding="utf-8"))
    planned = {r["unit_id"]: r for r in batch["rows"] if not r.get("parent_unit_id")}
    return pre, batch, tx_path, tx, planned


def diff(ep: str, execution_id: str, out: Path) -> dict:
    pre, batch, tx_path, tx, planned = load_ctx(ep, execution_id)
    rows = []
    for task in tx["tasks"]:
        uid = task["unit_id"]
        final_path = ENGINE / task["prompt_file"]
        if not final_path.is_file():
            rows.append({"unit_id": uid, "status": "FINAL_PROMPT_MISSING"}); continue
        final_sha = sha(final_path)
        pl = planned[uid]
        planned_path = ENGINE / pl["video_prompt"]["path"]
        planned_sha = pl["video_prompt"]["sha256"]
        if final_sha == planned_sha:
            rows.append({"unit_id": uid, "status": "UNCHANGED", "sha256": final_sha}); continue
        a = planned_path.read_text(encoding="utf-8").splitlines()
        b = final_path.read_text(encoding="utf-8").splitlines()
        ud = list(difflib.unified_diff(a, b, fromfile="planned", tofile="final", lineterm="", n=0))
        changed = [l for l in ud if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
        rows.append({"unit_id": uid, "status": "CHANGED", "planned_sha256": planned_sha, "final_sha256": final_sha,
                     "planned_path": rel(planned_path), "final_path": rel(final_path),
                     "changed_line_count": len(changed), "diff": changed[:80]})
    report = {"schema": "nalu.prompt_batch_finalization_digest.v1", "episode": ep, "execution_id": execution_id,
              "generated_at": datetime.now(timezone.utc).isoformat(), "rows": rows,
              "summary": {"unchanged": sum(1 for r in rows if r["status"] == "UNCHANGED"),
                          "changed": sum(1 for r in rows if r["status"] == "CHANGED"),
                          "missing": sum(1 for r in rows if r["status"] == "FINAL_PROMPT_MISSING")}}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return report


def receipts(ep: str, execution_id: str, digest_path: Path, answers_path: Path, out_dir: Path) -> dict:
    pre, batch, tx_path, tx, planned = load_ctx(ep, execution_id)
    dg = json.loads(digest_path.read_text(encoding="utf-8"))
    answers = json.loads(answers_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    by_uid = {r["unit_id"]: r for r in dg["rows"]}
    attached, skipped, failed = [], [], []
    for task in tx["tasks"]:
        uid = task["unit_id"]
        row = by_uid.get(uid) or {}
        if row.get("status") == "UNCHANGED":
            task.pop("prompt_batch_finalization", None); skipped.append(uid); continue
        if row.get("status") != "CHANGED":
            failed.append(f"{uid}:{row.get('status')}"); continue
        # re-verify the final file is still the reviewed bytes
        final_path = ENGINE / task["prompt_file"]
        if not final_path.is_file() or sha(final_path) != row["final_sha256"]:
            failed.append(f"{uid}:FINAL_PROMPT_CHANGED_SINCE_REVIEW"); continue
        a = answers["units"].get(uid)
        if not a or a.get("verdict") != "PASS":
            failed.append(f"{uid}:REVIEWER_NOT_PASS"); continue
        receipt = {"status": "PASS", "execution_id": execution_id, "unit_id": uid, "artifact_kind": "video_prompt",
                   "planned_prompt_sha256": row["planned_sha256"], "final_prompt_sha256": row["final_sha256"],
                   "scope": "INCREMENTAL_EXACT_MATERIALIZATION_QA",
                   "reviewer": answers.get("reviewer"), "review_method": answers.get("review_method"),
                   "reviewed_at": answers.get("reviewed_at"), "changed_line_count": row["changed_line_count"],
                   "reviewer_observation": a.get("observation"), "digest_sha256": sha(digest_path)}
        rpath = out_dir / f"{uid}.json"
        rpath.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        task["prompt_batch_finalization"] = {"path": rel(rpath), "sha256": sha(rpath)}
        task["prompt_sha256"] = row["final_sha256"]
        attached.append(uid)
    tx_path.write_text(json.dumps(tx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"attached": len(attached), "unchanged": len(skipped), "failed": failed}
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diff"); d.add_argument("--episode", required=True); d.add_argument("--execution-id", required=True); d.add_argument("--out", required=True)
    r = sub.add_parser("receipts"); r.add_argument("--episode", required=True); r.add_argument("--execution-id", required=True)
    r.add_argument("--digest", required=True); r.add_argument("--answers", required=True); r.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    if args.cmd == "diff":
        diff(args.episode, args.execution_id, Path(args.out)); return 0
    s = receipts(args.episode, args.execution_id, Path(args.digest), Path(args.answers), Path(args.out_dir))
    return 0 if not s["failed"] else 2


if __name__ == "__main__":
    sys.exit(main())
