#!/usr/bin/env python3
from __future__ import annotations
import copy,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];S=R/'workflow/production_line/E40_TASK_LANES_V1.json';sys.path.insert(0,'/Users/rogerwu/.local/share/backlotos/share/pipeline-tools')
from task_lane_state_store import commit_task_updates,read_scheduler_snapshot  # noqa:E402
T='E40-U29C-V54-CHANGED-REPRESENTATION-AUTHORITY-TASK-LOCAL-REMOTE-WAIT'
def z(x):return x.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
def main():
 n=datetime.now(timezone.utc);s=read_scheduler_snapshot(S);t=copy.deepcopy(next(x for x in s.payload['tasks'] if x['task_id']==T))
 if not (t.get('state')=='REMOTE_WAIT' and t.get('wait_scope')=='TASK_LOCAL' and t.get('maximum_new_submissions')==0 and t.get('authorization') is False and t.get('executor_handle')=='agent:/root/e40_next_unit_audit'):raise SystemExit('FAIL_CLOSED_V54_BOUNDARY_DRIFT')
 t.update({'lease_expires_at':z(n+timedelta(hours=24)),'last_progress_at':z(n),'next_due_at':z(n+timedelta(hours=12)),'executor_acknowledged_at':z(n),'executor_next_wakeup_at':z(n+timedelta(hours=6))})
 print(commit_task_updates(S,base_snapshot=s,task_updates={T:t},writer_id='codex-e40-next-unit-audit:u29c-v54-continuity-renew'))
if __name__=='__main__':main()
