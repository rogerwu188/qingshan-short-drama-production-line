#!/usr/bin/env python3
"""Pinned V40 regression over the V39 scheduler projection authority."""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import run_e40_u29c_v17_atomic_link_publish_gate as base
AUDITOR=ROOT/'tools/audit_e40_u29c_v39_canonical_chain_scheduler_projection_integrity.py';AUDITOR_SHA='0ede934cfd74976d40496e26d963d5506844ea1a493cf1da994f080acfbce234'
AUDIT=ROOT/'qa/e40_preproduction_20260808/u29c_v39_scheduler_projection_integrity_v1/E40_U29C_V39_CANONICAL_CHAIN_SCHEDULER_PROJECTION_INTEGRITY_AUDIT_V1.json';AUDIT_SHA='030862b95fe90beb3d47f2e0600724e9403d261a69b37b857b129d1a45b5a9d5'
CHAIN=ROOT/'qa/e40_preproduction_20260808/u29c_v37_canonical_bound_chain_authority_v1/E40_U29C_V37_CANONICAL_BOUND_RECEIPT_EVIDENCE_CHAIN_MANIFEST_V1.json';CHAIN_SHA='d34f069b63be4afef9885dd18dd09ad5393d423999abd0e378c865740a1badcb'
SPEC=ROOT/'qa/e40_preproduction_20260808/u29c_v40_pinned_scheduler_projection_regression_v1/E40_U29C_V40_PINNED_SCHEDULER_PROJECTION_REGRESSION_SPEC_V1.json';SPEC_SHA='ea4885637450641d6c28eca67c1458c9a48166794784f76b86831d46c442a2cc'
CANON=ROOT/'workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md';CANON_SHA='140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b';CANON_MANIFEST=ROOT/'workflow/claude_writer_agent/scripts/E40_manifest_v3.json';CANON_MANIFEST_SHA='773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1';SCHED=ROOT/'workflow/production_line/E40_TASK_LANES_V1.json'
REPORT=SPEC.parent/'E40_U29C_V40_PINNED_SCHEDULER_PROJECTION_REGRESSION_MATRIX_V1.json';PASS='PASS_PINNED_SCHEDULER_PROJECTION_16_OF_16_V39_SNAPSHOT_EXACT_UNIQUE_ZERO_AUTHORITY_NO_SUBMIT'
V37={'task_id':'E40-U29C-V37-CANONICAL-BOUND-RECEIPT-CHAIN-AUTHORITY-AUDIT-NO-SUBMIT','path':'qa/e40_preproduction_20260808/u29c_v37_canonical_bound_chain_authority_v1/E40_U29C_V37_CANONICAL_BOUND_RECEIPT_CHAIN_AUTHORITY_AUDIT_V1.json','sha256':'96ff17308d82aa6d1555d86ad06421f9668258115be8797093a8a0bc3974138b'};V38={'task_id':'E40-U29C-V38-PINNED-CANONICAL-BOUND-RECEIPT-CHAIN-REGRESSION-NO-SUBMIT','path':'qa/e40_preproduction_20260808/u29c_v38_pinned_canonical_chain_regression_v1/E40_U29C_V38_PINNED_CANONICAL_BOUND_RECEIPT_CHAIN_REGRESSION_MATRIX_V1.json','sha256':'d9649e20efe5d2dd3e6864e394967c109fe38e75d19175be4235dec40c4875fe'}
def dig(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):
 s=os.lstat(p);return {'path':str(p.relative_to(ROOT)),'sha256':dig(p),'device':s.st_dev,'inode':s.st_ino,'mode':oct(s.st_mode&0o7777),'nlink':s.st_nlink,'uid':s.st_uid,'gid':s.st_gid,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
def project(t):
 keys=('task_id','lane_id','state','zero_cost','exact_predecessor_task_id','evidence_ref','evidence_sha256','maximum_new_submissions','authorization','provider_post_allowed','provider_calls','transactions','credits','terminal_status','completed_at');return {k:t.get(k) for k in keys}
def negs():
 rows=[]
 for flag in ('--auditor','--audit','--chain','--spec','--scheduler','--canonical','--canonical-manifest'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),flag,'/tmp/forbidden-substitution'],cwd=ROOT,text=True,capture_output=True,check=False);rows.append({'argument':flag,'exit_code':p.returncode,'rejected_before_verification':p.returncode==2,'report_created':REPORT.exists()})
 return rows
def main():
 argparse.ArgumentParser(description='Fixed V40 projection regression; substitutions forbidden.',allow_abbrev=False).parse_args()
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 fail=[];pins=[(AUDITOR,AUDITOR_SHA),(AUDIT,AUDIT_SHA),(CHAIN,CHAIN_SHA),(SPEC,SPEC_SHA),(CANON,CANON_SHA),(CANON_MANIFEST,CANON_MANIFEST_SHA)];pb=[ident(p) for p,_ in pins];pm=[x['sha256']==e for x,(_,e) in zip(pb,pins)]
 if not all(pm):print(json.dumps({'status':'FAIL_CLOSED_PIN_MISMATCH','pin_matches':pm}));return 1
 authority=json.loads(AUDIT.read_text());authority_ok=authority.get('status')=='PASS_V23_TO_V38_SCHEDULER_PROJECTION_16_OF_16_UNIQUE_ZERO_AUTHORITY_NO_MUTATION_NO_SUBMIT' and authority.get('exact_projection_count')==16 and authority.get('physical_evidence_match_count')==16 and authority.get('zero_authority_counter_count')==16 and authority.get('duplicate_task_ids')==[] and authority.get('failures')==[]
 if not authority_ok:fail.append('V39_AUTHORITY_NOT_PASS_CLOSED')
 negatives=negs()
 if REPORT.exists() or not all(x['rejected_before_verification'] and not x['report_created'] for x in negatives):fail.append('SUBSTITUTION_NOT_REJECTED')
 chain=json.loads(CHAIN.read_text());expected=[{'task_id':x['task_id'],'path':x['path'],'sha256':x['sha256']} for x in chain['bindings'] if x.get('task_id')]+[V37,V38];sched_before=json.loads(SCHED.read_text());all_ids=[x.get('task_id') for x in sched_before['tasks']];duplicates=sorted({x for x in all_ids if all_ids.count(x)>1});tm={x['task_id']:x for x in sched_before['tasks']};before=[];rows=[]
 for i,e in enumerate(expected):
  t=tm.get(e['task_id']);proj=project(t) if t else None;before.append(proj);pred='E40-U29C-V22-RECOVERED-SUCCESS-RECEIPT-AND-CRASH-BOUNDARY-AUDIT-NO-SUBMIT' if i==0 else expected[i-1]['task_id'];physical=(ROOT/e['path']).is_file() and dig(ROOT/e['path'])==e['sha256'];fields=t is not None and t.get('lane_id')=='U29_VIDEO_QA' and t.get('state')=='TERMINAL' and t.get('zero_cost') is True and t.get('exact_predecessor_task_id')==pred and t.get('evidence_ref')==e['path'] and t.get('evidence_sha256')==e['sha256'] and isinstance(t.get('terminal_status'),str) and t['terminal_status'].startswith('PASS_') and isinstance(t.get('completed_at'),str);zero=t is not None and t.get('maximum_new_submissions')==0 and t.get('authorization') is False and t.get('provider_post_allowed') is False and t.get('provider_calls')==0 and t.get('transactions')==0 and t.get('credits')==0;rows.append({'task_id':e['task_id'],'physical_evidence_match':physical,'exact_projection_fields':fields,'zero_authority_counters':zero,'projection':proj})
 if duplicates:fail.append('DUPLICATE_TASK_IDS')
 if len(rows)!=16 or not all(x['physical_evidence_match'] and x['exact_projection_fields'] and x['zero_authority_counters'] for x in rows):fail.append('PROJECTION_NOT_16_OF_16_EXACT_CLOSED')
 snapshot=before==authority.get('projection_after')
 if not snapshot:fail.append('PROJECTION_DRIFT_FROM_V39')
 canonical=sched_before.get('canonical_script_sha256')==CANON_SHA and sched_before.get('canonical_manifest_sha256')==CANON_MANIFEST_SHA
 if not canonical:fail.append('CANONICAL_NOT_EXACT')
 sched_after=json.loads(SCHED.read_text());am={x['task_id']:x for x in sched_after['tasks']};after=[project(am.get(e['task_id'])) if am.get(e['task_id']) else None for e in expected];pa=[ident(p) for p,_ in pins]
 if before!=after:fail.append('PROJECTION_MUTATION')
 if pb!=pa:fail.append('PIN_MUTATION')
 status=PASS if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v40.pinned_scheduler_projection_regression_matrix.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':pb,'pin_expected_sha256':[e for _,e in pins],'pin_match_count':sum(pm),'pins_after':pa,'v39_authority_valid':authority_ok,'global_task_id_count':len(all_ids),'global_unique_task_id_count':len(set(all_ids)),'duplicate_task_ids':duplicates,'projection_task_count':len(rows),'exact_projection_count':sum(x['exact_projection_fields'] for x in rows),'physical_evidence_match_count':sum(x['physical_evidence_match'] for x in rows),'zero_authority_counter_count':sum(x['zero_authority_counters'] for x in rows),'projection_rows':rows,'v39_projection_snapshot_exact':snapshot,'projection_before':before,'projection_after':after,'canonical_binding_exact':canonical,'no_authority_elevation':True,'substitution_negatives':negatives,'substitution_negative_count':sum(x['rejected_before_verification'] for x in negatives),'blind_replay_allowed':False,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V41 scheduler projection field-schema integrity audit.'}
 fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'projection':sum(x['exact_projection_fields'] for x in rows),'snapshot':snapshot,'unique':not duplicates,'substitution_negatives':sum(x['rejected_before_verification'] for x in negatives),'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
