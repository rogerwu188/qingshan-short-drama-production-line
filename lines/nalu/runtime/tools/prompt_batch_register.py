#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompt_batch_register.py — register the whole-batch prompt execution for one episode.

tools/episode_prompt_batch_gate.py (engine, 2026-09-08) refuses every paid image/video POST
until the episode's complete prompt batch is registered in
``workflow/production_line/EPISODE_PROMPT_BATCH_POLICY.json`` and every unit row carries
``keyframe_prompt``, ``video_prompt`` and ``prompt_qa`` references whose files exist, whose
SHA-256 match, and whose QA receipt is PASS with cross-unit continuity checked.

This tool only assembles the batch manifest and the policy entry from files that already exist:

* keyframe_prompt  — the keyframe prompt of the unit's first editorial shot, exactly the file
                     the keyframe image manifest binds (``prompt_file`` / ``prompt_sha256``);
* video_prompt     — the planned provider prompt compiled with engine patch e13
                     (``--planning-only``), ``planned_video_prompts/<unit>.txt``;
* prompt_qa        — the receipt written by ``prompt_batch_qa.py`` after a Claude reviewer
                     actually read both prompts and the cross-unit context.  A missing receipt is
                     left missing; the gate then HOLDs, which is the correct answer.

Nothing here performs or fabricates creative QA.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ENGINE = Path(f"{_np.ENGINE_ROOT}")
WORK = Path(os.environ.get("NALU_WORK_ROOT", str(_np.RUNTIME_ROOT / "workflow" / "nalu"))).expanduser().resolve()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ENGINE.resolve()))
    except ValueError:
        return str(resolved)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode", required=True)
    ap.add_argument("--execution-id", required=True)
    ap.add_argument("--qa-dir", required=True, help="directory of <unit_id>.json prompt QA receipts (may be incomplete)")
    ap.add_argument("--report", required=True)
    args = ap.parse_args()
    ep = args.episode
    pre = WORK / ep / "preproduction"
    grouping = json.loads((pre / f"{ep}_VIDEO_UNIT_GROUPING_PLAN_V1.json").read_text(encoding="utf-8"))
    keyframe_candidates = [
        pre / f"{ep}_KEYFRAME_IMAGE_MANIFEST_V1.json",
        pre / f"{ep}_KEYFRAME_IMAGE_MANIFEST_V2_DEDICATED_GPT_V2.json",
        pre / f"{ep}_KEYFRAME_IMAGE_MANIFEST_V2_DEDICATED_GPT.json",
    ]
    keyframe_manifest_path = next((p for p in keyframe_candidates if p.is_file()), None)
    if keyframe_manifest_path is None:
        raise FileNotFoundError(f"no keyframe manifest found under {pre}")
    keyframes = json.loads(keyframe_manifest_path.read_text(encoding="utf-8"))
    planned_index = json.loads((pre / f"{ep}_GROUPED_SEEDANCE_MANIFEST_PLANNING_V1.planned_prompts.json").read_text(encoding="utf-8"))
    planned = {row["unit_id"]: row for row in planned_index["rows"]}
    kf_by_shot = {t["shot_id"]: t for t in keyframes["tasks"]}
    anchor_path = pre / f"{ep}_VIDEO_UNIT_ANCHOR_PLAN_V1.json"
    anchors = {u["unit_id"]: u for u in (json.loads(anchor_path.read_text(encoding="utf-8")).get("units") or [])} if anchor_path.is_file() else {}
    qa_dir = Path(args.qa_dir)

    rows, aliases, missing_qa, problems = [], {}, [], []
    for unit in grouping["units"]:
        uid = unit["unit_id"]
        shots = unit["editorial_shot_ids"]
        for shot_id in shots:
            if shot_id == shots[0] or shot_id not in kf_by_shot:
                aliases[shot_id] = uid
        first = kf_by_shot.get(shots[0])
        derivation = None
        if not first:
            # E02+ anchor policy v4: a unit whose opening anchor is CONTINUITY_DERIVED (materialised
            # from the previous unit's real tail at S6) has no keyframe task of its own.  The nearest
            # authored still is the previous unit's keyframe prompt; the row records the derivation and
            # the digest skips the keyframe-specific checks for it.
            anchor = anchors.get(uid) or {}
            oac = anchor.get("opening_anchor_contract") or {}
            prev = oac.get("previous_unit_id")
            hops = 0
            while prev and not first and hops < 6:
                prev_unit = next((u for u in grouping["units"] if u["unit_id"] == prev), None)
                if not prev_unit:
                    break
                first = kf_by_shot.get(prev_unit["editorial_shot_ids"][0])
                if not first:
                    prev = ((anchors.get(prev) or {}).get("opening_anchor_contract") or {}).get("previous_unit_id")
                hops += 1
            if not first:
                problems.append(f"{uid}: no keyframe task for first shot {shots[0]} and no continuity source")
                continue
            derivation = {"kind": "CONTINUITY_DERIVED_FROM_PREVIOUS_UNIT_TAIL", "source": oac.get("source"),
                          "previous_unit_id": oac.get("previous_unit_id"), "materialized_path": oac.get("materialized_path"),
                          "keyframe_prompt_of_unit": prev}
        kf_path = Path(first["prompt_file"])
        if not kf_path.is_file() or sha(kf_path) != first["prompt_sha256"]:
            problems.append(f"{uid}: keyframe prompt missing or sha mismatch vs keyframe manifest")
            continue
        vp = planned.get(uid)
        if not vp:
            problems.append(f"{uid}: no planned video prompt")
            continue
        vp_path = Path(vp["path"])
        if not vp_path.is_file() or sha(vp_path) != vp["sha256"]:
            problems.append(f"{uid}: planned video prompt missing or sha mismatch vs planned index")
            continue
        row = {"unit_id": uid,
               "editorial_shot_ids": shots,
               "keyframe_prompt": {"path": rel(kf_path), "sha256": first["prompt_sha256"], "shot_id": first["shot_id"],
                                   **({"derivation": derivation} if derivation else {})},
               "video_prompt": {"path": rel(vp_path), "sha256": vp["sha256"],
                                "scope": "PLANNED_PROMPT_COMPILATION_NOT_MEDIA_ADMISSION"}}
        qa_path = qa_dir / f"{uid}.json"
        if qa_path.is_file():
            row["prompt_qa"] = {"path": rel(qa_path), "sha256": sha(qa_path)}
        else:
            missing_qa.append(uid)
        rows.append(row)
        # A unit whose anchor plan needs a second keyframe (IDENTITY_OR_PROP_REANCHOR) has a second
        # keyframe task whose uid is its own shot_id.  Give it its own scoped row (same planned
        # video prompt, its own keyframe prompt, its own QA receipt) instead of an alias, so the
        # gate binds each paid keyframe prompt to a reviewed text.
        for shot_id in shots[1:]:
            extra = kf_by_shot.get(shot_id)
            if not extra:
                continue
            ep_path = Path(extra["prompt_file"])
            if not ep_path.is_file() or sha(ep_path) != extra["prompt_sha256"]:
                problems.append(f"{uid}/{shot_id}: second keyframe prompt missing or sha mismatch")
                continue
            row2 = {"unit_id": shot_id, "parent_unit_id": uid, "row_kind": "SECOND_KEYFRAME_OF_UNIT",
                    "editorial_shot_ids": shots,
                    "keyframe_prompt": {"path": rel(ep_path), "sha256": extra["prompt_sha256"], "shot_id": shot_id},
                    "video_prompt": dict(row["video_prompt"])}
            qa2 = qa_dir / f"{shot_id}.json"
            if qa2.is_file():
                row2["prompt_qa"] = {"path": rel(qa2), "sha256": sha(qa2)}
            else:
                missing_qa.append(shot_id)
            rows.append(row2)

    manifest_path = pre / f"{ep}_PROMPT_BATCH_V1.json"
    manifest = {"schema": "nalu.prompt_batch_manifest.v1", "execution_id": args.execution_id, "episode": ep,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": "prompt_batch_register.v1",
                "grouping_plan_sha256": sha(pre / f"{ep}_VIDEO_UNIT_GROUPING_PLAN_V1.json"),
                "keyframe_manifest_sha256": sha(keyframe_manifest_path),
                "planned_prompts_index_sha256": sha(pre / f"{ep}_GROUPED_SEEDANCE_MANIFEST_PLANNING_V1.planned_prompts.json"),
                "rows": rows}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    policy_src = ENGINE / "configs/EPISODE_PROMPT_BATCH_POLICY.json"
    policy_dst = ENGINE / "workflow/production_line/EPISODE_PROMPT_BATCH_POLICY.json"
    policy = json.loads(policy_dst.read_text(encoding="utf-8")) if policy_dst.is_file() else json.loads(policy_src.read_text(encoding="utf-8"))
    policy.setdefault("task_key_execution_prefixes", {})[f"{ep}-"] = args.execution_id
    policy.setdefault("executions", {})[args.execution_id] = {
        "required": True,
        "episode": ep,
        "unit_ids": [r["unit_id"] for r in rows],
        "unit_aliases": aliases,
        "manifest_ref": rel(manifest_path),
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "registered_by": "prompt_batch_register.v1 (nalu line)",
        "authorization": (
            "ENGINE_PROMPT_BATCH_POLICY: free preproduction registration only; "
            "does not authorize a provider POST or paid production"
        ),
        "provider_post_authorized": False,
    }
    policy_dst.parent.mkdir(parents=True, exist_ok=True)
    policy_dst.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {"schema": "nalu.prompt_batch_register_report.v1", "episode": ep, "execution_id": args.execution_id,
              "manifest": str(manifest_path), "policy": str(policy_dst), "rows": len(rows),
              "units_expected": len(grouping["units"]), "aliases": len(aliases),
              "missing_qa": missing_qa, "problems": problems,
              "status": "PASS" if not problems and not missing_qa and len(rows) >= len(grouping["units"]) else "HOLD"}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "rows", "units_expected", "missing_qa", "problems")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
