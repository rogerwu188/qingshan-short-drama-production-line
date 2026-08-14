#!/usr/bin/env python3
"""CAS advance E40 U02 V3 harvested image to V4 Fast720 no-submit QA."""
from __future__ import annotations
import hashlib, json, os, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
S=ROOT/'workflow/production_line/E40_TASK_LANES_V1.json'
Q=ROOT/'workflow/work_queue.json'
EXPECTED='f65c156871044802e73382677e5d4bbaf024592a0c2c2bcd73cd10d7bfca7784'
NOW='2026-08-14T06:12:00Z'
REMOTE='E40-U02-V3-LOW-HEM-SCENE-AUTHORITY-REMOTE-RETRY1'
NEXT='E40-U02-V4-FAST720-EXACT-START-FRAME-NO-SUBMIT-PACKAGE-QA'

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
 d=json.loads(S.read_text())
 rows=[x for x in d['tasks'] if x.get('task_id')==REMOTE]
 if len(rows)!=1 or rows[0].get('state')!='REMOTE_WAIT': raise SystemExit('remote task not uniquely active')
 if any(x.get('task_id')==NEXT for x in d['tasks']): raise SystemExit('successor exists')
 rows[0].update({'state':'TERMINAL','wait_scope':'NONE_TERMINAL','provider_query_allowed':False,'download_allowed':False,
  'provider_calls':2,'progress':'COMPLETED_DOWNLOADED_PAY5_CLASSIFIED_ORIGINAL_RESOLUTION_HUMAN88_ADMITTED_EXACT_START_FRAME_ONLY',
  'last_progress_at':NOW,'next_due_at':None,'executor_next_wakeup_at':None,'blocked_by':None,
  'evidence_ref':'qa/e40_preproduction_20260814/u02_v3_low_hem_authority_human_qa_v1/E40_U02_V3_LOW_HEM_AUTHORITY_EXACT_START_FRAME_HUMAN_QA_V1.json',
  'evidence_sha256':'a397247256c2eec8cb85ea0452d0494f202acc81cb3e18e2a8518dfeccea4426',
  'output_ref':'working_assets/e40_production_20260814/u02_v3_low_hem_authority_exact_start_frame_retry1/E40_E40-U02-EXACT-START-FRAME-V3-LOW-HEM-AUTHORITY-RETRY1_52180a09-d3ef-47d0-afc1-44d30147c8a2.png',
  'output_sha256':'2f8841136030bd4f691ddb9faa77badfe52e7caf207f6f6975030703894fe725',
  'completed_at':NOW,'terminal_status':'PASS_HUMAN88_ADMITTED_EXACT_START_FRAME_ONLY',
  'terminal_outcome':'PASS_HUMAN88_ADMITTED_EXACT_START_FRAME_ONLY',
  'next_action':'Terminal asset acquisition; V4 owns local seedance-2.0-fast 720p no-submit package QA.'})
 d['tasks'].append({'task_id':NEXT,'lane_id':'U02_VIDEO_PRECOMPILE_QA','state':'QA','wait_scope':'NONE_ACTIVE_QA','zero_cost':True,
  'deliverable_type':'U02_FAST720_EXACT_START_FRAME_NO_SUBMIT_MANIFEST_AND_INSTALLED_PRECHECK','priority':165,
  'scope':['E40','U02','V4','SEEDANCE_2_0_FAST_ONLY','720P','EXACT_START_FRAME_SHA_BOUND','NO_PROVIDER','NO_SUBMIT','NO_TRANSACTION','NO_CREDITS'],
  'exact_predecessor_task_id':REMOTE,'liveness_role':'PRODUCING','observation_only':False,'maximum_new_submissions':0,
  'authorization':False,'provider_post_allowed':False,'provider_query_allowed':False,'download_allowed':False,'provider_calls':0,'transactions':0,'credits':0,
  'blocked_by':None,'progress':'V3_EXACT_START_FRAME_ADMITTED_V4_FAST720_NO_SUBMIT_PACKAGE_QA_ACTIVE','last_progress_at':NOW,
  'next_action':'Materially update the obsolete standard/1080p U02 prompt to seedance-2.0-fast/720p, bind exact start-frame SHA 2f884113..., compile a unique no-submit manifest, and run static plus installed precheck. No paid video request.',
  'lease_owner':'codex-e40-production:u02-v4-fast720-package','lease_expires_at':'2026-08-14T08:12:00Z','next_due_at':'2026-08-14T06:22:00Z',
  'execution_mode':'CONTINUOUS','executor_handle':'automation:e40','executor_task_id':NEXT,'executor_acknowledged_at':NOW,'executor_next_wakeup_at':'2026-08-14T06:22:00Z',
  'evidence_ref':'qa/e40_preproduction_20260814/u02_v3_low_hem_authority_human_qa_v1/E40_U02_V3_LOW_HEM_AUTHORITY_EXACT_START_FRAME_HUMAN_QA_V1.json',
  'evidence_sha256':'a397247256c2eec8cb85ea0452d0494f202acc81cb3e18e2a8518dfeccea4426'})
 d['updated_at']=NOW; write(S,d); ss=sha(S)
 q=json.loads(Q.read_text())
 q.update({'updated_at':NOW,'mode':'E40_CONTINUOUS_EPISODE_PRODUCTION_U29_ASSEMBLED_U02_V3_ADMITTED_U02_V4_FAST720_PACKAGE_QA_ACTIVE',
  'status':'E40_U29_V77_ASSEMBLY_PASS_U02_V3_HUMAN88_ADMITTED_V4_FAST720_NO_SUBMIT_QA_ACTIVE',
  'updated_note_latest':'U02 V3 task 52180a09-d3ef-47d0-afc1-44d30147c8a2 completed and was downloaded once. Original-resolution QA passed all hard gates at 88/80. Asset SHA 2f884113... is admitted only as U02 exact video start frame. V4 Fast720 no-submit package QA is active; no video provider action is authorized.',
  'next_action':'Compile and locally precheck one seedance-2.0-fast 720p U02 image-to-video no-submit manifest bound to exact start frame SHA 2f8841136030bd4f691ddb9faa77badfe52e7caf207f6f6975030703894fe725.'})
 q['e40_credits'].update({'active_remote_image_pay':0,'active_remote_image_task_id':None,'pending_remote_image_task_count':2,
  'pending_remote_image_task_ids':['17939df6-4f2c-4148-91c3-38f26870b6dc','bac46b24-b9a2-4a17-ab48-c2327b82b67a'],'pending_remote_image_credit_amount':None,
  'status':'AUTHORITATIVE_TOTALS_1447_128_1319_U02_V3_COMPLETED_PAY5_CLASSIFIED_PLUS_U18_V5_TWO_TASK_CLASSIFICATION_PENDING',
  'totals_fresh_through':'U02_V3_RETRY1_COMPLETED_HARVESTED_PAY5_RECONCILED'})
 q['latest_e40_u02_v3_low_hem_authority_remediation'].update({'harvest':'workflow/tasks/E40_U02_V3_LOW_HEM_AUTHORITY_IMAGE_HARVEST_20260814.json','harvest_sha256':'3f5d018089fd71d73178d9fc878389cfba348b94599ce274b067886c46352b8b',
  'output':'working_assets/e40_production_20260814/u02_v3_low_hem_authority_exact_start_frame_retry1/E40_E40-U02-EXACT-START-FRAME-V3-LOW-HEM-AUTHORITY-RETRY1_52180a09-d3ef-47d0-afc1-44d30147c8a2.png','output_sha256':'2f8841136030bd4f691ddb9faa77badfe52e7caf207f6f6975030703894fe725',
  'human_qa':'qa/e40_preproduction_20260814/u02_v3_low_hem_authority_human_qa_v1/E40_U02_V3_LOW_HEM_AUTHORITY_EXACT_START_FRAME_HUMAN_QA_V1.json','human_qa_sha256':'a397247256c2eec8cb85ea0452d0494f202acc81cb3e18e2a8518dfeccea4426','human_score':88,
  'provider_calls':2,'status':'COMPLETED_HARVESTED_HUMAN88_ADMITTED_EXACT_START_FRAME_ONLY_NO_REPLAY'})
 q['latest_e40_u02_v4_fast720_no_submit_package']={'exact_start_frame':'working_assets/e40_production_20260814/u02_v3_low_hem_authority_exact_start_frame_retry1/E40_E40-U02-EXACT-START-FRAME-V3-LOW-HEM-AUTHORITY-RETRY1_52180a09-d3ef-47d0-afc1-44d30147c8a2.png','exact_start_frame_sha256':'2f8841136030bd4f691ddb9faa77badfe52e7caf207f6f6975030703894fe725','model':'seedance-2.0-fast','resolution':'720p','provider_calls':0,'transactions':0,'credits':0,'status':'PACKAGE_QA_ACTIVE_NO_SUBMIT'}
 q['task_lane_scheduler'].update({'observed_sha256':ss,'status':'DYNAMIC_SNAPSHOT_U29_V77_ASSEMBLED_U02_V4_FAST720_QA_U18_TASK_LOCAL_REMOTE_WAIT','episode_terminal':False,'stale_leases_detected':False})
 write(Q,q)
 print(json.dumps({'status':'PASS','scheduler_sha256':ss,'work_queue_sha256':sha(Q)}))
if __name__=='__main__': main()
