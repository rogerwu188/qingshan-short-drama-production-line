#!/usr/bin/env python3
from __future__ import annotations
import argparse,copy,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];S=R/'workflow/production_line/E40_TASK_LANES_V1.json';sys.path.insert(0,'/Users/rogerwu/.local/share/backlotos/share/pipeline-tools')
from task_lane_state_store import commit_task_updates,read_scheduler_snapshot  # noqa:E402
P='E40-U18-V42-EXECUTOR-IMPLEMENTATION-AUTHORITY-TASK-LOCAL-REMOTE-WAIT';T='E40-U18-V43-EXECUTOR-INTERFACE-V1-FREEZE-QA';N='E40-U18-V44-NEW-VERSION-AND-PER-BUNDLE-AUTHORITY-TASK-LOCAL-REMOTE-WAIT'
def z(x):return x.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def strip(x):
 for k in ['execution_mode','executor_handle','executor_task_id','executor_acknowledged_at','executor_next_wakeup_at']:x.pop(k,None)
def main():
 a=argparse.ArgumentParser();a.add_argument('action',choices=['register','terminal-and-wait']);a.add_argument('--evidence-ref',required=True);a.add_argument('--evidence-sha256',required=True);o=a.parse_args();n=datetime.now(timezone.utc);s=read_scheduler_snapshot(S);b={x['task_id']:copy.deepcopy(x) for x in s.payload['tasks']}
 if o.action=='register':
  p=b[P]
  if p.get('state')!='REMOTE_WAIT':raise SystemExit('V42 is not active REMOTE_WAIT')
  p.update({'state':'TERMINAL','wait_scope':'NONE_TERMINAL','next_due_at':None,'completed_at':z(n),'terminal_status':'HANDOFF_TO_V43_EXECUTOR_INTERFACE_V1_FREEZE_QA'});strip(p)
  t={'task_id':T,'lane_id':'U18_ISOLATED_ASSET_ACQUISITION','state':'QA','zero_cost':True,'deliverable_type':'EXECUTOR_INTERFACE_V1_FREEZE_QA','priority':213,'scope':['E40','U18','V43','LOCAL_ONLY','MANIFEST_AND_COMPATIBILITY_TESTS_ONLY','NO_EXECUTOR_IMPLEMENTATION','NO_EXECUTION','NO_NETWORK'],'exact_predecessor_task_id':P,'liveness_role':'PRODUCING','observation_only':False,'maximum_new_submissions':0,'authorization':False,'provider_post_allowed':False,'provider_query_allowed':False,'download_allowed':False,'provider_calls':0,'transactions':0,'credits':0,'wait_scope':'NONE_ACTIVE_QA','progress':'REGISTERED_V43_EXECUTOR_INTERFACE_V1_FREEZE_QA','last_progress_at':z(n),'next_action':'Freeze V41 interface v1 content-addressably and test unauthorized extensions fail closed.','lease_owner':'codex-e40-next-unit-audit:u18-v43','lease_expires_at':z(n+timedelta(hours=2)),'next_due_at':z(n+timedelta(minutes=20)),'execution_mode':'CONTINUOUS','executor_handle':'agent:/root/e40_next_unit_audit','executor_task_id':T,'executor_acknowledged_at':z(n),'executor_next_wakeup_at':z(n+timedelta(minutes=10)),'evidence_ref':o.evidence_ref,'evidence_sha256':o.evidence_sha256};u={P:p,T:t}
 else:
  t=b[T]
  if t.get('state')!='QA':raise SystemExit('V43 is not active QA')
  t.update({'state':'TERMINAL','wait_scope':'NONE_TERMINAL','next_due_at':None,'completed_at':z(n),'terminal_status':'INTERFACE_V1_FROZEN_NO_IMPLEMENTATION','progress':'PASS_V43_COMPATIBILITY_AND_UNAUTHORIZED_EXTENSION_TESTS','evidence_ref':o.evidence_ref,'evidence_sha256':o.evidence_sha256});strip(t)
  q={'task_id':N,'lane_id':'U18_ISOLATED_ASSET_ACQUISITION','state':'REMOTE_WAIT','zero_cost':True,'deliverable_type':'NEW_VERSION_AND_PER_BUNDLE_AUTHORITY_TASK_LOCAL_REMOTE_WAIT','priority':214,'scope':['E40','U18','V44','TASK_LOCAL','OFFLINE_ONLY','NO_WATCH','NO_NETWORK','NO_EXECUTOR_PRESENT'],'exact_predecessor_task_id':T,'liveness_role':'PRODUCING','observation_only':False,'maximum_new_submissions':0,'authorization':False,'provider_post_allowed':False,'provider_query_allowed':False,'download_allowed':False,'provider_calls':0,'transactions':0,'credits':0,'wait_scope':'TASK_LOCAL','blocked_by':'NEW_VERSION_SHA_INDEPENDENT_SECURITY_AUDIT_AND_FRESH_PER_BUNDLE_AUTHORITY_NOT_PRESENT','progress':'V43_INTERFACE_V1_FROZEN_WAITING_NEW_VERSION_CHANGE_CONTROL_AND_FRESH_AUTHORITY','last_progress_at':z(n),'next_action':'Wake only on a separately versioned/SHA-bound interface, new independent security audit and fresh per-bundle authority; V41 tests confer no execution authority.','lease_owner':'codex-e40-next-unit-audit:u18-v44','lease_expires_at':z(n+timedelta(hours=24)),'next_due_at':z(n+timedelta(hours=12)),'execution_mode':'CONTINUOUS','executor_handle':'agent:/root/e40_next_unit_audit','executor_task_id':N,'executor_acknowledged_at':z(n),'executor_next_wakeup_at':z(n+timedelta(hours=6)),'evidence_ref':o.evidence_ref,'evidence_sha256':o.evidence_sha256};u={T:t,N:q}
 print(commit_task_updates(S,base_snapshot=s,task_updates=u,writer_id='codex-e40-next-unit-audit:u18-v43'))
if __name__=='__main__':main()
