#!/usr/bin/env python3
"""CAS-record U02 V4 local precheck rejection while preserving active QA continuity."""
from __future__ import annotations
import hashlib,json,os,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1]; S=R/'workflow/production_line/E40_TASK_LANES_V1.json'; Q=R/'workflow/work_queue.json'
EXPECTED='6645a74bca144b60d4b3ff282cfa9eb0bb923bcad502c7d925f3a68fbf6e80c5'; T='E40-U02-V4-FAST720-EXACT-START-FRAME-NO-SUBMIT-PACKAGE-QA'; NOW='2026-08-14T06:15:30Z'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,d):
 fd,n=tempfile.mkstemp(prefix='.'+Path(p).name+'.',dir=Path(p).parent)
 try:
  with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
  os.replace(n,p)
 finally:
  if os.path.exists(n): os.unlink(n)
def main():
 if sha(S)!=EXPECTED: raise SystemExit('scheduler CAS mismatch '+sha(S))
 d=json.loads(S.read_text()); rows=[x for x in d['tasks'] if x.get('task_id')==T]
 if len(rows)!=1 or rows[0].get('state')!='QA': raise SystemExit('V4 QA not uniquely active')
 rows[0].update({'progress':'STATIC_PACKAGE_PASS_INSTALLED_PREFLIGHT_FAIL_ACTION_COMPLETION_AND_SLOW_MOTION_CODES_NO_PROVIDER',
  'last_progress_at':NOW,'executor_acknowledged_at':NOW,'next_due_at':'2026-08-14T06:28:00Z','executor_next_wakeup_at':'2026-08-14T06:28:00Z','lease_expires_at':'2026-08-14T08:18:00Z',
  'blocked_by':'ATOMIC_ACTION_COMPLETION_WINDOW_INVALID; ATOMIC_ACTION_DURATION_INVITES_SLOW_MOTION',
  'next_action':'Future V5 only: persist this precheck failure into prompt memory, materially redesign primary fan close to complete by 1.2s plus independent causal beats, create a new task key/fingerprint, then run one precheck-only invocation. Do not reuse V4 unchanged and do not submit.',
  'evidence_ref':'qa/e40_preproduction_20260814/u02_v4_fast720_no_submit_package_qa_v1/E40_U02_V4_FAST720_INSTALLED_PRECHECK_FAILURE_V1.json','evidence_sha256':'c3168172fd33e4d8853a164e62eaf11dc7732d6da5963dcfd60f9b7bf44ecbe3'})
 d['updated_at']=NOW; write(S,d); ss=sha(S)
 q=json.loads(Q.read_text()); q.update({'updated_at':NOW,'mode':'E40_CONTINUOUS_EPISODE_PRODUCTION_U29_ASSEMBLED_U02_V3_ADMITTED_U02_V4_FAST720_LOCAL_PREFLIGHT_FAIL_QA_ACTIVE',
  'status':'E40_U29_V77_ASSEMBLY_PASS_U02_V3_HUMAN88_ADMITTED_V4_FAST720_PREFLIGHT_FAIL_CLOSED_NO_PROVIDER',
  'updated_note_latest':'U02 V3 exact start frame is admitted at human 88. V4 Fast720 static package passed, but the installed authoritative precheck rejected the motion contract with ATOMIC_ACTION_COMPLETION_WINDOW_INVALID and ATOMIC_ACTION_DURATION_INVITES_SLOW_MOTION. No provider request, transaction or credit occurred. V4 remains active QA only for a future materially changed V5 design.',
  'next_action':'Future heartbeat: bind local precheck failure memory, materially redesign U02 V5 so the primary fan-close completes by 1.2s and later windows are independently causal, create new task key/fingerprint, then run one precheck-only call.'})
 v=q['latest_e40_u02_v4_fast720_no_submit_package']; v.update({'prompt':'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v4_fast720_exact_start_frame_v1/E40_U02_V4_FAST720_SILENT_VISUAL_PROMPT_V1.txt','prompt_sha256':'e55ee5d08a0cdbfbe995f167b223270f202367dd710870f846b9ca0a15657805',
  'manifest':'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v4_fast720_exact_start_frame_v1/E40_U02_V4_FAST720_NO_SUBMIT_MANIFEST_V1.json','manifest_sha256':'61ec7de0445a076dc1097b383123c0999b2ed9e7b40255ae32cc566d96af9863',
  'static_gate':'qa/e40_preproduction_20260814/u02_v4_fast720_no_submit_package_qa_v1/E40_U02_V4_FAST720_STATIC_GATE_V1.json','static_gate_sha256':'73989c0cf35230548205458b9edcbdc46228a049bb493fa62129f3af9d535aa5',
  'installed_precheck_failure':'qa/e40_preproduction_20260814/u02_v4_fast720_no_submit_package_qa_v1/E40_U02_V4_FAST720_INSTALLED_PRECHECK_FAILURE_V1.json','installed_precheck_failure_sha256':'c3168172fd33e4d8853a164e62eaf11dc7732d6da5963dcfd60f9b7bf44ecbe3',
  'provider_calls':0,'transactions':0,'credits':0,'status':'STATIC_PASS_INSTALLED_PREFLIGHT_FAIL_CLOSED_MATERIAL_V5_REQUIRED_NO_SUBMIT'})
 q['task_lane_scheduler'].update({'observed_sha256':ss,'status':'DYNAMIC_SNAPSHOT_U29_V77_ASSEMBLED_U02_V4_FAST720_QA_PREFLIGHT_FAIL_U18_TASK_LOCAL_REMOTE_WAIT','episode_terminal':False,'stale_leases_detected':False})
 write(Q,q); print(json.dumps({'status':'PASS','scheduler_sha256':ss,'work_queue_sha256':sha(Q)}))
if __name__=='__main__': main()
