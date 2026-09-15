#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""start_frame_evidence_writer.py — D-5: the start-frame observation receipt.

``grouped_anchor_semantic_contract.validate_start_anchor_semantics``, reached
from ``compile_grouped_seedance_manifest.py:849-859``, re-reads a
``qingshan.start_frame_semantic_evidence.v1`` file named by the contract's
``evidence_ref`` and cross-checks it against the contract byte for byte:

    payload.status                        == "PASS"
    payload.reference_path                == the admitted first reference's path
    payload.reference_sha256              == that reference's sha256
    sorted(set(observed_visible_characters)) == the contract's own
    sorted(set(observed_visible_props))      == the contract's own
    list(dict.fromkeys(observed_space_anchors)) == the contract's own
    camera_start_framing_match / space_match / empty_establishing_frame
                                          are compared with ``is`` (identity)

and the contract's observed lists must in turn be supersets of the SCRIPT's
expectations (``_visible_characters`` / ``_visible_props`` of the first shot's
prompt_spec, plus the mapped start-space anchors).

The only existing writers are zero-argument builders hardcoded to E43/E44 whose
``review_method`` is an explicit human contact-sheet review.  This one is
parameterised by episode and its ``review_method`` is
``CLAUDE_VLM_STRUCTURED_REVIEW``: the observed lists and the three booleans come
from a submitted ``start_frame`` review in which a Claude reviewer compared the
real keyframe against the unit's ``entry_state``.  Nothing here is inferred from
the expectations — a receipt is only written when the reviewer reported it.

Path convention.  ``build_nalu_preproduction.py:1006-1007`` authors
``expected_evidence_ref = "reports/start_frame_evidence/<UNIT>_start_frame_evidence.json"``
and ``grouped_anchor_semantic_contract._resolve`` resolves a relative
``evidence_ref`` against the ENGINE root.  This tool writes exactly there (and
mirrors a copy next to the episode's other reports for the pipeline receipts).

CLI
---
  write  --episode EP --review <submitted start_frame review>
  verify --episode EP
  status --episode EP
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nalu_qa_common import (  # noqa: E402
    ENGINE, REVIEWER_ID, REVIEW_METHOD, START_FRAME_EVIDENCE_RELDIR, Expectations,
    QaPaths, engine_module, now, read_json, sha256_file, write_json,
)

TOOL_ID = "start_frame_evidence_writer.v1"
EVIDENCE_SCHEMA = "qingshan.start_frame_semantic_evidence.v1"


def evidence_path(episode: str, unit_id: str) -> Path:
    return ENGINE / START_FRAME_EVIDENCE_RELDIR / f"{unit_id}_start_frame_evidence.json"


def _bool(value: Any) -> bool | None:
    text = str(value).upper()
    if text in {"YES", "PASS", "TRUE"}:
        return True
    if text in {"NO", "FAIL", "FALSE"}:
        return False
    return None


def materialise(episode: str, submitted: dict[str, Any],
                submitted_path: Path) -> dict[str, Any]:
    p = QaPaths(episode)
    exp = Expectations(episode)
    review_sha = sha256_file(submitted_path)
    contracts = read_json(p.start_frames, {}) or {}
    by_unit = {str(row.get("unit_id")): row for row in contracts.get("units") or []}

    rows: list[dict[str, Any]] = []
    for item in submitted.get("items") or []:
        unit_id = item["item_id"]
        contract = by_unit.get(unit_id) or {}
        request_item = item.get("request_item") or {}
        expectations = request_item.get("expectations") or {}
        media = [row for row in request_item.get("media") or []
                 if row.get("role") == "START_FRAME_KEYFRAME"]
        reference_value = contract.get("reference_path") or (
            media[0].get("path") if media else None)
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

        observed_characters = sorted(set(str(value) for value in
                                         observed.get("observed_visible_characters") or []))
        observed_props = sorted(set(str(value) for value in
                                    observed.get("observed_visible_props") or []))
        observed_space: list[str] = list(dict.fromkeys(
            str(value) for value in observed.get("observed_space_anchors") or []))

        camera_match = _bool(answers.get("camera_start_framing_match"))
        space_match = _bool(answers.get("space_match"))
        empty_frame = _bool(answers.get("empty_establishing_frame"))
        for name, value in (("camera_start_framing_match", camera_match),
                            ("space_match", space_match),
                            ("empty_establishing_frame", empty_frame)):
            if value is None:
                blockers.append(f"REVIEWER_UNCERTAIN:{name}")

        # the engine's own supersets — checked here so a receipt is never written
        # that compile_grouped_seedance_manifest would raise on later.
        required_chars = list(expectations.get("required_visible_characters") or [])
        required_props = list(expectations.get("required_visible_props") or [])
        required_anchors = list(expectations.get("required_space_anchors") or [])
        missing_chars = sorted(set(required_chars) - set(observed_characters))
        missing_props = sorted(set(required_props) - set(observed_props))
        missing_anchors = sorted(set(required_anchors) - set(observed_space))
        if missing_chars:
            blockers.append("REQUIRED_CHARACTER_NOT_OBSERVED:" + ",".join(missing_chars))
        if missing_props:
            blockers.append("REQUIRED_PROP_NOT_OBSERVED:" + ",".join(missing_props))
        if missing_anchors:
            blockers.append("REQUIRED_SPACE_ANCHOR_NOT_OBSERVED:" + ",".join(missing_anchors))
        if required_chars and empty_frame is not False:
            blockers.append("EMPTY_FRAME_CLAIMED_BUT_CAST_REQUIRED")
        if str(answers.get("entry_state_only")) != "PASS":
            blockers.append("START_FRAME_NOT_ENTRY_STATE_ONLY")
        if camera_match is not True:
            blockers.append("CAMERA_START_FRAMING_NOT_VERIFIED")
        if space_match is not True:
            blockers.append("MAPPED_START_SPACE_NOT_VERIFIED")

        status = "PASS" if not blockers else "FAIL"
        payload = {
            "schema": EVIDENCE_SCHEMA,
            "episode": episode,
            "unit_id": unit_id,
            "shot_id": request_item.get("shot_id"),
            "status": status,
            "reference_path": str(reference_value) if reference_value else None,
            "reference_sha256": reference_sha,
            "observed_visible_characters": observed_characters,
            "observed_visible_props": observed_props,
            "observed_space_anchors": observed_space,
            "camera_start_framing_match": camera_match,
            "space_match": space_match,
            "empty_establishing_frame": empty_frame,
            "required_visible_characters": sorted(set(required_chars)),
            "required_visible_props": sorted(set(required_props)),
            "required_space_anchors": list(dict.fromkeys(required_anchors)),
            "entry_state": expectations.get("entry_state"),
            "start_frame_must_show_only_entry_state":
                expectations.get("start_frame_must_show_only_entry_state"),
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
            "consumed_by": "tools/grouped_anchor_semantic_contract.py"
                           " via compile_grouped_seedance_manifest.py:849-859",
        }
        target = evidence_path(episode, unit_id)
        write_json(target, payload)
        p.start_frame_evidence_mirror.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(target, p.start_frame_evidence_mirror / target.name)
        rows.append({
            "unit_id": unit_id,
            "status": status,
            "evidence_ref": f"{START_FRAME_EVIDENCE_RELDIR}/{target.name}",
            "evidence_path": str(target),
            "evidence_sha256": sha256_file(target),
            "reference_path": payload["reference_path"],
            "reference_sha256": reference_sha,
            "blockers": blockers,
        })

    passing = [row for row in rows if row["status"] == "PASS"]
    record = {
        "schema": "nalu.start_frame_evidence_index.v1",
        "episode": episode,
        "recorded_at": now(),
        "recorded_by": TOOL_ID,
        "reviewer": REVIEWER_ID,
        "review_method": REVIEW_METHOD,
        "review_file": str(submitted_path),
        "review_file_sha256": review_sha,
        "evidence_dir": str(ENGINE / START_FRAME_EVIDENCE_RELDIR),
        "evidence_ref_convention": f"{START_FRAME_EVIDENCE_RELDIR}/<UNIT_ID>_start_frame_evidence.json"
                                   "  (relative to the engine root, which is how "
                                   "grouped_anchor_semantic_contract._resolve reads it)",
        "status": ("PASS" if rows and len(passing) == len(rows)
                   else f"PARTIAL_{len(passing)}_OF_{len(rows)}" if rows else "NO_ITEMS"),
        "unit_count": len(rows),
        "pass_count": len(passing),
        "units": rows,
        "next": "re-run build_nalu_preproduction.py (S6 rebuild): build_start_frame_contracts "
                "picks the receipt up from expected_evidence_ref and 4.4 "
                "compile_grouped_seedance_manifest re-verifies every field.",
    }
    out = write_json(p.preprod_reports / f"{episode}_START_FRAME_EVIDENCE_INDEX.json", record)
    record["_written_to"] = str(out)
    return record


def verify(episode: str) -> dict[str, Any]:
    """Re-run the ENGINE's own validator against the current contracts + receipts."""
    p = QaPaths(episode)
    contracts = read_json(p.start_frames, {}) or {}
    editorial = read_json(p.editorial, {}) or {}
    shots = {str(row.get("shot_id")): row for row in editorial.get("shots") or []}
    try:
        validator = engine_module("grouped_anchor_semantic_contract")
    except Exception as exc:  # noqa: BLE001
        return {"status": "VALIDATOR_UNAVAILABLE", "error": str(exc)}
    rows = []
    for contract in contracts.get("units") or []:
        unit_id = str(contract.get("unit_id"))
        shot_id = str((contract.get("derived_from") or {}).get("shot_id") or "")
        spec = (shots.get(shot_id) or {}).get("prompt_spec") or {}
        reference_value = contract.get("reference_path")
        first_reference = {"path": reference_value,
                           "sha256": sha256_file(reference_value) if reference_value else None}
        try:
            validator.validate_start_anchor_semantics(
                contract, unit_id=unit_id, first_reference=first_reference,
                first_prompt_spec=spec, camera_plan={"start_framing": None},
                required_space_anchors=contract.get("required_space_anchors") or [],
                root=ENGINE)
            rows.append({"unit_id": unit_id, "status": "PASS"})
        except Exception as exc:  # noqa: BLE001 — the validator raises with the reason
            rows.append({"unit_id": unit_id, "status": "FAIL", "reason": str(exc)})
    passing = sum(1 for row in rows if row["status"] == "PASS")
    return {
        "schema": "nalu.start_frame_evidence_verify.v1",
        "episode": episode,
        "validator": "grouped_anchor_semantic_contract.validate_start_anchor_semantics",
        "status": "PASS" if rows and passing == len(rows) else "FAIL",
        "unit_count": len(rows), "pass_count": passing, "units": rows,
    }


def route_status(episode: str) -> dict[str, Any]:
    p = QaPaths(episode)
    contracts = read_json(p.start_frames, {}) or {}
    units = contracts.get("units") or []
    present = [row for row in units
               if evidence_path(episode, str(row.get("unit_id"))).is_file()]
    return {
        "writer": f"{__file__} write --episode {episode} --review <submitted review>",
        "evidence_schema": EVIDENCE_SCHEMA,
        "evidence_dir": str(ENGINE / START_FRAME_EVIDENCE_RELDIR),
        "evidence_ref_convention": f"{START_FRAME_EVIDENCE_RELDIR}/<UNIT_ID>_start_frame_evidence.json",
        "review_method": REVIEW_METHOD,
        "unit_count": len(units),
        "receipts_present": len(present),
        "contracts_pass": sum(1 for row in units if row.get("status") == "PASS"),
        "pending_inputs": sorted({str(value).split(":")[0]
                                  for row in units
                                  for value in row.get("pending_inputs") or []}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    wr = sub.add_parser("write")
    wr.add_argument("--episode", required=True)
    wr.add_argument("--review", required=True, type=Path)
    vf = sub.add_parser("verify")
    vf.add_argument("--episode", required=True)
    st = sub.add_parser("status")
    st.add_argument("--episode", required=True)
    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(route_status(args.episode), ensure_ascii=False, indent=2))
        return 0
    if args.command == "verify":
        record = verify(args.episode)
        print(json.dumps(record, ensure_ascii=False, indent=2)[:4000])
        return 0 if record.get("status") == "PASS" else 2

    submitted = read_json(args.review)
    if not isinstance(submitted, dict) or submitted.get("kind") != "start_frame":
        raise SystemExit(f"not a start_frame review: {args.review}")
    if submitted.get("validation", {}).get("status") != "PASS":
        raise SystemExit(f"review did not validate: {args.review}")
    record = materialise(args.episode, submitted, args.review)
    print(json.dumps({"status": record["status"], "units": record["unit_count"],
                      "pass": record["pass_count"], "out": record["_written_to"]},
                     ensure_ascii=False))
    return 0 if record["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
