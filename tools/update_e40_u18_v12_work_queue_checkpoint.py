#!/usr/bin/env python3
"""CAS-update only the E40/U18 local wait checkpoint in work_queue."""
from __future__ import annotations
import argparse,fcntl,hashlib,json,os,tempfile
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];Q=R/'workflow/work_queue.json';S=R/'workflow/production_line/E40_TASK_LANES_V1.json'
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--expected-current-sha256',required=True);a=p.parse_args();lock=Q.with_suffix('.json.lock')
 with lock.open('a+b') as h:
  fcntl.flock(h,fcntl.LOCK_EX);old=Q.read_bytes()
  if sha(old)!=a.expected_current_sha256:raise SystemExit('CAS mismatch')
  d=json.loads(old);sched_sha=sha(S.read_bytes());now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
  d.update({'updated_at':now,'mode':'E40_U18_V12_LOCAL_SNAPSHOT_WAIT_AND_U29C_LEGAL_REMOTE_WAIT','status':'E40_U18_V12_EXACT_LOCAL_SNAPSHOT_TASK_LOCAL_REMOTE_WAIT_NO_WATCH_NO_POLL','updated_note_latest':'U18 two exact V5 image task IDs remain durably bound and replay-forbidden. V9 offline closed-set ingest and V11 atomic snapshot boundary are ready; V12 waits task-locally for exactly two stable local result snapshots plus one authoritative credit snapshot. Pending credit amount remains unknown, and generation-status polls remain zero. U29C V54 legal wait remains independent.'})
  u=d.pop('latest_e40_u18_v5_exact_two_remote_image_wait')
  u.update({'checkpoint':'V12','pending_remote_image_credit_amount':None,'v9_receipt':'qa/e40_preproduction_20260813/u18_v9_offline_ingest_v1/E40_U18_V9_OFFLINE_VALIDATOR_TEST_RECEIPT_V1.json','v9_receipt_sha256':'9450b1ed2191b0e1d2f60b6f6dc615c25f15d05469af4e903a417032981172a0','offline_validator':'tools/e40_u18_v9_offline_snapshot_ingest.py','offline_validator_sha256':'5ade3a34ee4995bc7de918609d6518549c5cb3432f2bcd4444651b0105636f92','v11_receipt':'qa/e40_preproduction_20260813/u18_v11_snapshot_boundary_v1/E40_U18_V11_BOUNDARY_AND_NEGATIVE_TEST_RECEIPT_V1.json','v11_receipt_sha256':'ff993f72738b61d84006ea3065ff35c6888fd9453e836d31bc7afa304e1cb960','watcher_spec':'qa/e40_preproduction_20260813/u18_v11_snapshot_boundary_v1/E40_U18_V11_READONLY_WATCHER_SPEC_V1.json','watcher_spec_sha256':'2253308a5abf4a89b41c71022f645ba4b5808fece96d19aea5e19d61b72c7de1','watcher_running':False,'status':'V12_EXACT_LOCAL_SNAPSHOT_TASK_LOCAL_REMOTE_WAIT_NO_WATCH_NO_POLL'})
  d['latest_e40_u18_v12_local_snapshot_wait']=u
  d['task_lane_scheduler'].update({'observed_sha256':sched_sha,'status':'DYNAMIC_SNAPSHOT_U18_V13_QA_AND_U29C_V54_TASK_LOCAL_REMOTE_WAIT_NO_POLL'})
  d['blocked_by']='U18 exact image task IDs are bound, but exactly two stable local result snapshots and one authoritative credit snapshot are absent; pending amount remains null. U29C V5 remains quarantined and needs separate changed-representation authorization plus qualifying licensed source. U12 independently lacks admitted source authority.'
  d['next_action']='Keep U18 local-only checkpoint and U29C V54 fail-closed. Do not watch, query, download or poll. When exact local snapshots are supplied, use only the offline validator before machine/human QA; no replay or new submit.'
  out=(json.dumps(d,ensure_ascii=False,indent=2)+'\n').encode();tmp=''
  with tempfile.NamedTemporaryFile(dir=Q.parent,prefix='.work_queue.u18v13.',suffix='.tmp',delete=False) as f:tmp=f.name;f.write(out);f.flush();os.fsync(f.fileno())
  if sha(Q.read_bytes())!=a.expected_current_sha256:Path(tmp).unlink();raise SystemExit('CAS changed')
  os.replace(tmp,Q);fd=os.open(Q.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
 print(json.dumps({'status':'COMMITTED_CAS','old_sha256':sha(old),'new_sha256':sha(out),'scheduler_sha256':sched_sha}))
if __name__=='__main__':main()
