#!/usr/bin/env python3
"""Attach reviewed incremental keyframe-prompt QA receipts to an image manifest.

This is the image-task counterpart of ``prompt_batch_finalize.py``.  It never
submits media.  The caller must supply a reviewer and review note after reading
the complete changed-prompt digest; this tool only binds exact SHAs and writes
the evidence shape enforced by ``episode_prompt_batch_gate``.

The policy is resolved exactly as the gate resolves it (runtime copy first, see
``episode_prompt_batch_gate.policy_candidates``): device 1101 E27 S6 (2026-11-24) registered its
execution only in the runtime policy and this tool, reading the engine copy, refused it.

Only tasks whose final prompt differs from the batch-approved planned prompt need a receipt; the
others are skipped.  ``--diff-out`` writes the changed-line digest the reviewer reads, without
receipts.  Receipts land in ``--receipt-dir``; S5's ``stamp_reviewed_keyframe_requests.py``
re-attaches them on every keyframe-manifest rebuild, so they survive the rebuild and the D-11
materialized copy.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE = Path(__file__).resolve().parents[1]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
from tools.episode_prompt_batch_gate import resolve_policy_path, runtime_root  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--reviewer")
    parser.add_argument("--review-note")
    parser.add_argument("--receipt-dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--task-key", action="append", default=[],
                        help="only these tasks (repeatable); default every task whose prompt changed")
    parser.add_argument("--diff-out", type=Path,
                        help="write the planned-vs-final changed-line digest and exit (no receipts)")
    args = parser.parse_args(argv)
    if args.diff_out is None and not (args.reviewer and args.review_note and args.receipt_dir and args.report):
        parser.error("--reviewer, --review-note, --receipt-dir and --report are required unless --diff-out")

    root = args.engine_root.resolve()
    policy_path = resolve_policy_path(root)
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.is_file() else {}
    config = (policy.get("executions") or {}).get(args.execution_id)
    if not config or config.get("required") is not True:
        raise SystemExit(f"prompt batch execution is not registered and required (policy {policy_path})")
    batch_path = root / config["manifest_ref"]
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    rows = {str(row["unit_id"]): row for row in batch.get("rows") or []}
    aliases = {str(k): str(v) for k, v in (config.get("unit_aliases") or {}).items()}
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    runtime = runtime_root(root)
    runtime = runtime.resolve() if runtime else None
    if args.receipt_dir is not None:
        receipt_dir = args.receipt_dir.resolve()
        if not (receipt_dir.is_relative_to(root) or (runtime and receipt_dir.is_relative_to(runtime))):
            raise SystemExit("receipt directory must be inside engine root or NALU_RUNTIME_ROOT")
    wanted = set(args.task_key)

    evidence_rows: list[dict[str, Any]] = []
    digest_rows: list[dict[str, Any]] = []
    for task in manifest.get("tasks") or []:
        task_key = str(task["task_key"])
        if wanted and task_key not in wanted:
            continue
        shot_id = str(task.get("shot_id") or "")
        unit_id = aliases.get(shot_id, shot_id)
        planned_row = rows.get(unit_id)
        if not planned_row:
            if wanted:
                raise SystemExit(f"{task_key}: no registered prompt-batch row for {unit_id}")
            continue
        planned = planned_row["keyframe_prompt"]
        if task.get("prompt_sha256") == planned["sha256"]:
            continue  # the batch-approved prompt itself: the gate needs no receipt
        planned_path = root / planned["path"]
        final_path = Path(str(task["prompt_file"]))
        final_path = (final_path if final_path.is_absolute() else root / final_path).resolve()
        if not planned_path.is_file() or sha(planned_path) != planned["sha256"]:
            raise SystemExit(f"{task_key}: registered planned prompt is missing or stale")
        if not final_path.is_file() or sha(final_path) != task["prompt_sha256"]:
            raise SystemExit(f"{task_key}: final prompt is missing or stale")
        changed = [
            line for line in difflib.unified_diff(
                planned_path.read_text(encoding="utf-8").splitlines(),
                final_path.read_text(encoding="utf-8").splitlines(),
                fromfile="planned", tofile="final", n=0, lineterm="",
            )
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        if args.diff_out is not None:
            digest_rows.append({"task_key": task_key, "shot_id": shot_id, "unit_id": unit_id,
                                "planned_prompt": str(planned_path), "final_prompt": str(final_path),
                                "planned_prompt_sha256": planned["sha256"],
                                "final_prompt_sha256": task["prompt_sha256"], "changed_lines": changed})
            continue
        receipt = {
            "schema": "nalu.keyframe_prompt_batch_finalization_receipt.v1",
            "status": "PASS",
            "execution_id": args.execution_id,
            "unit_id": unit_id,
            "shot_id": shot_id,
            "task_key": task_key,
            "artifact_kind": "keyframe_prompt",
            "planned_prompt_sha256": planned["sha256"],
            "final_prompt_sha256": task["prompt_sha256"],
            "scope": "INCREMENTAL_EXACT_MATERIALIZATION_QA",
            "reviewer": args.reviewer,
            "review_method": "FULL_BATCH_DIFF_PLUS_PER_TASK_MACHINE_PRECHECK",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "changed_line_count": len(changed),
            "reviewer_observation": args.review_note,
        }
        receipt_path = receipt_dir / f"{task_key}.json"
        atomic_json(receipt_path, receipt)
        stored_path = (str(receipt_path.relative_to(root)) if receipt_path.is_relative_to(root)
                       else str(receipt_path))
        task["prompt_batch_finalization"] = {"path": stored_path, "sha256": sha(receipt_path)}
        evidence_rows.append({
            "task_key": task_key,
            "shot_id": shot_id,
            "unit_id": unit_id,
            "planned_prompt_sha256": planned["sha256"],
            "final_prompt_sha256": task["prompt_sha256"],
            "changed_line_count": len(changed),
            "receipt": stored_path,
            "receipt_sha256": sha(receipt_path),
        })

    if args.diff_out is not None:
        atomic_json(args.diff_out, {
            "schema": "nalu.keyframe_prompt_batch_finalization_digest.v1",
            "execution_id": args.execution_id, "episode": manifest.get("episode"),
            "manifest": str(args.manifest.resolve()), "policy": str(policy_path),
            "task_count": len(digest_rows), "rows": digest_rows})
        print(json.dumps({"status": "DIGEST", "tasks": len(digest_rows), "digest": str(args.diff_out)}))
        return 0
    atomic_json(args.manifest, manifest)
    report = {
        "schema": "nalu.keyframe_prompt_batch_finalization_report.v1",
        "status": "PASS",
        "execution_id": args.execution_id,
        "episode": manifest.get("episode"),
        "manifest": str(args.manifest.resolve()),
        "manifest_sha256": sha(args.manifest),
        "reviewer": args.reviewer,
        "review_note": args.review_note,
        "task_count": len(evidence_rows),
        "rows": evidence_rows,
    }
    atomic_json(args.report, report)
    print(json.dumps({"status": "PASS", "tasks": len(evidence_rows), "manifest_sha256": report["manifest_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
