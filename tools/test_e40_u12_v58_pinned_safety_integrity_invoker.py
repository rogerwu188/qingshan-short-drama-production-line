#!/usr/bin/env python3
"""Canonical and substitution-negative matrix for V58."""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];INVOKER=ROOT/'tools/run_e40_u12_v58_pinned_safety_integrity_gate.py'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rp(raw):
 p=Path(raw)
 if p.is_absolute() or '..' in p.parts:raise SystemExit('PATH_MUST_BE_REPO_RELATIVE')
 r=(ROOT/p).resolve();r.relative_to(ROOT);return r
def main():
 ap=argparse.ArgumentParser(allow_abbrev=False);ap.add_argument('--out',required=True);ap.add_argument('--canonical-output',required=True);a=ap.parse_args();out=rp(a.out);canonical=rp(a.canonical_output)
 if out.exists() or canonical.exists():raise SystemExit('OUT_OVERWRITE_FORBIDDEN')
 canonical.parent.mkdir(parents=True,exist_ok=True);cases=[]
 run=subprocess.run([sys.executable,str(INVOKER),'--out',str(canonical.relative_to(ROOT))],cwd=ROOT,capture_output=True,text=True);gate=json.loads(canonical.read_text()) if canonical.exists() else {}
 ok=run.returncode==0 and gate.get('status')=='PASS_10_OF_10_SAFETY_LEDGER_BINDINGS_EXACT_NO_MUTATION' and gate.get('binding_pass_count')==10 and gate.get('new_evidence_synthesized') is False and gate.get('authority_keys_admitted')==0 and gate.get('production_assets_admitted')==0 and gate.get('authorization') is False
 cases.append({'case_id':'CANONICAL_PINNED_10_OF_10','returncode':run.returncode,'output_created':canonical.exists(),'output_sha256':sha(canonical) if canonical.exists() else None,'passed':ok})
 for case_id,arg in [('MANIFEST_SUBSTITUTION_REJECTED','--manifest'),('VERIFIER_SUBSTITUTION_REJECTED','--verifier'),('GATE_SUBSTITUTION_REJECTED','--gate')]:
  target=canonical.with_name(canonical.stem+'_'+case_id+'.json');run=subprocess.run([sys.executable,str(INVOKER),'--out',str(target.relative_to(ROOT)),arg,'attacker.json'],cwd=ROOT,capture_output=True,text=True);cases.append({'case_id':case_id,'returncode':run.returncode,'output_created':target.exists(),'argparse_rejected_before_child':run.returncode==2 and not target.exists(),'passed':run.returncode==2 and not target.exists()})
 passed=len(cases)==4 and all(c['passed'] for c in cases)
 report={'schema':'qingshan.e40.u12.v58.pinned_safety_integrity_invoker_matrix.v1','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':'PASS_PINNED_SAFETY_INTEGRITY_10_OF_10_AND_3_SUBSTITUTIONS_REJECTED_NO_ADMISSION' if passed else 'FAIL_CLOSED_PINNED_SAFETY_INTEGRITY_INVOKER_REQUIRES_REVIEW','invoker_sha256':sha(INVOKER),'cases':cases,'case_count':len(cases),'case_pass_count':sum(c['passed'] for c in cases),'nested_binding_pass_count':gate.get('binding_pass_count'),'new_evidence_synthesized':False,'authority_keys_admitted':0,'production_assets_admitted':0,'real_evidence_validation_authorized':False,'positive_admission_test_authorized':False,'authorization':False,'maximum_new_submissions':0,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'generation_actions':0,'browser_started':False,'platform_state_changed':False,'work_queue_changed':False,'e38_state_changed':False,'e39_state_changed':False}}
 out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':report['status'],'cases':f"{report['case_pass_count']}/{report['case_count']}",'nested':report['nested_binding_pass_count']}));return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
