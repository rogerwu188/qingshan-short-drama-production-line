#!/usr/bin/env python3
"""Pinned V38 regression over V37 canonical-bound receipt evidence chain."""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import run_e40_u29c_v17_atomic_link_publish_gate as base
MANIFEST=ROOT/'qa/e40_preproduction_20260808/u29c_v37_canonical_bound_chain_authority_v1/E40_U29C_V37_CANONICAL_BOUND_RECEIPT_EVIDENCE_CHAIN_MANIFEST_V1.json';MANIFEST_SHA='d34f069b63be4afef9885dd18dd09ad5393d423999abd0e378c865740a1badcb'
VERIFIER=ROOT/'tools/verify_e40_u29c_v37_canonical_bound_receipt_chain_authority.py';VERIFIER_SHA='07fc22233965dadd46f770dd110f7c1b62b0457eee5434db814eef715416151f'
AUDIT=ROOT/'qa/e40_preproduction_20260808/u29c_v37_canonical_bound_chain_authority_v1/E40_U29C_V37_CANONICAL_BOUND_RECEIPT_CHAIN_AUTHORITY_AUDIT_V1.json';AUDIT_SHA='96ff17308d82aa6d1555d86ad06421f9668258115be8797093a8a0bc3974138b'
SPEC=ROOT/'qa/e40_preproduction_20260808/u29c_v38_pinned_canonical_chain_regression_v1/E40_U29C_V38_PINNED_CANONICAL_BOUND_RECEIPT_CHAIN_REGRESSION_SPEC_V1.json';SPEC_SHA='0027447e0278d2e035ee290ec1252afaaf274db4167b36208f652dfb87e4d1d1'
CANON=ROOT/'workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md';CANON_SHA='140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b';CANON_MANIFEST=ROOT/'workflow/claude_writer_agent/scripts/E40_manifest_v3.json';CANON_MANIFEST_SHA='773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1';SCHED=ROOT/'workflow/production_line/E40_TASK_LANES_V1.json'
REPORT=SPEC.parent/'E40_U29C_V38_PINNED_CANONICAL_BOUND_RECEIPT_CHAIN_REGRESSION_MATRIX_V1.json';PASS='PASS_PINNED_CANONICAL_CHAIN_16_OF_16_TERMINAL_14_OF_14_TOPOLOGY_13_OF_13_NO_AUTHORITY_ELEVATION'
def dig(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):
 s=os.lstat(p);return {'path':str(p.relative_to(ROOT)),'sha256':dig(p),'device':s.st_dev,'inode':s.st_ino,'mode':oct(s.st_mode&0o7777),'nlink':s.st_nlink,'uid':s.st_uid,'gid':s.st_gid,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
def negs():
 rows=[]
 for flag in ('--manifest','--verifier','--audit','--spec','--scheduler','--canonical','--canonical-manifest'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),flag,'/tmp/forbidden-substitution'],cwd=ROOT,text=True,capture_output=True,check=False);rows.append({'argument':flag,'exit_code':p.returncode,'rejected_before_verification':p.returncode==2,'report_created':REPORT.exists()})
 return rows
def main():
 argparse.ArgumentParser(description='Fixed V38 canonical-chain regression; substitutions forbidden.',allow_abbrev=False).parse_args()
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 fail=[];pins=[(MANIFEST,MANIFEST_SHA),(VERIFIER,VERIFIER_SHA),(AUDIT,AUDIT_SHA),(SPEC,SPEC_SHA),(CANON,CANON_SHA),(CANON_MANIFEST,CANON_MANIFEST_SHA)];pb=[ident(p) for p,_ in pins];pm=[x['sha256']==e for x,(_,e) in zip(pb,pins)]
 if not all(pm):print(json.dumps({'status':'FAIL_CLOSED_PIN_MISMATCH','pin_matches':pm}));return 1
 authority=json.loads(AUDIT.read_text());authority_ok=authority.get('status')=='PASS_CANONICAL_BOUND_V23_TO_V36_TERMINAL_CHAIN_16_OF_16_TOPOLOGY_13_OF_13_NO_AUTHORITY_ELEVATION' and authority.get('binding_match_count')==16 and authority.get('terminal_task_evidence_match_count')==14 and authority.get('predecessor_topology_match_count')==13 and authority.get('admission_closed_no_authority_elevation') is True and authority.get('failures')==[]
 if not authority_ok:fail.append('V37_AUTHORITY_NOT_PASS_CLOSED')
 negatives=negs()
 if REPORT.exists() or not all(x['rejected_before_verification'] and not x['report_created'] for x in negatives):fail.append('SUBSTITUTION_NOT_REJECTED')
 manifest=json.loads(MANIFEST.read_text());bindings=manifest.get('bindings',[]);paths=[ROOT/x['path'] for x in bindings];before=[ident(p) for p in paths];rows=[]
 for b,x in zip(bindings,before):rows.append({'role':b['role'],'task_id':b.get('task_id'),'path':b['path'],'expected_sha256':b['sha256'],'actual_sha256':x['sha256'],'match':x['sha256']==b['sha256']})
 if len(rows)!=16 or not all(x['match'] for x in rows):fail.append('PHYSICAL_CHAIN_NOT_16_OF_16')
 scheduler=json.loads(SCHED.read_text());tasks={x['task_id']:x for x in scheduler['tasks']};terminal=[b for b in bindings if b.get('task_id')];task_rows=[]
 for i,b in enumerate(terminal):
  t=tasks.get(b['task_id']);pred=terminal[i-1]['task_id'] if i else None;top=True if i==0 else t is not None and t.get('exact_predecessor_task_id')==pred;evidence=t is not None and t.get('state')=='TERMINAL' and t.get('evidence_ref')==b['path'] and t.get('evidence_sha256')==b['sha256'] and t.get('maximum_new_submissions')==0 and t.get('authorization') is False and t.get('provider_post_allowed') is False
  task_rows.append({'task_id':b['task_id'],'expected_predecessor':pred,'actual_predecessor':t.get('exact_predecessor_task_id') if t else None,'topology_match':top,'terminal_evidence_match_closed':evidence})
 terminal_count=sum(x['terminal_evidence_match_closed'] for x in task_rows);topology=sum(x['topology_match'] for x in task_rows[1:])
 if terminal_count!=14:fail.append('TERMINAL_EVIDENCE_NOT_14_OF_14')
 if topology!=13:fail.append('TOPOLOGY_NOT_13_OF_13')
 canonical=rows[0]['match'] and rows[1]['match'] and scheduler.get('canonical_script_sha256')==CANON_SHA and scheduler.get('canonical_manifest_sha256')==CANON_MANIFEST_SHA
 if not canonical:fail.append('CANONICAL_NOT_EXACT')
 snapshot=before==authority.get('chain_identity_after')
 if not snapshot:fail.append('CHAIN_IDENTITY_DRIFT_FROM_V37')
 policy=manifest.get('execution_permitted') is False and manifest.get('provider_post_allowed') is False and manifest.get('admission_closed') is True and manifest.get('blind_replay_allowed') is False
 if not policy:fail.append('AUTHORITY_ELEVATION')
 after=[ident(p) for p in paths];pa=[ident(p) for p,_ in pins]
 if before!=after:fail.append('CHAIN_IDENTITY_MUTATION')
 if pb!=pa:fail.append('PIN_IDENTITY_MUTATION')
 status=PASS if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v38.pinned_canonical_bound_receipt_chain_regression_matrix.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':pb,'pin_expected_sha256':[e for _,e in pins],'pin_match_count':sum(pm),'pins_after':pa,'v37_authority_valid':authority_ok,'binding_count':len(rows),'binding_match_count':sum(x['match'] for x in rows),'bindings':rows,'terminal_task_count':len(task_rows),'terminal_task_evidence_match_count':terminal_count,'predecessor_topology_edge_count':13,'predecessor_topology_match_count':topology,'task_bindings':task_rows,'canonical_binding_exact':canonical,'v37_after_snapshot_exact':snapshot,'admission_closed_no_authority_elevation':policy,'chain_identity_before':before,'chain_identity_after':after,'substitution_negatives':negatives,'substitution_negative_count':sum(x['rejected_before_verification'] for x in negatives),'blind_replay_allowed':False,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V39 canonical-chain scheduler projection integrity audit.'}
 fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'bindings':sum(x['match'] for x in rows),'terminal':terminal_count,'topology':topology,'v37_snapshot_exact':snapshot,'substitution_negatives':sum(x['rejected_before_verification'] for x in negatives),'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
