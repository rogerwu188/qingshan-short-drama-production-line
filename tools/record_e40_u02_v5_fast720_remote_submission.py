#!/usr/bin/env python3
"""Record bound U02 V5 video submission and keep its task-local remote successor active."""
from __future__ import annotations
import hashlib, json, os, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHED = ROOT / 'workflow/production_line/E40_TASK_LANES_V1.json'
QUEUE = ROOT / 'workflow/work_queue.json'
AUTH = ROOT / 'workflow/approvals/E40_U02_V5_FAST720_EXACTLY_ONCE_AUTHORIZATION_20260814.json'
SUBMIT = ROOT / 'workflow/tasks/E40_U02_V5_FAST720_EXACTLY_ONCE_SUBMIT_20260814.json'
TRANSACTION = ROOT / 'workflow/tasks/giggle_video_submit_transactions/E40/E40-U02-V5-FAST720-LOW-HEM-EXACT-FIRST-FRAME-CAUSAL-BEATS-SILENT-V1__bf9c35e79327303e.json'
RECEIPT = ROOT / 'workflow/tasks/E40_U02_V5_FAST720_EXACTLY_ONCE_SUBMIT_20260814_receipts/E40-U02-V5-FAST720-LOW-HEM-EXACT-FIRST-FRAME-CAUSAL-BEATS-SILENT-V1_submit_receipt.json'
PRECHECK = ROOT / 'qa/e40_preproduction_20260814/u02_v5_fast720_exactly_once_readiness_v1/E40_U02_V5_FAST720_EXECUTION_PRECHECK_V1.json'

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def portable(path): return str(Path(path).relative_to(ROOT))
def write(path, payload):
    path = Path(path); fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2); handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def main():
    report = json.loads(SUBMIT.read_text()); task = report['tasks'][0]
    task_id = task['task_id']
    if report.get('status') != 'PASS' or report.get('submitted') != 1 or report.get('failed') != 0: raise SystemExit('submit report not exact pass')
    if report['credit_reconciliation'].get('charged_credits') != 64 or report.get('ambiguity_resolution') != 'NO_AMBIGUOUS_SUBMISSIONS': raise SystemExit('credit classification not exact Pay64')
    tx = json.loads(TRANSACTION.read_text())
    if tx.get('state') != 'SUBMITTED_TASK_ID_BOUND' or tx.get('task_id') != task_id: raise SystemExit('transaction task binding invalid')

    auth = json.loads(AUTH.read_text())
    auth.update({'status':'CONSUMED_EXACTLY_ONCE_NO_REPLAY','consumed_provider_posts':1,'bound_provider_task_id':task_id,
                 'submission_receipt':{'path':portable(RECEIPT),'sha256':sha(RECEIPT)},
                 'transaction':{'path':portable(TRANSACTION),'sha256':sha(TRANSACTION),'state':'SUBMITTED_TASK_ID_BOUND'},
                 'credit_classification':{'pay':64,'refund':0,'net':64,'status':'PASS_AUTHORITATIVE_EXACT_WINDOW'}})
    write(AUTH, auth)

    scheduler = json.loads(SCHED.read_text()); scheduler['updated_at'] = '2026-08-14T06:30:00Z'
    predecessor = None
    for row in scheduler['tasks']:
        if row.get('task_id') == 'E40-U02-V4-FAST720-EXACT-START-FRAME-NO-SUBMIT-PACKAGE-QA':
            predecessor = row
            row.update({'state':'TERMINAL','wait_scope':'NONE_TERMINAL','blocked_by':None,
                        'progress':'V4_PREFLIGHT_FAILURE_MEMORY_PF033_PERSISTED_V5_MATERIALLY_CHANGED_AND_EXECUTION_PREFLIGHT_PASS',
                        'last_progress_at':'2026-08-14T06:30:00Z','next_action':'Terminal. V5 task-local remote successor owns the bound provider task and forbids replay.',
                        'next_due_at':None,'executor_acknowledged_at':'2026-08-14T06:30:00Z','executor_next_wakeup_at':None,
                        'completed_at':'2026-08-14T06:30:00Z','terminal_status':'PASS_V5_MATERIAL_REMEDIATION_PREFLIGHT_AND_EXACTLY_ONCE_SUBMISSION'})
    if predecessor is None: raise SystemExit('missing V4 predecessor')
    new_id = 'E40-U02-V5-FAST720-EXACTLY-ONCE-TASK-LOCAL-REMOTE-WAIT'
    if any(row.get('task_id') == new_id for row in scheduler['tasks']): raise SystemExit('V5 successor already exists')
    scheduler['tasks'].append({
        'task_id':new_id,'provider_task_id':task_id,'lane_id':'VIDEO_GENERATION_REMOTE','state':'REMOTE_WAIT','wait_scope':'TASK_LOCAL','zero_cost':False,
        'deliverable_type':'U02_V5_FAST720_EXACT_START_FRAME_VIDEO','priority':166,
        'scope':['E40','U02','V5','SEEDANCE_2_0_FAST_ONLY','720P','EXACT_START_FRAME','EXACTLY_ONCE','TASK_LOCAL_REMOTE_WAIT'],
        'exact_predecessor_task_id':predecessor['task_id'],'liveness_role':'PRODUCING','observation_only':False,'maximum_new_submissions':0,
        'authorization':True,'authorization_consumed':True,'provider_post_allowed':False,'provider_query_allowed':True,'download_allowed':True,
        'provider_calls':1,'provider_posts_consumed':1,'transactions':1,'credits':64,'pay':64,'refund':0,'net':64,'blocked_by':None,
        'progress':'SUBMITTED_TASK_ID_BOUND_PAY64_AUTHORITATIVELY_CLASSIFIED_REMOTE_RUNNING_NO_REPLAY',
        'last_progress_at':'2026-08-14T06:30:00Z','next_action':'At the scheduled task-local wakeup, query this exact task_id once. If complete, download once and run exact-frame, frame0-to-frame1, silent-audio, cadence, OCR and original-resolution human QA before AgentCut.',
        'lease_owner':'codex-e40-production:u02-v5-fast720-remote','lease_expires_at':'2026-08-14T08:30:00Z','next_due_at':'2026-08-14T06:38:00Z',
        'execution_mode':'CONTINUOUS','executor_handle':'automation:e40','executor_task_id':new_id,'executor_acknowledged_at':'2026-08-14T06:30:00Z','executor_next_wakeup_at':'2026-08-14T06:38:00Z',
        'evidence_ref':portable(SUBMIT),'evidence_sha256':sha(SUBMIT),'transaction_ref':portable(TRANSACTION),'transaction_sha256':sha(TRANSACTION),
        'submission_receipt_ref':portable(RECEIPT),'submission_receipt_sha256':sha(RECEIPT),'installed_precheck_ref':portable(PRECHECK),'installed_precheck_sha256':sha(PRECHECK)})
    write(SCHED, scheduler)

    queue = json.loads(QUEUE.read_text()); queue['updated_at'] = '2026-08-14T06:30:00Z'
    queue['mode'] = 'E40_CONTINUOUS_EPISODE_PRODUCTION_U29_ASSEMBLED_U02_V5_FAST720_REMOTE_RUNNING'
    queue['occupied_scope_count'] = 2; queue['real_active_handle_count'] = 3
    queue['status'] = 'E40_U29_V77_ASSEMBLY_PASS_U02_V5_FAST720_TASK_BOUND_PAY64_REMOTE_RUNNING'
    queue['updated_note_latest'] = f'U02 V5 materially changed 4s causal prompt passed both installed prechecks and was submitted exactly once as {task_id}; transaction is bound and Pay64 is authoritatively classified. No replay is allowed. Task-local remote harvest/QA remains active.'
    credits = queue['e40_credits']; credits.update({'gross_pay':1511,'refund':128,'net':1383,'remaining':8617,'video_pay':1120,'active_remote_video_pay':64,
        'status':'AUTHORITATIVE_TOTALS_1511_128_1383_U02_V5_VIDEO_TASK_BOUND_PAY64_PLUS_U18_V5_TWO_TASK_CLASSIFICATION_PENDING',
        'totals_fresh_through':'U02_V5_FAST720_SUBMITTED_TASK_BOUND_PAY64_RECONCILED','active_remote_video_task_id':task_id,
        'pending_remote_video_task_count':1,'pending_remote_video_task_ids':[task_id]})
    queue['latest_e40_u02_v5_fast720_execution'] = {'task_id':task_id,'model':'seedance-2.0-fast','resolution':'720p','duration_seconds':4,
        'prompt_sha256':'b9398395d20845b5b876b25ca4f5235040aa4126f04ff87ecddb44fe459ec446','manifest_sha256':'c0eceda319c4b5be9233f831f79e10849b3fd825f040f6a0e895821168dd851b',
        'submission_report':portable(SUBMIT),'submission_report_sha256':sha(SUBMIT),'transaction':portable(TRANSACTION),'transaction_sha256':sha(TRANSACTION),
        'pay':64,'refund':0,'net':64,'status':'REMOTE_RUNNING_TASK_ID_BOUND_NO_REPLAY'}
    queue['blocked_by'] = 'U02_V5_TASK_LOCAL_REMOTE_RESULT_AND_POST_HARVEST_QA_PENDING; E40_FULL_EPISODE_ASSEMBLY_QA_AND_RELEASE_PENDING'
    queue['next_action'] = f'At 2026-08-14T06:38:00Z query exact U02 V5 task_id {task_id} once; if complete, download once and run mandatory post-harvest video QA before any AgentCut or final assembly.'
    queue['task_lane_scheduler'] = {'path':portable(SCHED),'sha256_pending_after_write':True,'heartbeat_integration':scheduler['heartbeat_integration']}
    write(QUEUE, queue)
    queue = json.loads(QUEUE.read_text()); queue['task_lane_scheduler']['sha256'] = sha(SCHED); queue['task_lane_scheduler'].pop('sha256_pending_after_write', None); write(QUEUE, queue)
    print(json.dumps({'status':'PASS','task_id':task_id,'scheduler_sha256':sha(SCHED),'work_queue_sha256':sha(QUEUE),'authorization_sha256':sha(AUTH),'gross_pay':1511,'refund':128,'net':1383,'remaining':8617}))

if __name__ == '__main__': main()
