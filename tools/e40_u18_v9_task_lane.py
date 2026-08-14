#!/usr/bin/env python3
from __future__ import annotations
import argparse,copy,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];S=R/'workflow/production_line/E40_TASK_LANES_V1.json';sys.path.insert(0,'/Users/rogerwu/.local/share/backlotos/share/pipeline-tools')
from task_lane_state_store import commit_task_updates,read_scheduler_snapshot  # noqa:E402
V8='E40-U18-V8-EXACT-TASK-RETRIEVAL-AUTHORITY-TASK-LOCAL-REMOTE-WAIT';V9='E40-U18-V9-OFFLINE-EXACT-RESULT-AND-CREDIT-SNAPSHOT-INGEST-QA';V10='E40-U18-V10-EXACT-SNAPSHOT-ARRIVAL-TASK-LOCAL-REMOTE-WAIT'
def t(x):return x.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['register','terminal-and-wait']);p.add_argument('--evidence-ref',required=True);p.add_argument('--evidence-sha256',required=True);a=p.parse_args();n=datetime.now(timezone.utc);s=read_scheduler_snapshot(S);by={x['task_id']:copy.deepcopy(x) for x in s.payload['tasks']}
 if a.action=='register':
  if V9 in by:raise SystemExit('V9 exists')
  v8=by[V8]
  if v8.get('state')!='REMOTE_WAIT':raise SystemExit('V8 not remote wait')
  v8.update({'state':'TERMINAL','wait_scope':'NONE_TERMINAL','next_due_at':None,'completed_at':t(n),'terminal_status':'HANDOFF_TO_V9_LOCAL_OFFLINE_INGEST_QA','progress':'V9_LOCAL_QA_REGISTERED_NO_EXTERNAL_EXECUTION'})
  for k in ['execution_mode','executor_handle','executor_task_id','executor_acknowledged_at','executor_next_wakeup_at']:v8.pop(k,None)
  v9={'task_id':V9,'lane_id':'U18_ISOLATED_ASSET_ACQUISITION','state':'QA','zero_cost':True,'deliverable_type':'OFFLINE_EXACT_RESULT_AND_CREDIT_SNAPSHOT_INGEST_QA','priority':179,'scope':['E40','U18','V9','OFFLINE_ONLY','NO_NETWORK','NO_DOWNLOAD','NO_POLL','NO_TRANSACTION','NO_CREDITS'],'exact_predecessor_task_id':V8,'liveness_role':'PRODUCING','observation_only':False,'maximum_new_submissions':0,'authorization':False,'provider_post_allowed':False,'provider_query_allowed':False,'download_allowed':False,'provider_calls':0,'transactions':0,'credits':0,'wait_scope':'NONE_ACTIVE_QA','progress':'REGISTERED_V9_OFFLINE_INGEST_QA','last_progress_at':t(n),'next_action':'Implement and test closed-set local snapshot validator.','lease_owner':'codex-e40-next-unit-audit:u18-v9','lease_expires_at':t(n+timedelta(hours=2)),'next_due_at':t(n+timedelta(minutes=20)),'execution_mode':'CONTINUOUS','executor_handle':'agent:/root/e40_next_unit_audit','executor_task_id':V9,'executor_acknowledged_at':t(n),'executor_next_wakeup_at':t(n+timedelta(minutes=10)),'evidence_ref':a.evidence_ref,'evidence_sha256':a.evidence_sha256};u={V8:v8,V9:v9}
 else:
  v9=by[V9]
  if v9.get('state')!='QA':raise SystemExit('V9 not QA')
  v9.update({'state':'TERMINAL','wait_scope':'NONE_TERMINAL','next_due_at':None,'completed_at':t(n),'terminal_status':'PASS_V9_OFFLINE_CLOSED_SET_INGEST_VALIDATOR_AND_TESTS_NO_EXECUTION','progress':'PASS_V9_OFFLINE_VALIDATOR_POSITIVE_AND_NEGATIVE_TESTS','evidence_ref':a.evidence_ref,'evidence_sha256':a.evidence_sha256,'blocked_by':'EXACT_LOCAL_SNAPSHOTS_NOT_YET_PRESENT'})
  for k in ['execution_mode','executor_handle','executor_task_id','executor_acknowledged_at','executor_next_wakeup_at']:v9.pop(k,None)
  v10={'task_id':V10,'lane_id':'U18_ISOLATED_ASSET_ACQUISITION','state':'REMOTE_WAIT','zero_cost':True,'deliverable_type':'EXACT_SNAPSHOT_ARRIVAL_TASK_LOCAL_REMOTE_WAIT','priority':180,'scope':['E40','U18','V10','TASK_LOCAL','OFFLINE_ONLY','NO_PROVIDER','NO_DOWNLOAD','NO_POLL','NO_TRANSACTION','NO_CREDITS'],'exact_predecessor_task_id':V9,'liveness_role':'PRODUCING','observation_only':False,'maximum_new_submissions':0,'authorization':False,'provider_post_allowed':False,'provider_query_allowed':False,'download_allowed':False,'provider_calls':0,'transactions':0,'credits':0,'wait_scope':'TASK_LOCAL','blocked_by':'EXACT_TWO_LOCAL_RESULT_SNAPSHOTS_AND_AUTHORITATIVE_CREDIT_SNAPSHOT_NOT_PRESENT','progress':'V9_VALIDATOR_READY_WAITING_LOCAL_SNAPSHOT_ARRIVAL','last_progress_at':t(n),'next_action':'Wake only when exactly two local result snapshots and one authoritative local credit snapshot are durably present.','lease_owner':'codex-e40-next-unit-audit:u18-v10','lease_expires_at':t(n+timedelta(hours=24)),'next_due_at':t(n+timedelta(hours=12)),'execution_mode':'CONTINUOUS','executor_handle':'agent:/root/e40_next_unit_audit','executor_task_id':V10,'executor_acknowledged_at':t(n),'executor_next_wakeup_at':t(n+timedelta(hours=6)),'evidence_ref':a.evidence_ref,'evidence_sha256':a.evidence_sha256};u={V9:v9,V10:v10}
 print(commit_task_updates(S,base_snapshot=s,task_updates=u,writer_id='codex-e40-next-unit-audit:u18-v9'))
if __name__=='__main__':main()
