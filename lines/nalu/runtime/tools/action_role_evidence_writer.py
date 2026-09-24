#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""action_role_evidence_writer.py — the exact-output action-role verification receipt.

``tools/shot_media_admission_gate.precheck_submission_inputs`` (called by the engine's
video submitter for every task, before any paid POST) requires, for a VIDEO task whose
``interaction_topology_contract.required`` is true, that the start-frame admission JSON
named by ``start_frame_admission_ref`` carries ``action_role_verification`` in the shape
``_validate_action_role_verification`` checks:

    schema                  == "qingshan.exact_output_action_role_verification.v1"
    status                  == "PASS"
    reviewed_asset_sha256   == the task's start_frame_sha256
    interaction_state       in {PRE_CONTACT, CONTACT_RESULT, BRIDGE_STATE_NO_ACTION_OWNER_VISIBLE}
    initiator_entity_id / target_entity_id   non-empty
    forbidden_role_reversal == True
    prop_ownership          a list

The engine ships no producer of this record (only the consumer), so this line writes it
from a submitted ``action_role`` review: a Claude reviewer looked at the real start
keyframe and answered the closed questionnaire against the authored initiator / target /
props of the unit's first shot.  A receipt is written ONLY when the reviewer's item verdict
is PASS / PASS_WITH_P2 and the media sha still matches; nothing here infers a role from the
expectations.  ``build_nalu_preproduction.py`` embeds the receipt into the per-unit
``<UNIT>_START_FRAME_ADMISSION_V1.json`` it writes for the video transaction manifest.

CLI
---
  write  --episode EP --review <submitted action_role review>
  verify --episode EP
  status --episode EP
"""
from __future__ import annotations

import argparse
import os
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nalu_qa_common import (  # noqa: E402
    ACTION_ROLE_EVIDENCE_RELDIR, ENGINE, REVIEWER_ID, REVIEW_METHOD, Expectations,
    QaPaths, engine_module, now, read_json, sha256_file, write_json,
)

TOOL_ID = "action_role_evidence_writer.v1"
SCHEMA = "qingshan.exact_output_action_role_verification.v1"
STATES = {"PRE_CONTACT", "CONTACT_RESULT", "BRIDGE_STATE_NO_ACTION_OWNER_VISIBLE"}


def evidence_path(episode: str, unit_id: str) -> Path:
    if os.environ.get("NALU_QA_CONTEXT"):
        return mirror_dir(episode) / f"{unit_id}_action_role_verification.json"
    return ENGINE / ACTION_ROLE_EVIDENCE_RELDIR / f"{unit_id}_action_role_verification.json"


def mirror_dir(episode: str) -> Path:
    return QaPaths(episode).preprod_reports / "action_role_evidence"


def _parse_owners(values: list[Any]) -> list[dict[str, str]]:
    rows = []
    for value in values or []:
        text = str(value)
        if ":" in text:
            prop_id, owner = text.split(":", 1)
        elif "=" in text:
            prop_id, owner = text.split("=", 1)
        else:
            prop_id, owner = text, ""
        rows.append({"prop_id": prop_id.strip(), "owner_entity_id": owner.strip()})
    return rows


def materialise(episode: str, submitted: dict[str, Any], submitted_path: Path) -> dict[str, Any]:
    p = QaPaths(episode)
    review_sha = sha256_file(submitted_path)
    rows: list[dict[str, Any]] = []
    for item in submitted.get("items") or []:
        unit_id = item["item_id"]
        request_item = item.get("request_item") or {}
        expectations = request_item.get("expectations") or {}
        media = [row for row in request_item.get("media") or []
                 if row.get("role") == "START_FRAME_KEYFRAME"]
        reference_value = media[0].get("path") if media else None
        reference_path = Path(str(reference_value)) if reference_value else None
        reference_sha = sha256_file(reference_path) if reference_path else None
        answers = item.get("answers") or {}
        observed = item.get("observed") or {}
        blockers: list[str] = []
        if reference_path is None or not reference_path.is_file():
            blockers.append(f"KEYFRAME_MISSING:{reference_value}")
        if media and media[0].get("sha256") and media[0]["sha256"] != reference_sha:
            blockers.append("KEYFRAME_CHANGED_SINCE_REVIEW")
        if item["verdict"] not in {"PASS", "PASS_WITH_P2"}:
            blockers.append(f"VLM_REVIEW_{item['verdict']}")
        state = str(answers.get("interaction_state") or "")
        if state not in STATES:
            blockers.append(f"INTERACTION_STATE_NOT_DECIDED:{state or 'MISSING'}")
        if str(answers.get("no_role_reversal")) != "PASS":
            blockers.append("ROLE_REVERSAL_NOT_EXCLUDED")
        for key in ("initiator_is_expected_entity", "target_is_expected_entity", "prop_ownership_as_expected"):
            if str(answers.get(key)) not in {"PASS", "NOT_APPLICABLE"}:
                blockers.append(f"{key.upper()}_NOT_PASS")
        initiator = str(expectations.get("initiator_entity_id") or "")
        target = str(expectations.get("target_entity_id") or "")
        if not initiator or not target:
            blockers.append("CONTRACT_INITIATOR_OR_TARGET_UNDECLARED")
        status = "PASS" if not blockers else "FAIL"
        payload = {
            "schema": SCHEMA,
            "episode": episode,
            "unit_id": unit_id,
            "shot_id": request_item.get("shot_id"),
            "status": status,
            "reviewed_asset_path": str(reference_value) if reference_value else None,
            "reviewed_asset_sha256": reference_sha,
            "interaction_state": state if state in STATES else None,
            "initiator_entity_id": initiator,
            "initiator_kind": expectations.get("initiator_kind"),
            "target_entity_id": target,
            "target_kind": expectations.get("target_kind"),
            "forbidden_role_reversal": str(answers.get("no_role_reversal")) == "PASS",
            "prop_ownership": _parse_owners(observed.get("observed_prop_owners") or []),
            "observed_initiator": list(observed.get("observed_initiator") or []),
            "observed_target": list(observed.get("observed_target") or []),
            "answers": answers,
            "expectations": expectations,
            "review_method": REVIEW_METHOD,
            "reviewer": REVIEWER_ID,
            "reviewer_type": "AI_VISUAL",
            "review_file": str(submitted_path),
            "review_file_sha256": review_sha,
            "review_request_file": submitted.get("request_path"),
            "review_request_file_sha256": submitted.get("request_sha256"),
            "reviewed_at": submitted.get("reviewed_at"),
            "observation": item.get("observation"),
            "defects": item.get("defects") or [],
            "blockers": blockers,
            "recorded_at": now(),
            "recorded_by": TOOL_ID,
            "consumed_by": "tools/shot_media_admission_gate.precheck_submission_inputs via the "
                           "per-unit START_FRAME_ADMISSION json build_nalu_preproduction.py writes",
        }
        target_path = evidence_path(episode, unit_id)
        write_json(target_path, payload)
        mirror_dir(episode).mkdir(parents=True, exist_ok=True)
        mirror_path = mirror_dir(episode) / target_path.name
        if target_path.resolve() != mirror_path.resolve():
            shutil.copyfile(target_path, mirror_path)
        rows.append({"unit_id": unit_id, "status": status,
                     "evidence_ref": str(target_path),
                     "evidence_path": str(target_path), "evidence_sha256": sha256_file(target_path),
                     "reviewed_asset_sha256": reference_sha, "blockers": blockers})
    passing = [row for row in rows if row["status"] == "PASS"]
    record = {
        "schema": "nalu.action_role_evidence_index.v1", "episode": episode,
        "recorded_at": now(), "recorded_by": TOOL_ID, "reviewer": REVIEWER_ID,
        "review_method": REVIEW_METHOD, "review_file": str(submitted_path),
        "review_file_sha256": review_sha, "evidence_dir": str(evidence_path(episode, "_index").parent),
        "status": ("PASS" if rows and len(passing) == len(rows)
                   else f"PARTIAL_{len(passing)}_OF_{len(rows)}" if rows else "NO_ITEMS"),
        "unit_count": len(rows), "pass_count": len(passing), "units": rows,
    }
    out = mirror_dir(episode) / "_index.json"
    write_json(out, record)
    record["_written_to"] = str(out)
    return record


def verify(episode: str) -> dict[str, Any]:
    """Re-run the ENGINE's own validator on every receipt against the current keyframe."""
    gate = engine_module("shot_media_admission_gate")
    exp = Expectations(episode)
    rows = []
    for unit_id, contract in sorted(exp.start_frame_units.items()):
        path = evidence_path(episode, unit_id)
        keyframe = Path(str(contract.get("reference_path") or ""))
        expected_sha = sha256_file(keyframe) if keyframe.is_file() else None
        payload = read_json(path, {}) or {}
        failures = (gate._validate_action_role_verification(payload, expected_sha=expected_sha or "")
                    if payload else ["Q1_ACTION_ROLE_VERIFICATION_MISSING"])
        rows.append({"unit_id": unit_id, "evidence_path": str(path), "present": bool(payload),
                     "status": "PASS" if not failures else "FAIL", "failures": failures})
    return {"episode": episode, "units": len(rows), "pass": sum(r["status"] == "PASS" for r in rows),
            "missing": [r["unit_id"] for r in rows if not r["present"]],
            "failing": [r["unit_id"] for r in rows if r["present"] and r["status"] != "PASS"],
            "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write"); w.add_argument("--episode", required=True); w.add_argument("--review", required=True, type=Path)
    for name in ("verify", "status"):
        x = sub.add_parser(name); x.add_argument("--episode", required=True)
    args = ap.parse_args()
    if args.cmd == "write":
        submitted = read_json(args.review)
        if not isinstance(submitted, dict) or submitted.get("kind") != "action_role":
            raise SystemExit("not a submitted action_role review")
        if (submitted.get("validation") or {}).get("status") != "PASS":
            raise SystemExit("review validation is not PASS")
        rec = materialise(args.episode, submitted, args.review)
        print(json.dumps({"status": rec["status"], "units": rec["unit_count"], "pass": rec["pass_count"], "out": rec["_written_to"]}, ensure_ascii=False))
        return 0 if rec["status"] == "PASS" else 2
    rep = verify(args.episode)
    print(json.dumps({k: rep[k] for k in ("episode", "units", "pass", "missing", "failing")}, ensure_ascii=False))
    return 0 if not rep["missing"] and not rep["failing"] else 2


if __name__ == "__main__":
    sys.exit(main())
