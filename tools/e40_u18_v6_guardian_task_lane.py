#!/usr/bin/env python3
"""CAS-renew the exact-task U18 V6 guardian without provider activity."""

from __future__ import annotations
import argparse, copy, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'workflow/production_line/E40_TASK_LANES_V1.json'
sys.path.insert(0,'/Users/rogerwu/.local/share/backlotos/share/pipeline-tools')
from task_lane_state_store import commit_task_updates, read_scheduler_snapshot  # noqa: E402

TASK_ID='E40-U18-V6-CHANGED-COMPACT-EXACT-TWO-IMAGE-ONE-POST-TASK-ID-BINDING'
EVIDENCE='qa/e40_preproduction_20260813/u18_v6_exact_task_integrity_v1/E40_U18_V6_NO_EXECUTION_INTEGRITY_RECEIPT_V1.json'
EVIDENCE_SHA='288216bb154fc0963fae8f39f4b9c5c40b063415bdc54ebf504942a043795ae2'

def stamp(x): return x.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['renew','terminal'],nargs='?',default='renew');args=parser.parse_args()
    now=datetime.now(timezone.utc); snap=read_scheduler_snapshot(STATE)
    row=next((copy.deepcopy(x) for x in snap.payload['tasks'] if x.get('task_id')==TASK_ID),None)
    if not row or row.get('state')!='REMOTE_WAIT': raise SystemExit('V6 exact task guardian is not REMOTE_WAIT')
    if row.get('task_ids')!=['17939df6-4f2c-4148-91c3-38f26870b6dc','bac46b24-b9a2-4a17-ab48-c2327b82b67a']: raise SystemExit('V6 exact task ids drifted')
    row.update({
      'progress':'PASS_LOCAL_EXACT_TASK_TRANSACTION_RECEIPT_PLAN_QUEUE_SCHEDULER_INTEGRITY_NO_EXECUTION',
      'last_progress_at':stamp(now),'next_action':'Remain task-local remote wait. On a later authorized wakeup, run one exact-task retrieval checkpoint, authoritative credit classification, exact download/SHA binding, then machine and human QA. No polling or replay.',
      'lease_owner':'codex-e40-next-unit-audit:u18-v6-guardian','lease_expires_at':stamp(now+timedelta(hours=24)),'next_due_at':stamp(now+timedelta(hours=12)),
      'execution_mode':'CONTINUOUS','executor_handle':'agent:/root/e40_next_unit_audit','executor_task_id':TASK_ID,'executor_acknowledged_at':stamp(now),'executor_next_wakeup_at':stamp(now+timedelta(hours=6)),
      'evidence_ref':EVIDENCE,'evidence_sha256':EVIDENCE_SHA,
      'blocked_by':'EXACT_REMOTE_TASKS_BOUND_RETRIEVAL_AND_CREDIT_CLASSIFICATION_NOT_AUTHORIZED_THIS_TURN',
      'maximum_new_submissions':0,'authorization':False,'provider_post_allowed':False,
    })
    if args.action=='terminal':
        row.update({'state':'TERMINAL','wait_scope':'NONE_TERMINAL','next_due_at':None,'completed_at':stamp(now),'terminal_status':'PASS_V6_LOCAL_INTEGRITY_HANDOFF_TO_V7_V8_NO_EXECUTION','blocked_by':'EXACT_TASK_RETRIEVAL_AUTHORITY_NOT_GRANTED','next_action':'V8 is the sole U18 exact-task retrieval authority TASK_LOCAL REMOTE_WAIT successor.'})
        for key in ('execution_mode','executor_handle','executor_task_id','executor_acknowledged_at','executor_next_wakeup_at'): row.pop(key,None)
    print(commit_task_updates(STATE,base_snapshot=snap,task_updates={TASK_ID:row},writer_id='codex-e40-next-unit-audit:u18-v6-guardian'))
if __name__=='__main__': main()
