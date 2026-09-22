#!/usr/bin/env python3
"""Attach reviewed incremental keyframe-prompt QA receipts to an image manifest.

This is the image-task counterpart of ``prompt_batch_finalize.py``.  It never
submits media.  The caller must supply a reviewer and review note after reading
the complete changed-prompt digest; this tool only binds exact SHAs and writes
the evidence shape enforced by ``episode_prompt_batch_gate``.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--review-note", required=True)
    parser.add_argument("--receipt-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    root = args.engine_root.resolve()
    policy_path = root / "workflow/production_line/EPISODE_PROMPT_BATCH_POLICY.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    config = (policy.get("executions") or {}).get(args.execution_id)
    if not config or config.get("required") is not True:
        raise SystemExit("prompt batch execution is not registered and required")
    batch_path = root / config["manifest_ref"]
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    rows = {str(row["unit_id"]): row for row in batch.get("rows") or []}
    aliases = {str(k): str(v) for k, v in (config.get("unit_aliases") or {}).items()}
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    evidence_rows: list[dict[str, Any]] = []
    for task in manifest.get("tasks") or []:
        task_key = str(task["task_key"])
        shot_id = str(task.get("shot_id") or "")
        unit_id = aliases.get(shot_id, shot_id)
        planned_row = rows.get(unit_id)
        if not planned_row:
            raise SystemExit(f"{task_key}: no registered prompt-batch row for {unit_id}")
        planned = planned_row["keyframe_prompt"]
        planned_path = root / planned["path"]
        final_path = Path(str(task["prompt_file"])).resolve()
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
        receipt_path = args.receipt_dir / f"{task_key}.json"
        atomic_json(receipt_path, receipt)
        resolved_receipt = receipt_path.resolve()
        runtime_root = Path(os.environ.get("NALU_RUNTIME_ROOT", "")).resolve() if os.environ.get("NALU_RUNTIME_ROOT") else None
        if resolved_receipt.is_relative_to(root):
            stored_path = str(resolved_receipt.relative_to(root))
        elif runtime_root and resolved_receipt.is_relative_to(runtime_root):
            stored_path = str(resolved_receipt)
        else:
            raise SystemExit("receipt directory must be inside engine root or NALU_RUNTIME_ROOT")
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
