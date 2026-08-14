#!/usr/bin/env python3
"""Audit U29B inventory admission and disabled final-chain source binding."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FORBIDDEN_SHA = "caffa28f91bc9aa6b2f7029c583ad416614b61b1937ec404c501475b6be06acb"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    inventory = load(root, args.inventory)
    slot = load(root, args.slot)
    project_rel = slot["verified_agentcut_source_project_path"]
    project = load(root, project_rel)
    clip = project["timeline"]["videoTracks"][0]["clips"][0]

    checks: dict[str, bool] = {}
    for name, item in (
        ("source", inventory["source"]),
        ("derivative", inventory["agentcut_compatible_derivative"]),
    ):
        checks[f"{name}_physical_sha"] = sha256(root / item["path"]) == item["sha256"]
    for name, receipt in (
        ("closeout", inventory["qa_receipts"]["editorial_and_parity_closeout"]),
        ("machine_qa", inventory["qa_receipts"]["machine"]),
        ("human_qa", inventory["qa_receipts"]["human"]),
    ):
        checks[f"{name}_physical_sha"] = sha256(root / receipt["path"]) == receipt["sha256"]
    checks["parent_skeleton_immutable_sha"] = sha256(root / slot["parent_skeleton_path"]) == slot["parent_skeleton_sha256"]
    checks["project_physical_sha"] = sha256(root / project_rel) == slot["verified_agentcut_source_project_sha256"]
    checks["project_actual_source_path"] = str((root / inventory["source"]["path"]).resolve()) == clip["source"] == slot["verified_actual_source_path"]
    checks["project_actual_source_sha"] = clip["metadata"]["source_sha256"] == inventory["source"]["sha256"] == slot["verified_actual_source_sha256"]
    checks["forbidden_provider_not_project_source"] = clip["metadata"]["source_sha256"] != FORBIDDEN_SHA
    checks["forbidden_provider_not_inventory_admitted"] = not inventory["forbidden_material"]["inventory_admission"]
    checks["independent_material_admitted"] = inventory["independent_material_admitted"] and slot["independent_material_admitted"]
    checks["final_chain_slot_disabled"] = not inventory["final_chain_slot_enabled"] and not slot["final_chain_slot_enabled"]
    checks["u29a_tail_evidence_null"] = slot["enable_condition"]["current_evidence"] is None and not slot["enable_condition"]["satisfied"]
    checks["no_u29a_tail_substitution"] = not inventory["hold"]["u29b_start_frame_or_local_reaction_may_satisfy_u29a_tail"]
    checks["no_assembly_or_render"] = not slot["assembly_started"] and not slot["render_started"]

    status = "PASS" if all(checks.values()) else "FAIL"
    payload = {
        "schema": "qingshan.e40.u29b.material_admission_source_reference_audit.v1",
        "status": status,
        "inventory_path": args.inventory,
        "inventory_sha256": sha256(root / args.inventory),
        "slot_candidate_path": args.slot,
        "slot_candidate_sha256": sha256(root / args.slot),
        "agentcut_project_path": project_rel,
        "agentcut_project_sha256": sha256(root / project_rel),
        "checks": checks,
        "independent_material_admitted": True,
        "final_chain_slot_enabled": False,
        "blocked_by": "ACCEPTED_U29A_SEMANTIC_TAIL_NULL",
        "provider_posts": 0,
        "transactions": 0,
        "credits": 0,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "out": str(args.out), "failed": [key for key, value in checks.items() if not value]}))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
