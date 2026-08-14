#!/usr/bin/env python3
"""CAS-register/close U18 V7 local receipt-template compilation."""
from __future__ import annotations
import argparse,copy,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; STATE=ROOT/'workflow/production_line/E40_TASK_LANES_V1.json'
sys.path.insert(0,'/Users/rogerwu/.local/share/backlotos/share/pipeline-tools')
from task_lane_state_store import commit_task_updates,read_scheduler_snapshot  # noqa:E402
TASK='E40-U18-V7-EXACT-DOWNLOAD-CREDIT-OUTPUT-QA-RECEIPT-TEMPLATES-NO-EXECUTION'
WAIT='E40-U18-V8-EXACT-TASK-RETRIEVAL-AUTHORITY-TASK-LOCAL-REMOTE-WAIT'
def ts(x):return x.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['register','terminal-and-wait']);p.add_argument('--evidence-ref');p.add_argument('--evidence-sha256');a=p.parse_args();n=datetime.now(timezone.utc);s=read_scheduler_snapshot(STATE)
 row=next((copy.deepcopy(x) for x in s.payload['tasks'] if x.get('task_id')==TASK),None)
 if a.action=='register':
  if row: raise SystemExit('V7 already registered')
  row={'task_id':TASK,'lane_id':'U18_ISOLATED_ASSET_ACQUISITION','state':'QA','zero_cost':True,'deliverable_type':'EXACT_DOWNLOAD_CREDIT_OUTPUT_QA_RECEIPT_TEMPLATES_NO_EXECUTION','priority':177,'scope':['E40','U18','V7','LOCAL_QA','NO_PROVIDER','NO_DOWNLOAD','NO_TRANSACTION','NO_CREDITS'],'exact_predecessor_task_id':'E40-U18-V6-CHANGED-COMPACT-EXACT-TWO-IMAGE-ONE-POST-TASK-ID-BINDING','liveness_role':'PRODUCING','observation_only':False,'maximum_new_submissions':0,'authorization':False,'provider_post_allowed':False,'provider_calls':0,'transactions':0,'credits':0,'wait_scope':'NONE_ACTIVE_QA','progress':'REGISTERED_V7_LOCAL_TEMPLATE_QA','last_progress_at':ts(n),'next_action':'Compile exact receipt templates and SHA-lock contract without external execution.','lease_owner':'codex-e40-next-unit-audit:u18-v7','lease_expires_at':ts(n+timedelta(hours=2)),'next_due_at':ts(n+timedelta(minutes=20)),'execution_mode':'CONTINUOUS','executor_handle':'agent:/root/e40_next_unit_audit','executor_task_id':TASK,'executor_acknowledged_at':ts(n),'executor_next_wakeup_at':ts(n+timedelta(minutes=10)),'evidence_ref':a.evidence_ref,'evidence_sha256':a.evidence_sha256}
  updates={TASK:row}
 else:
  if not row or row.get('state')!='QA' or not a.evidence_ref or not a.evidence_sha256:raise SystemExit('V7 active/evidence required')
  row.update({'state':'TERMINAL','progress':'PASS_V7_TEMPLATES_AND_SHA_LOCKS_NO_EXECUTION','last_progress_at':ts(n),'completed_at':ts(n),'terminal_status':'PASS_V7_EXACT_RECEIPT_TEMPLATES_INPUT_CONTRACT_SHA_LOCKS_NO_EXECUTION','next_due_at':None,'evidence_ref':a.evidence_ref,'evidence_sha256':a.evidence_sha256,'blocked_by':'EXACT_TASK_RETRIEVAL_AUTHORITY_NOT_GRANTED'})
  for k in ['execution_mode','executor_handle','executor_task_id','executor_acknowledged_at','executor_next_wakeup_at']:row.pop(k,None)
  wait={'task_id':WAIT,'lane_id':'U18_ISOLATED_ASSET_ACQUISITION','state':'REMOTE_WAIT','zero_cost':True,'deliverable_type':'EXACT_TASK_RETRIEVAL_AUTHORITY_TASK_LOCAL_REMOTE_WAIT','priority':178,'scope':['E40','U18','V8','TASK_LOCAL','NO_PROVIDER','NO_DOWNLOAD','NO_POLL','NO_TRANSACTION','NO_CREDITS'],'exact_predecessor_task_id':TASK,'liveness_role':'PRODUCING','observation_only':False,'maximum_new_submissions':0,'authorization':False,'provider_post_allowed':False,'provider_calls':0,'transactions':0,'credits':0,'wait_scope':'TASK_LOCAL','blocked_by':'EXACT_TASK_RETRIEVAL_AUTHORITY_NOT_GRANTED','progress':'V7_TEMPLATES_READY_WAITING_EXACT_TASK_RETRIEVAL_AUTHORITY','last_progress_at':ts(n),'next_action':'Wake only on explicit exact-task retrieval authority; no platform query, download or polling.','lease_owner':'codex-e40-next-unit-audit:u18-v8-wait','lease_expires_at':ts(n+timedelta(hours=24)),'next_due_at':ts(n+timedelta(hours=12)),'execution_mode':'CONTINUOUS','executor_handle':'agent:/root/e40_next_unit_audit','executor_task_id':WAIT,'executor_acknowledged_at':ts(n),'executor_next_wakeup_at':ts(n+timedelta(hours=6)),'evidence_ref':a.evidence_ref,'evidence_sha256':a.evidence_sha256}
  updates={TASK:row,WAIT:wait}
 print(commit_task_updates(STATE,base_snapshot=s,task_updates=updates,writer_id='codex-e40-next-unit-audit:u18-v7'))
if __name__=='__main__':main()
