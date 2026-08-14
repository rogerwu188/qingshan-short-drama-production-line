#!/usr/bin/env python3
"""Verify V37 canonical-bound V23-V36 terminal evidence chain read-only."""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import run_e40_u29c_v17_atomic_link_publish_gate as base
MANIFEST=ROOT/'qa/e40_preproduction_20260808/u29c_v37_canonical_bound_chain_authority_v1/E40_U29C_V37_CANONICAL_BOUND_RECEIPT_EVIDENCE_CHAIN_MANIFEST_V1.json';MANIFEST_SHA='d34f069b63be4afef9885dd18dd09ad5393d423999abd0e378c865740a1badcb'
SPEC=ROOT/'qa/e40_preproduction_20260808/u29c_v37_canonical_bound_chain_authority_v1/E40_U29C_V37_CANONICAL_BOUND_RECEIPT_CHAIN_AUTHORITY_SPEC_V1.json';SPEC_SHA='f2861ab7c94b120892c9e5ddc6a855f91d9f139cec3da140905c531ed01d6d57'
SCHED=ROOT/'workflow/production_line/E40_TASK_LANES_V1.json';REPORT=SPEC.parent/'E40_U29C_V37_CANONICAL_BOUND_RECEIPT_CHAIN_AUTHORITY_AUDIT_V1.json';PASS='PASS_CANONICAL_BOUND_V23_TO_V36_TERMINAL_CHAIN_16_OF_16_TOPOLOGY_13_OF_13_NO_AUTHORITY_ELEVATION'
def dig(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):
 s=os.lstat(p);return {'path':str(p.relative_to(ROOT)),'sha256':dig(p),'device':s.st_dev,'inode':s.st_ino,'mode':oct(s.st_mode&0o7777),'nlink':s.st_nlink,'uid':s.st_uid,'gid':s.st_gid,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
def negs():
 rows=[]
 for flag in ('--manifest','--spec','--scheduler','--canonical','--canonical-manifest'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),flag,'/tmp/forbidden-substitution'],cwd=ROOT,text=True,capture_output=True,check=False);rows.append({'argument':flag,'exit_code':p.returncode,'rejected_before_verification':p.returncode==2,'report_created':REPORT.exists()})
 return rows
def main():
 argparse.ArgumentParser(description='Fixed V37 canonical chain verifier; substitutions forbidden.',allow_abbrev=False).parse_args()
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 fail=[];pins=[(MANIFEST,MANIFEST_SHA),(SPEC,SPEC_SHA)];pb=[ident(p) for p,_ in pins];pm=[x['sha256']==e for x,(_,e) in zip(pb,pins)]
 if not all(pm):print(json.dumps({'status':'FAIL_CLOSED_PIN_MISMATCH','pin_matches':pm}));return 1
 negatives=negs()
 if REPORT.exists() or not all(x['rejected_before_verification'] and not x['report_created'] for x in negatives):fail.append('SUBSTITUTION_NOT_REJECTED')
 manifest=json.loads(MANIFEST.read_text());bindings=manifest.get('bindings',[]);paths=[ROOT/x['path'] for x in bindings];before=[ident(p) for p in paths];rows=[]
 for b,x in zip(bindings,before):rows.append({'role':b['role'],'task_id':b.get('task_id'),'path':b['path'],'expected_sha256':b['sha256'],'actual_sha256':x['sha256'],'match':x['sha256']==b['sha256']})
 if len(rows)!=16 or not all(x['match'] for x in rows):fail.append('PHYSICAL_CHAIN_NOT_16_OF_16')
 scheduler=json.loads(SCHED.read_text());tasks={x['task_id']:x for x in scheduler['tasks']};terminal=[b for b in bindings if b.get('task_id')];task_rows=[]
 for i,b in enumerate(terminal):
  t=tasks.get(b['task_id']);expected_pred=terminal[i-1]['task_id'] if i else None;topology=True if i==0 else t is not None and t.get('exact_predecessor_task_id')==expected_pred;evidence=t is not None and t.get('state')=='TERMINAL' and t.get('evidence_ref')==b['path'] and t.get('evidence_sha256')==b['sha256'] and t.get('maximum_new_submissions')==0 and t.get('authorization') is False and t.get('provider_post_allowed') is False
  task_rows.append({'task_id':b['task_id'],'state':t.get('state') if t else None,'expected_predecessor':expected_pred,'actual_predecessor':t.get('exact_predecessor_task_id') if t else None,'topology_match':topology,'terminal_evidence_match_closed':evidence})
 if len(task_rows)!=14 or not all(x['terminal_evidence_match_closed'] for x in task_rows):fail.append('SCHEDULER_TERMINAL_EVIDENCE_NOT_14_OF_14')
 topology_count=sum(x['topology_match'] for x in task_rows[1:])
 if topology_count!=13:fail.append('TOPOLOGY_NOT_13_OF_13')
 canonical_exact=rows[0]['role']=='CANONICAL_SCRIPT' and rows[0]['match'] and rows[1]['role']=='CANONICAL_MANIFEST' and rows[1]['match'] and scheduler.get('canonical_script_sha256')==rows[0]['expected_sha256'] and scheduler.get('canonical_manifest_sha256')==rows[1]['expected_sha256']
 if not canonical_exact:fail.append('CANONICAL_NOT_EXACT_BOUND')
 policy=manifest.get('execution_permitted') is False and manifest.get('provider_post_allowed') is False and manifest.get('admission_closed') is True and manifest.get('blind_replay_allowed') is False
 if not policy:fail.append('AUTHORITY_ELEVATION')
 after=[ident(p) for p in paths];pa=[ident(p) for p,_ in pins]
 if before!=after:fail.append('CHAIN_IDENTITY_MUTATION')
 if pb!=pa:fail.append('PIN_IDENTITY_MUTATION')
 status=PASS if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v37.canonical_bound_receipt_chain_authority_audit.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':pb,'pin_expected_sha256':[e for _,e in pins],'pin_match_count':sum(pm),'pins_after':pa,'manifest':str(MANIFEST.relative_to(ROOT)),'manifest_sha256':MANIFEST_SHA,'binding_count':len(rows),'binding_match_count':sum(x['match'] for x in rows),'bindings':rows,'canonical_binding_exact':canonical_exact,'terminal_task_count':len(task_rows),'terminal_task_evidence_match_count':sum(x['terminal_evidence_match_closed'] for x in task_rows),'predecessor_topology_edge_count':13,'predecessor_topology_match_count':topology_count,'task_bindings':task_rows,'admission_closed_no_authority_elevation':policy,'chain_identity_before':before,'chain_identity_after':after,'substitution_negatives':negatives,'substitution_negative_count':sum(x['rejected_before_verification'] for x in negatives),'blind_replay_allowed':False,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V38 pinned canonical-bound chain regression.'}
 fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'bindings':sum(x['match'] for x in rows),'terminal':sum(x['terminal_evidence_match_closed'] for x in task_rows),'topology':topology_count,'substitution_negatives':sum(x['rejected_before_verification'] for x in negatives),'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
