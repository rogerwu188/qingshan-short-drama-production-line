#!/usr/bin/env python3
"""Read-only exact-schema inventory for positive-admission prerequisites."""
from __future__ import annotations
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v47_authority_boundary_inventory/E40_U12_V47_AUTHORITY_BOUNDARY_PREREQUISITE_INVENTORY_SPEC.json';SPEC_SHA='4ae52523440a57036e9a162a98e55ccca3397d82a0c775e79d802589104ff0d6'
EXACT={
'ROGER_EXPLICIT_REAL_EVIDENCE_VALIDATION_AUTHORIZATION':'qingshan.e40.u12.roger_real_evidence_validation_authorization.v1',
'EXACT_AUTHORITY_REQUEST_SHA':'qingshan.e40.u12.real_validation_authority_request_binding.v1',
'INDEPENDENT_SIGNOFF_SHA':'qingshan.e40.u12.real_validation_independent_signoff_binding.v1',
'REAL_SOURCE_PACKAGE_SHA':'qingshan.e40.u12.real_validation_source_package_binding.v1',
'UNEXPIRED_UNCONSUMED_NONCES':'qingshan.e40.u12.real_validation_nonce_state.v1',
'SEPARATE_POSITIVE_ADMISSION_TEST_AUTHORIZATION':'qingshan.e40.u12.roger_positive_admission_test_authorization.v1'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rp(raw):
 p=(ROOT/raw).resolve();p.relative_to(ROOT);return p
def main():
 ap=argparse.ArgumentParser(allow_abbrev=False);ap.add_argument('--out',required=True);a=ap.parse_args();out=rp(a.out)
 if out.exists():raise SystemExit('OUT_OVERWRITE_FORBIDDEN')
 spec=json.loads(SPEC.read_text());rows=[];scanned=0;invalid=0;excluded_fast=0;excluded_synthetic=0;matches={k:[] for k in EXACT}
 for rawroot in spec['scan_roots']:
  root=rp(rawroot)
  if not root.exists():continue
  for p in root.rglob('*.json'):
   scanned+=1
   try:d=json.loads(p.read_text())
   except Exception:invalid+=1;continue
   schema=d.get('schema')
   if d.get('synthetic_only') is True or 'synthetic' in str(schema).lower():excluded_synthetic+=1;continue
   text=json.dumps(d,ensure_ascii=False).lower()
   if 'seedance-2.0-fast' in text or 'fast720' in text:excluded_fast+=1;continue
   for cat,expected in EXACT.items():
    if schema==expected:matches[cat].append({'path':str(p.relative_to(ROOT)),'sha256':sha(p)})
 for cat in spec['required_categories']:
  rows.append({'category':cat,'expected_schema':EXACT[cat],'match_count':len(matches[cat]),'matches':matches[cat],'present':len(matches[cat])>0})
 before=sha(SPEC);after=sha(SPEC);present=sum(x['present'] for x in rows);missing=len(rows)-present;passed=before==after==SPEC_SHA and len(rows)==6
 r={'schema':'qingshan.e40.u12.v47.authority_boundary_prerequisite_inventory.v1','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':'PASS_INVENTORY_0_OF_6_PREREQUISITES_PRESENT_FAIL_CLOSED' if passed and missing==6 else 'FAIL_CLOSED_PREREQUISITE_INVENTORY_REQUIRES_REVIEW','spec_sha256':after,'spec_unchanged':before==after,'files_scanned':scanned,'invalid_json_count':invalid,'excluded_seedance_fast_or_fast720_count':excluded_fast,'excluded_synthetic_count':excluded_synthetic,'categories':rows,'category_count':len(rows),'categories_present':present,'categories_missing':missing,'real_evidence_validation_authorized':False,'positive_admission_test_authorized':False,'authority_keys_admitted':0,'production_assets_admitted':0,'authorization':False,'maximum_new_submissions':0,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'generation_actions':0,'renders':0,'agentcut_actions':0,'assembly_actions':0,'release_actions':0,'browser_started':False,'platform_state_changed':False,'work_queue_changed':False,'e38_state_changed':False,'e39_state_changed':False}}
 out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':r['status'],'present':present,'missing':missing,'files_scanned':scanned}));return 0 if passed and missing==6 else 1
if __name__=='__main__':raise SystemExit(main())
