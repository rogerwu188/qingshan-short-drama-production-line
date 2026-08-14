#!/usr/bin/env python3
"""Read-only audit proving synthetic QA grants no real/positive authority."""
from __future__ import annotations
import argparse,ast,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PINS={
'BOUNDARY':('workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v46_positive_admission_authority_boundary/E40_U12_V46_POSITIVE_ADMISSION_AUTHORITY_BOUNDARY_CONTRACT.json','0f40432b9f1efd007d5e0263df3c403db6c9cfa6a472c34fc0d5e78b1af286f3'),
'V45_GATE':('qa/e40_preproduction_20260812/u12_v45_real_intake_safety_integrity/E40_U12_V45_REAL_INTAKE_SAFETY_INTEGRITY_GATE.json','2c7b17bdb1f964bb37afc67493f7216a2104e6248f864e0d9695a01a9c9b75d9'),
'V45_CLOSEOUT':('workflow/releases/E40_U12_V45_REAL_INTAKE_SAFETY_INTEGRITY_CLOSEOUT_20260812.json','7d28b594c7fe33b12dfff5c36462d2a87340e720b98da79312cb4cb6146e2a67'),
'V43_VALIDATOR':('tools/validate_e40_u12_v43_real_intake_v2_synthetic_negative.py','5389af8542105abd78244662b45ac9b5f725582a36e8a3a42e47518b58592911'),
'V44_INVOKER':('tools/run_e40_u12_v44_pinned_real_intake_v2_gate.py','4dc2e432be45304f91972d438522ee4b807280f9f94163ae8ce8384bf17aec39')}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rp(raw):
 p=(ROOT/raw).resolve();p.relative_to(ROOT);return p
def lits(src):return {n.value for n in ast.walk(ast.parse(src)) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
def main():
 ap=argparse.ArgumentParser(allow_abbrev=False);ap.add_argument('--out',required=True);a=ap.parse_args();out=rp(a.out)
 if out.exists():raise SystemExit('OUT_OVERWRITE_FORBIDDEN')
 rows=[];before={};data={}
 for role,(raw,expected) in PINS.items():
  p=rp(raw);actual=sha(p);before[role]=actual;data[role]=p.read_text();rows.append({'role':role,'path':raw,'expected_sha256':expected,'actual_sha256':actual,'status':'PASS' if actual==expected else 'FAIL'})
 boundary=json.loads(data['BOUNDARY']);gate=json.loads(data['V45_GATE']);close=json.loads(data['V45_CLOSEOUT']);vl=lits(data['V43_VALIDATOR']);il=lits(data['V44_INVOKER'])
 current=boundary['current_state'];checks={
 'all_prerequisites_absent':all(v is False for v in current.values()),
 'v45_real_validation_false':gate.get('real_evidence_validation_authorized') is False and close.get('real_evidence_validation_authorized') is False,
 'v45_positive_admission_false':gate.get('positive_admission_test_authorized') is False and close.get('positive_admission_test_authorized') is False,
 'validator_output_authority_zero':"authority_keys_admitted" in vl and "production_assets_admitted" in vl and "maximum_new_submissions" in vl,
 'invoker_accepts_only_out':{x for x in il if x.startswith('--')}=={'--out'},
 'real_bundle_cli_absent':'--bundle' not in il,
 'real_mode_cli_absent':'--real-mode' not in il,
 'positive_admission_cli_absent':'--positive-admission' not in il,
 'synthetic_capability_not_authority':gate.get('authorization') is False and gate.get('authority_keys_admitted')==0 and gate.get('production_assets_admitted')==0}
 after={role:sha(rp(raw)) for role,(raw,_) in PINS.items()};passed=all(x['status']=='PASS' for x in rows) and before==after and all(checks.values())
 r={'schema':'qingshan.e40.u12.v46.positive_admission_authority_boundary_gate.v1','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':'PASS_SYNTHETIC_CAPABILITY_CONFERS_NO_REAL_OR_POSITIVE_AUTHORITY' if passed else 'FAIL_CLOSED_AUTHORITY_BOUNDARY_MISMATCH','pinned_inputs':rows,'pinned_inputs_unchanged':before==after,'checks':checks,'check_count':len(checks),'pass_count':sum(checks.values()),'failure_count':sum(not x for x in checks.values()),'real_evidence_validation_authorized':False,'positive_admission_test_authorized':False,'authority_keys_admitted':0,'production_assets_admitted':0,'authorization':False,'maximum_new_submissions':0,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'generation_actions':0,'renders':0,'agentcut_actions':0,'assembly_actions':0,'release_actions':0,'browser_started':False,'platform_state_changed':False,'work_queue_changed':False,'e38_state_changed':False,'e39_state_changed':False}}
 out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':r['status'],'checks':f"{r['pass_count']}/{r['check_count']}",'failure_count':r['failure_count']}));return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
