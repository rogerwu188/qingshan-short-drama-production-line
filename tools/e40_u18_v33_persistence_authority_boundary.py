#!/usr/bin/env python3
"""Machine-check fresh per-bundle root persistence authority boundary."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from tools.e40_u18_v25_final_persistence_preaudit import CANONICAL,ROOT,WORK_QUEUE
from tools.e40_u18_v31_atomic_persistence_bundle import FORMAL_MEMORY
V5_AUTH=("workflow/approvals/E40_U18_V5_CHANGED_COMPACT_EXACT_TWO_IMAGE_AUTHORIZATION_20260813.json","f333dfb04d6cea1ab6961cc5452ccf19231807e08246568b44c7ddb19852c8a3")
INVALID={"E40_U18_V5_IMAGE_AUTHORIZATION","ROGER_SEEDANCE_FAST_MODEL_AUTHORIZATION","HEARTBEAT_INSTRUCTIONS","STANDING_EPISODE_CREDIT_CAP","PRIOR_OR_BROAD_AUTHORIZATION"}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def wait(fs):return {'schema':'qingshan.e40.u18.v33.persistence_authority_boundary_result.v1','status':'TASK_LOCAL_REMOTE_WAIT','failures':sorted(set(fs)),'execution_authorized':False,'nonce_registration_permitted':False,'target_write_permitted':False,'scope':'U18_ONLY','blocks_other_lanes':False,'maximum_new_submissions':0}
def check(bundle_path:Path,authority_path:Path|None=None,root:Path=ROOT):
 fs=[]
 try:b=json.loads(bundle_path.read_text())
 except Exception:b={};fs.append('V31_BUNDLE_MISSING_OR_INVALID')
 if b.get('schema')!='qingshan.e40.u18.v31.atomic_persistence_bundle.v1' or b.get('status')!='ATOMIC_PERSISTENCE_BUNDLE_READY_DRY_RUN_ONLY' or b.get('dry_run_only') is not True:fs.append('V31_BUNDLE_BOUNDARY_INVALID')
 locks=b.get('locks') or {}
 for label,(rel,expected) in {**CANONICAL,'work_queue':WORK_QUEUE,'formal_memory':FORMAL_MEMORY}.items():
  p=root/rel
  lock_key={'script':'canonical_script_sha256','manifest':'canonical_manifest_sha256','work_queue':'work_queue_sha256','formal_memory':'current_formal_memory_sha256'}[label]
  if not p.is_file() or sha(p)!=expected or locks.get(lock_key)!=expected:fs.append(f'{label.upper()}_FRESH_LOCK_FAILED')
 lp=Path(locks.get('nonce_ledger_path') or '__missing__');lp=lp if lp.is_absolute() else root/lp
 try:ledger=json.loads(lp.read_text())
 except Exception:ledger={};fs.append('NONCE_LEDGER_MISSING_OR_INVALID')
 if not lp.is_file() or sha(lp)!=locks.get('nonce_ledger_sha256') or sum(1 for x in ledger.get('used_nonces',[]) if x==b.get('nonce'))!=0:fs.append('NONCE_LEDGER_FRESH_ZERO_MATCH_FAILED')
 target=Path(locks.get('target_path') or '__missing__');target=target if target.is_absolute() else root/target
 if target.exists() or locks.get('target_absent') is not True:fs.append('TARGET_NOT_ABSENT')
 dp=Path(locks.get('explicit_decision_path') or '__missing__');dp=dp if dp.is_absolute() else root/dp
 try:d=json.loads(dp.read_text())
 except Exception:d={};fs.append('EXPLICIT_DECISION_MISSING_OR_INVALID')
 expected_type='EXPLICIT_ROOT_DECISION' if b.get('branch')=='AUTHORIZATION' else 'EXPLICIT_MEMORY_DECISION' if b.get('branch')=='FORMAL_MEMORY_UPDATE_EVENT' else None
 if not dp.is_file() or sha(dp)!=locks.get('explicit_decision_sha256') or d.get('decision_type')!=expected_type:fs.append('EXPLICIT_DECISION_OR_BRANCH_LOCK_FAILED')
 if authority_path is None:
  a={};fs.append('FRESH_PER_BUNDLE_ONE_TIME_ROOT_PERSISTENCE_AUTHORIZATION_REQUIRED')
 else:
  try:a=json.loads(authority_path.read_text())
  except Exception:a={};fs.append('ROOT_PERSISTENCE_AUTHORITY_INVALID')
  if a.get('authority_source') in INVALID:fs.append('INVALID_INHERITED_AUTHORITY_SOURCE')
  if a.get('schema')!='qingshan.e40.u18.v33.one_time_root_persistence_authorization.v1' or a.get('one_time') is not True or a.get('consumed') is not False or a.get('bundle_sha256')!=b.get('bundle_sha256') or a.get('branch')!=b.get('branch'):fs.append('ROOT_PERSISTENCE_AUTHORITY_NOT_EXACT_FRESH_PER_BUNDLE')
 # Pin old image auth only as forbidden evidence, never authority.
 if not (root/V5_AUTH[0]).is_file() or sha(root/V5_AUTH[0])!=V5_AUTH[1]:fs.append('V5_HISTORICAL_AUTH_EVIDENCE_DRIFT')
 if fs:return wait(fs)
 return {**wait([]),'status':'PRECONDITIONS_PASS_BUT_EXECUTION_NOT_AUTHORIZED_BY_THIS_CHECKER','failures':[],'execution_authorized':False,'fresh_one_time_authority_present':True,'bundle_sha256':b.get('bundle_sha256'),'branch':b.get('branch')}
def main():
 p=argparse.ArgumentParser();p.add_argument('--v31-bundle',type=Path,required=True);p.add_argument('--root-persistence-authority',type=Path);p.add_argument('--out',type=Path);a=p.parse_args();r=check(a.v31_bundle,a.root_persistence_authority);s=json.dumps(r,ensure_ascii=False,indent=2)+'\n';a.out.write_text(s) if a.out else print(s,end='');return 0 if r['status'].startswith('PRECONDITIONS_PASS') else 3
if __name__=='__main__':raise SystemExit(main())
