#!/usr/bin/env python3
"""Bounded read-only post-V3 authority and source-layer inventory."""

from __future__ import annotations

import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v34_post_v3_inventory_refresh/E40_U12_V34_POST_V3_INVENTORY_REFRESH_CONTRACT.json"
CONTRACT_SHA256 = "e9f3643980d30f2290d061eae1af56838ad648601359c6e5975c0a24db6670c8"

def sha256(p: Path) -> str: return hashlib.sha256(p.read_bytes()).hexdigest()

def repo_path(raw: str) -> Path:
    p=Path(raw)
    if p.is_absolute() or ".." in p.parts: raise ValueError(raw)
    r=(ROOT/p).resolve(); r.relative_to(ROOT); return r

def main() -> int:
    ap=argparse.ArgumentParser(allow_abbrev=False); ap.add_argument("--out",required=True); args=ap.parse_args()
    contract=json.loads(CONTRACT.read_text()); schemas=contract["exact_schemas"]
    found={role:[] for role in schemas}
    for root_raw in contract["bounded_roots"]:
        root=repo_path(root_raw)
        if not root.exists(): continue
        for p in root.rglob("*.json"):
            try: data=json.loads(p.read_text())
            except (OSError,json.JSONDecodeError): continue
            if not isinstance(data,dict): continue
            for role,schema in schemas.items():
                if data.get("schema")==schema:
                    found[role].append({"path":str(p.relative_to(ROOT)),"sha256":sha256(p),"status":data.get("status"),"authorization":data.get("authorization"),"failure_count":data.get("failure_count")})
    for rows in found.values(): rows.sort(key=lambda x:x["path"])
    authorized_requests=[x for x in found["authority_request"] if x["authorization"] is True]
    admitted_sources=[x for x in found["source_layer_gate"] if x["status"]=="PASS_FULL_SOURCE_LAYER_PACKAGE_ADMITTED_LOCAL_ONLY" and (x["failure_count"] or 0)==0]
    counts={
        "authority_request_schema_files":len(found["authority_request"]),
        "authorized_request_files":len(authorized_requests),
        "roger_authorization_schema_files":len(found["roger_authorization"]),
        "independent_signoff_schema_files":len(found["independent_signoff"]),
        "source_layer_gate_schema_files":len(found["source_layer_gate"]),
        "admitted_source_layer_gates":len(admitted_sources),
        "fully_authorized_requests":min(len(authorized_requests),len(found["roger_authorization"]),len(found["independent_signoff"])),
    }
    fail_closed=counts["fully_authorized_requests"]==0 or counts["admitted_source_layer_gates"]==0
    receipt={
        "schema":"qingshan.e40.u12.v34.post_v3_authority_source_inventory.v1",
        "recorded_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "status":"FAIL_CLOSED_NO_AUTHORIZED_AUTHORITY_OR_ADMITTED_SOURCE_LAYER" if fail_closed else "PASS_AUTHORITY_AND_SOURCE_LAYER_EVIDENCE_PRESENT_REVIEW_REQUIRED",
        "contract_sha256":sha256(CONTRACT),"contract_pin_ok":sha256(CONTRACT)==CONTRACT_SHA256,
        "counts":counts,"candidates":found,
        "all_request_candidates_negative_or_unauthorized":len(authorized_requests)==0,
        "all_source_layer_gates_rejected":len(admitted_sources)==0,
        "roger_seedance_fast_authorization_is_not_key_admission":True,
        "authority_keys_admitted":0,"production_assets_admitted":0,"authorization":False,"maximum_new_submissions":0,
        "side_effects":{"provider_calls":0,"transactions":0,"credits":0,"generation_actions":0,"renders":0,"agentcut_actions":0,"assembly_actions":0,"release_actions":0,"browser_started":False,"platform_state_changed":False,"work_queue_changed":False,"e38_state_changed":False,"e39_state_changed":False}
    }
    out=repo_path(args.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":receipt["status"],"counts":counts}))
    return 0 if receipt["contract_pin_ok"] else 1

if __name__=="__main__": raise SystemExit(main())
