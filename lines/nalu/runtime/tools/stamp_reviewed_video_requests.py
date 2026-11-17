#!/usr/bin/env python3
"""Stamp reviewed_request_sha256 on VIDEO tasks whose prompt a review actually covered.

PROVIDER_REQUEST_REVIEW_BINDING_V1 is enforced from E14 on every task, but only the keyframe
stage had a stamper (`stamp_reviewed_keyframe_requests.py`).  S6 recompiles the video manifest
from scratch on every entry (stage_s2 with --keyframes), so a stamp written outside the stage
is gone by the time the paid submit reads the manifest — E14's first S6 wave was refused twelve
times with REVIEWED_REQUEST_NOT_BOUND for exactly that reason, before any charge.

The stamp is only honest when a review exists for the very bytes about to be sent, so a task is
stamped only when BOTH of these hold and the file on disk still hashes to it:

  * its FINAL prompt equals the batch-approved PLANNED prompt (nothing changed after the
    whole-batch prompt gate reviewed it), or
  * the task carries a signed `prompt_batch_finalization` receipt for that exact final prompt
    (an incremental INCREMENTAL_EXACT_MATERIALIZATION_QA review of the diff).

Every other task is left unstamped and the submitter refuses it.  The digest is computed with
the same resolver and fields `submit_giggle_video_manifest_v2` uses.
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
from tools.submit_giggle_video_manifest_v2 import task_fingerprint  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ENGINE / path



def _every_bound_take_is_another_request(transaction_dir: Path, task_key: str, prompt_sha256: str,
                                         reference_sha256: list[str] | None = None,
                                         own_fingerprint: str | None = None) -> bool:
    """True only when every provider-bound transaction of this task was a different request: it records a
    prompt_sha256 that is not this prompt, or it records this prompt with a different reference set (a new
    start frame: the engine's Q2 face-count / speaker-framing redo regenerates the unit's own keyframe and
    keeps the reviewed prompt).  A take without a recorded prompt sha is unknown and keeps the refusal (the
    duplicate guard stays fail-closed), and so does a same-prompt take whose references are unrecorded or
    equal to the current ones: that is an identical-request reroll (K130).

    The task's own transaction (``own_fingerprint``) is not one of the "other" takes and is skipped: it is
    this very request, and the submitter's ``prior_bound`` already decides it (poll the live take, or release
    a zero-cost terminal failure for one new attempt).  Field device ...0926 E14 VU-001/020 (2026-11-17): the
    redo's own take failed at the provider at zero cost, its still-bound row then read as a same-prompt
    reroll here, the supersede of the ORIGINAL take was no longer declared on recompile, and the authorised
    zero-cost retry was refused BOUND_UNDER_OTHER_FINGERPRINT before any POST."""
    current_refs = [str(v) for v in (reference_sha256 or [])]
    seen = False
    for path in sorted(Path(transaction_dir).glob(f"{task_key}__*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (row.get("state") == "SUBMITTED_TASK_ID_BOUND" or row.get("task_id")):
            continue
        if own_fingerprint and str(row.get("submission_fingerprint") or "") == own_fingerprint:
            continue
        seen = True
        bound = str(row.get("prompt_sha256") or "")
        if not bound:
            return False
        if bound == prompt_sha256:
            bound_refs = [str(v) for v in (row.get("reference_sha256") or [])]
            if not bound_refs or not current_refs or bound_refs == current_refs:
                return False
    return seen

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--finalization-digest", type=Path, required=True,
                    help="<EP>_PROMPT_FINALIZATION_DIGEST.json from prompt_batch_finalize.py diff")
    args = ap.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    digest = json.loads(args.finalization_digest.read_text(encoding="utf-8"))
    rows = {str(row.get("unit_id")): row for row in digest.get("rows") or []}

    out = {"episode": args.episode, "status": None, "stamped": [], "left_unstamped": [], "supersedes_declared": {}}
    transaction_dir = ENGINE / "workflow/tasks/giggle_video_submit_transactions" / args.episode
    for task in manifest.get("tasks") or []:
        key = str(task.get("task_key") or task.get("unit_id") or "")
        if not prd.binding_required(task):
            out["left_unstamped"].append({"task_key": key, "reason": "BINDING_NOT_REQUIRED"})
            continue
        prompt_path = resolve(task["prompt_file"])
        task_sha = str(task.get("prompt_sha256") or "")
        if not (prompt_path.is_file() and sha(prompt_path) == task_sha):
            out["left_unstamped"].append({"task_key": key, "reason": "PROMPT_CHANGED_ON_DISK"})
            continue
        row = rows.get(str(task.get("unit_id") or key)) or {}
        unchanged_since_review = (row.get("status") == "UNCHANGED"
                                  and row.get("sha256") == task_sha)
        # A CHANGED unit is reviewable only through its signed incremental receipt, which S6
        # attaches to the task itself; the digest alone does not prove a human read the diff.
        signed_change = (row.get("status") == "CHANGED"
                         and row.get("final_sha256") == task_sha
                         and isinstance(task.get("prompt_batch_finalization"), dict))
        if not (unchanged_since_review or signed_change):
            out["left_unstamped"].append({
                "task_key": key,
                "reason": "PROMPT_NOT_THE_REVIEWED_ONE",
                "finalization_status": row.get("status"),
            })
            continue
        refs = [resolve(p) for p in task.get("reference_images") or []]
        audio = prd.sent_audio_references(task)
        task["reviewed_request_sha256"] = prd.task_request_digest(
            task, prompt_text=prompt_path.read_text(encoding="utf-8"), reference_paths=refs,
            duration=int(task["duration_seconds"]) if task.get("duration_seconds") is not None else None,
            audio=audio)["request_sha256"]
        out["stamped"].append(key)
        # Same rule as stamp_reviewed_keyframe_requests: a signed incremental review of a CHANGED
        # prompt for a unit already bound to a provider take is a deliberate redo, so the earlier
        # fingerprints are declared and the duplicate-submission guard lets exactly this task
        # through.  Without it the E14 fight redesign (wave 33) was refused BOUND_UNDER_OTHER_FINGERPRINT
        # on every unit.  An unchanged or unreviewed task never declares a supersede.
        if signed_change:
            others = prd.bound_under_other_fingerprint(transaction_dir, key, task_fingerprint(task))
            if others:
                task["supersedes_submission_fingerprints"] = others
                out["supersedes_declared"][key] = others
        elif unchanged_since_review:
            # Stamper gap (E15 fight redesign, 2026-11-07): a unit whose REVIEWED batch prompt changed
            # after its take was bound renders UNCHANGED at finalization (final == planned), so it had
            # no signed receipt and never declared a supersede -> BOUND_UNDER_OTHER_FINGERPRINT on
            # VU-014/015/017/018.  The redo is deliberate exactly when the current prompt differs from
            # EVERY bound take's prompt_sha256; a take bound to this same prompt keeps the refusal
            # (no identical-prompt reroll, K130).
            own = task_fingerprint(task)
            others = prd.bound_under_other_fingerprint(transaction_dir, key, own)
            # Q2 auto-redo gap (field device ...1324 E16 VU-016, 2026-11-15): a face-count redo keeps the
            # reviewed prompt and shoots from a regenerated own keyframe, so the prompt sha equals the bound
            # take's and the single-unit redo wave was refused before any POST.  A different recorded
            # reference set is a changed request, not a reroll.
            if others and _every_bound_take_is_another_request(
                    transaction_dir, key, task_sha, task.get("reference_sha256"), own_fingerprint=own):
                task["supersedes_submission_fingerprints"] = others
                out["supersedes_declared"][key] = others

    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out["status"] = "PASS" if not out["left_unstamped"] else "PARTIAL"
    print(json.dumps({**out, "stamped": len(out["stamped"]),
                      "supersedes_declared": sorted(out["supersedes_declared"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
