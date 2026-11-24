#!/usr/bin/env python3
"""Stamp reviewed_request_sha256 on keyframe tasks whose prompt the whole-batch prompt gate reviewed.

PROVIDER_REQUEST_REVIEW_BINDING_V1 (enforced from E14) refuses a paid task that carries no
reviewed_request_sha256.  The stamp is only honest when a review exists for the very prompt bytes, so a
task is stamped only if (a) the prompt-batch register report is PASS for this episode's execution id and
(b) the registered batch row for that shot names the same keyframe prompt sha256 as the task, and the
file on disk still hashes to it.  Every other task is left unstamped and the submitter refuses it.
The digest is computed exactly as submit_giggle_image_manifest does (same resolver, same fields).

A task whose prompt legitimately differs from the batch row (an S6 own keyframe written after the batch
was registered — device 1101 E27 2026-11-24) is reviewed through
``tools/attach_keyframe_prompt_batch_finalization.py``, which writes one receipt per task into
``<preproduction>/keyframe_prompt_batch_finalization/<task_key>.json``.  build_keyframe_manifest
rebuilds the manifest on every S5 entry, so the receipt is re-attached here (exact final sha, PASS,
keyframe_prompt, same execution, planned sha = the batch row of its unit) and the task is stamped; the
D-11 materialized copy is made from this manifest afterwards and keeps both fields.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ENGINE))
from tools import provider_request_digest as prd  # noqa: E402
from tools.submit_giggle_image_manifest import submission_fingerprint  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ENGINE / path


RECEIPT_DIR_NAME = "keyframe_prompt_batch_finalization"


def portable(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ENGINE.resolve()))
    except ValueError:
        return str(resolved)  # a runtime outside the engine checkout: absolute (gate trusts the runtime root)


def finalization_receipt(receipt_dir: Path, task: dict, batch: dict) -> Path | None:
    """The reviewed incremental keyframe receipt binding exactly this task's final prompt, else None."""
    path = receipt_dir / f"{task.get('task_key')}.json"
    if not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = {str(r.get("unit_id")): r for r in batch.get("rows") or []}
    planned = (rows.get(str(receipt.get("unit_id"))) or {}).get("keyframe_prompt") or {}
    ok = (receipt.get("status") == "PASS"
          and receipt.get("artifact_kind") == "keyframe_prompt"
          and receipt.get("scope") == "INCREMENTAL_EXACT_MATERIALIZATION_QA"
          and receipt.get("execution_id") == batch.get("execution_id")
          and receipt.get("task_key") == task.get("task_key")
          and receipt.get("final_prompt_sha256") == task.get("prompt_sha256")
          and planned.get("sha256") and receipt.get("planned_prompt_sha256") == planned.get("sha256"))
    return path if ok else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--batch-manifest", type=Path, required=True)
    ap.add_argument("--register-report", type=Path, required=True)
    ap.add_argument("--receipt-dir", type=Path,
                    help=f"reviewed keyframe finalization receipts (default <manifest dir>/{RECEIPT_DIR_NAME})")
    args = ap.parse_args(argv)

    report = json.loads(args.register_report.read_text(encoding="utf-8"))
    batch = json.loads(args.batch_manifest.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    receipt_dir = args.receipt_dir or (args.manifest.parent / RECEIPT_DIR_NAME)
    out = {"episode": args.episode, "stamped": [], "left_unstamped": [], "supersedes_declared": {},
           "finalization_attached": []}
    transaction_dir = ENGINE / "workflow/tasks/giggle_submit_transactions" / args.episode
    if report.get("status") != "PASS" or report.get("execution_id") != batch.get("execution_id"):
        out["status"] = "BATCH_NOT_REGISTERED_PASS"
        print(json.dumps(out, ensure_ascii=False))
        return 2
    reviewed = {}
    for row in batch.get("rows") or []:
        kp = row.get("keyframe_prompt") or {}
        if kp.get("shot_id"):
            reviewed[kp["shot_id"]] = kp.get("sha256")
    for task in manifest.get("tasks") or []:
        key, shot = task.get("task_key"), task.get("shot_id")
        if not prd.binding_required(task):
            out["left_unstamped"].append({"task_key": key, "reason": "BINDING_NOT_REQUIRED"})
            continue
        prompt_path = resolve(task["prompt_file"])
        task_sha = task.get("prompt_sha256")
        on_disk = prompt_path.is_file() and sha(prompt_path) == task_sha
        if not (on_disk and reviewed.get(shot) and reviewed[shot] == task_sha):
            receipt = finalization_receipt(receipt_dir, task, batch) if on_disk else None
            if receipt is None:
                task.pop("prompt_batch_finalization", None)
                out["left_unstamped"].append({"task_key": key, "shot_id": shot,
                                              "reason": "PROMPT_NOT_THE_REVIEWED_ONE"})
                continue
            task["prompt_batch_finalization"] = {"path": portable(receipt), "sha256": sha(receipt)}
            out["finalization_attached"].append(key)
        refs = [resolve(p) for p in task.get("reference_images") or []]
        task["reviewed_request_sha256"] = prd.task_request_digest(
            task, prompt_text=prompt_path.read_text(encoding="utf-8"), reference_paths=refs)["request_sha256"]
        out["stamped"].append(key)
        # A reviewed prompt that differs from an earlier bound submission is a deliberate re-POST: declare
        # the earlier fingerprints so the duplicate-submission guard lets exactly this task through.  A
        # task without a registered review never reaches here, so an unreviewed change is still refused.
        others = prd.bound_under_other_fingerprint(transaction_dir, key, submission_fingerprint(task))
        if others:
            task["supersedes_submission_fingerprints"] = others
            out["supersedes_declared"][key] = others
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out["status"] = "PASS" if not out["left_unstamped"] else "PARTIAL"
    print(json.dumps({**out, "stamped": len(out["stamped"]),
                      "supersedes_declared": sorted(out["supersedes_declared"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
