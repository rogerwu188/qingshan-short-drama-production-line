#!/usr/bin/env python3
"""Fail-closed validator for E40/U12 four-evidence intake bundles."""

from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v35_four_evidence_preflight/E40_U12_V35_FOUR_EVIDENCE_INTAKE_CONTRACT.json"
CONTRACT_SHA256="3b045d8642b95030e41384cd8ea8aded7ef7c1ea3549f3a110462a4f8fdb6992"

def sha256(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def repo_path(raw:str)->Path:
 p=Path(raw)
 if p.is_absolute() or ".." in p.parts:raise ValueError(raw)
 r=(ROOT/p).resolve();r.relative_to(ROOT);return r
def add(checks:list[dict[str,Any]],name:str,ok:bool,detail:Any)->None:checks.append({"check":name,"status":"PASS" if ok else "FAIL","detail":detail})

def main()->int:
 ap=argparse.ArgumentParser(allow_abbrev=False);ap.add_argument("--bundle",required=True);ap.add_argument("--out",required=True);ap.add_argument("--expect-reject",action="store_true");args=ap.parse_args()
 contract=json.loads(CONTRACT.read_text());bundle_path=repo_path(args.bundle);bundle=json.loads(bundle_path.read_text());checks=[]
 add(checks,"CONTRACT_SHA_PIN",sha256(CONTRACT)==CONTRACT_SHA256,sha256(CONTRACT));add(checks,"BUNDLE_SCHEMA",bundle.get("schema")=="qingshan.e40.u12.v35.four_evidence_intake_bundle.v1",bundle.get("schema"))
 schemas=contract["required_evidence"]; loaded={}
 for role,schema_key in [("authority_request","authority_request_schema"),("roger_authorization","roger_authorization_schema"),("independent_signoff","independent_signoff_schema"),("source_layer_gate","source_layer_gate_schema")]:
  entry=bundle.get(role);present=isinstance(entry,dict);add(checks,f"{role.upper()}_PRESENT",present,entry)
  if not present:continue
  try:
   p=repo_path(entry.get("path") or "");exists=p.is_file();actual=sha256(p) if exists else None;data=json.loads(p.read_text()) if exists else None
  except (ValueError,OSError,json.JSONDecodeError):exists=False;actual=None;data=None
  add(checks,f"{role.upper()}_FILE_EXISTS",exists,entry.get("path"));add(checks,f"{role.upper()}_SHA_EXACT",actual==entry.get("sha256"),{"expected":entry.get("sha256"),"actual":actual});add(checks,f"{role.upper()}_SCHEMA_EXACT",bool(data) and data.get("schema")==schemas[schema_key],data.get("schema") if data else None);loaded[role]=data
 request=loaded.get("authority_request");add(checks,"AUTHORITY_REQUEST_AUTHORIZED",bool(request) and request.get("authorization") is True,request.get("authorization") if request else None)
 roger=loaded.get("roger_authorization");add(checks,"ROGER_AUTHORIZATION_TRUE",bool(roger) and roger.get("authorization") is True,roger.get("authorization") if roger else None)
 signoff=loaded.get("independent_signoff");add(checks,"INDEPENDENT_SIGNOFF_AUTHORIZED",bool(signoff) and signoff.get("authorization") is True,signoff.get("authorization") if signoff else None)
 source=loaded.get("source_layer_gate");required_status=schemas["source_layer_required_status"];add(checks,"SOURCE_LAYER_GATE_ADMITTED",bool(source) and source.get("status")==required_status and (source.get("failure_count") or 0)==0,{"required":required_status,"actual":source.get("status") if source else None})
 add(checks,"ALL_FOUR_PRESENT",all(isinstance(bundle.get(x),dict) for x in ["authority_request","roger_authorization","independent_signoff","source_layer_gate"]),None)
 failures=[c for c in checks if c["status"]=="FAIL"];status="PASS_FOUR_EVIDENCE_BUNDLE_READY_FOR_SEPARATE_REVIEW" if not failures else "FAIL_CLOSED_FOUR_EVIDENCE_BUNDLE_REJECTED"
 receipt={"schema":"qingshan.e40.u12.v35.four_evidence_intake_gate.v1","status":status,"bundle":str(bundle_path.relative_to(ROOT)),"checks":checks,"failure_count":len(failures),"failures":[c["check"] for c in failures],"authority_keys_admitted":0,"production_assets_admitted":0,"authorization":False,"maximum_new_submissions":0,"failure_behavior":contract["failure_behavior"]}
 out=repo_path(args.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n");print(json.dumps({"status":status,"failures":receipt["failures"]}))
 return 0 if (args.expect_reject and failures) or (not args.expect_reject and not failures) else 2
if __name__=="__main__":raise SystemExit(main())
