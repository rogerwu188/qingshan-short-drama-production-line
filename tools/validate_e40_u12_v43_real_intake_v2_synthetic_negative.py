#!/usr/bin/env python3
"""Synthetic-negative-only validator for bundle-shaped U12 real-intake V2 QA."""

from __future__ import annotations
import argparse,copy,hashlib,json
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v43_real_intake_v2_contract/E40_U12_V43_REAL_FOUR_EVIDENCE_INTAKE_V2_CONTRACT.json'
CONTRACT_SHA='2d33b700323195d8da9fcef49f73a9a23c7f46322ac69c20602acb71692323d5'
FIXTURES=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v43_real_intake_v2_contract/E40_U12_V43_BUNDLE_SHAPED_SYNTHETIC_NEGATIVE_MATRIX.json'
FIXTURES_SHA='1448f907046f6a318360d63a1584f10ffe7368352f39a59b3e04dae0272b029c'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def path(raw):
 p=Path(raw)
 if p.is_absolute() or '..' in p.parts:raise ValueError(raw)
 r=(ROOT/p).resolve();r.relative_to(ROOT);return r
def merge(base,over):
 r=copy.deepcopy(base)
 for k,v in over.items():
  if isinstance(v,dict) and isinstance(r.get(k),dict):r[k].update(v)
  else:r[k]=v
 return r
def check(bundle,now):
 roles=['authority_request','roger_authorization','independent_signoff','source_layer_gate'];vals=[bundle[x] for x in roles]
 common=[(v.get('authority_request_sha256'),v.get('episode'),v.get('unit_id'),v.get('target_key'),v.get('source_package_sha256')) for v in vals]
 auth=[bundle['roger_authorization'],bundle['independent_signoff']]
 try:valid_auth=all(v.get('authorization') is True and datetime.fromisoformat(v['issued_at'].replace('Z','+00:00'))<=now<datetime.fromisoformat(v['expires_at'].replace('Z','+00:00')) and v.get('consumed_at') is None for v in auth) and len({v.get('authorization_nonce') for v in auth})==2 and all(v.get('authorization_nonce') for v in auth)
 except Exception:valid_auth=False
 pairs=[
 ('SYNTHETIC_NEGATIVE_QA_ONLY',bundle.get('synthetic_only') is True),
 ('POSITIVE_ADMISSION_TEST_FORBIDDEN',bundle.get('positive_admission_test') is False),
 ('ALL_FOUR_EXACT_SHA_AND_SCHEMA_VALID',bundle.get('schema')=='qingshan.e40.u12.v43.real_four_evidence_intake_bundle.v2' and all(isinstance(v,dict) for v in vals)),
 ('ALL_FOUR_BIND_SAME_REQUEST_TARGET_AND_SOURCE',len(set(common))==1 and all(common[0])),
 ('ROGER_AND_SIGNOFF_TRUE_DISTINCT_UNEXPIRED_UNCONSUMED',valid_auth),
 ('SOURCE_GATE_ADMITTED_FAILURE_ZERO',bundle['source_layer_gate'].get('status')=='PASS_FULL_SOURCE_LAYER_PACKAGE_ADMITTED_LOCAL_ONLY' and bundle['source_layer_gate'].get('failure_count')==0)]
 return [{'check':n,'status':'PASS' if ok else 'FAIL'} for n,ok in pairs]
def main():
 ap=argparse.ArgumentParser(allow_abbrev=False);ap.add_argument('--out',required=True);a=ap.parse_args();out=path(a.out)
 if out.exists():raise SystemExit('OUT_OVERWRITE_FORBIDDEN')
 c0,f0=sha(CONTRACT),sha(FIXTURES);contract=json.loads(CONTRACT.read_text());fx=json.loads(FIXTURES.read_text());now=datetime.fromisoformat(fx['evaluation_time'].replace('Z','+00:00'));rows=[]
 for case in fx['cases']:
  checks=check(merge(fx['base_bundle'],case['overrides']),now);fails=[x['check'] for x in checks if x['status']=='FAIL'];rows.append({'name':case['name'],'expected_failure':case['expected_failure'],'actual_failures':fails,'status':'PASS' if fails==[case['expected_failure']] else 'FAIL','checks':checks,'admission':False})
 pins=c0==sha(CONTRACT)==CONTRACT_SHA and f0==sha(FIXTURES)==FIXTURES_SHA;passed=pins and contract['current_execution_mode']=='SYNTHETIC_NEGATIVE_QA_ONLY' and contract['real_evidence_validation_authorized'] is False and contract['positive_admission_test_authorized'] is False and all(x['status']=='PASS' for x in rows)
 r={'schema':'qingshan.e40.u12.v43.real_intake_v2_synthetic_negative_gate.v1','status':'PASS_4_OF_4_BUNDLE_SHAPED_SYNTHETIC_NEGATIVES_NO_ADMISSION' if passed else 'FAIL_CLOSED_V43_SYNTHETIC_NEGATIVE_MISMATCH','contract_sha256':sha(CONTRACT),'fixtures_sha256':sha(FIXTURES),'pinned_inputs_unchanged':c0==sha(CONTRACT) and f0==sha(FIXTURES),'cases':rows,'case_count':len(rows),'pass_count':sum(x['status']=='PASS' for x in rows),'failure_count':sum(x['status']!='PASS' for x in rows)+(0 if pins else 1),'real_evidence_validation_authorized':False,'positive_admission_test_authorized':False,'authority_keys_admitted':0,'production_assets_admitted':0,'authorization':False,'maximum_new_submissions':0,'execution':False,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'generation_actions':0,'renders':0,'agentcut_actions':0,'assembly_actions':0,'release_actions':0,'browser_started':False,'platform_state_changed':False,'work_queue_changed':False,'e38_state_changed':False,'e39_state_changed':False}}
 out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':r['status'],'cases':f"{r['pass_count']}/{r['case_count']}",'failure_count':r['failure_count']}));return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
