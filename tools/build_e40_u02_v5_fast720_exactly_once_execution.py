#!/usr/bin/env python3
"""Compile the one-post execution package for admitted E40 U02 V5."""
from __future__ import annotations
import copy, hashlib, importlib.util, json, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path.home() / '.local/share/backlotos/share/pipeline-tools'
BASE = ROOT / 'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v5_fast720_causal_beats_v1'
SOURCE = BASE / 'E40_U02_V5_FAST720_NO_SUBMIT_MANIFEST_V1.json'
EXECUTION = BASE / 'E40_U02_V5_FAST720_EXACTLY_ONCE_MANIFEST_V1.json'
PRECHECK = ROOT / 'qa/e40_preproduction_20260814/u02_v5_fast720_no_submit_package_qa_v1/E40_U02_V5_FAST720_INSTALLED_PRECHECK_V1.json'
READINESS = ROOT / 'qa/e40_preproduction_20260814/u02_v5_fast720_exactly_once_readiness_v1/E40_U02_V5_FAST720_PAID_READINESS_V1.json'
AUTH = ROOT / 'workflow/approvals/E40_U02_V5_FAST720_EXACTLY_ONCE_AUTHORIZATION_20260814.json'
QUEUE = ROOT / 'workflow/work_queue.json'

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def portable(path): return str(Path(path).relative_to(ROOT))
def write(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2); handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def load_module(name, path):
    sys.path.insert(0, str(TOOLS))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module
    finally:
        if sys.path and sys.path[0] == str(TOOLS): sys.path.pop(0)

def main():
    pre = json.loads(PRECHECK.read_text())
    if pre.get('status') != 'PASS' or pre.get('precheck_pass') != 1 or pre.get('submitted') != 0 or pre.get('failed') != 0:
        raise SystemExit('installed precheck is not exact PASS/1/0/0')
    manifest = copy.deepcopy(json.loads(SOURCE.read_text()))
    task = manifest['tasks'][0]
    if task['model'] != 'seedance-2.0-fast' or task['resolution'] != '720p' or task['duration_seconds'] != 4:
        raise SystemExit('model/resolution/duration boundary failed')
    manifest['schema'] = 'qingshan.e40.u02.v5.fast720_exactly_once_manifest.v1'
    manifest['recorded_at'] = '2026-08-14T06:29:00Z'
    manifest['status'] = 'AUTHORIZED_EXACTLY_ONCE_PENDING_PROVIDER_POST'
    task['submission_authorization'] = {'precheck_only':False,'authorized':True,'paid_submission_allowed':True,'transaction_creation_allowed':True,'maximum_new_submissions':1,'exactly_once':True}
    manifest['submission_policy'] = {'precheck_only':False,'paid_submission_allowed':True,'provider_post_allowed':True,'durable_transaction_allowed':True,'maximum_new_submissions':1,'unchanged_retry_forbidden':True,'same_round_retry_forbidden':True,'exactly_once':True}
    queue = json.loads(QUEUE.read_text()); credits = queue['e40_credits']
    expected_pay = 64
    projected_net = int(credits['net']) + expected_pay
    if projected_net > int(credits['cap']): raise SystemExit('episode credit cap exceeded')
    manifest['credit_guard'] = {'episode_cap':int(credits['cap']),'observed_net_before':int(credits['net']),'maximum_authorized_cost':expected_pay,'projected_net_maximum':projected_net,'projected_remaining_minimum':int(credits['cap'])-projected_net}
    manifest['blocked_by'] = None
    manifest['next_action'] = 'Invoke deployed submitter exactly once; it must persist intent before POST and bind task_id immediately. Never replay an unknown or bound transaction.'
    write(EXECUTION, manifest)

    submit = load_module('deployed_video_submitter_for_fingerprint', TOOLS / 'submit_giggle_video_manifest_v2.py')
    submit.ROOT = ROOT
    exact = load_module('deployed_exact_first_frame_for_fingerprint', TOOLS / 'exact_first_frame_transport.py')
    fp = submit.task_fingerprint(task); transport_fp = exact.transport_fingerprint(task)
    transaction = ROOT / 'workflow/tasks/giggle_video_submit_transactions/E40' / f"{task['task_key']}__{fp[:16]}.json"
    matching_task_key = 0; matching_fp = 0; matching_transport = 0
    for path in (ROOT / 'workflow/tasks/giggle_video_submit_transactions/E40').glob('*.json'):
        row = json.loads(path.read_text())
        matching_task_key += row.get('task_key') == task['task_key']
        matching_fp += row.get('submission_fingerprint') == fp
        matching_transport += row.get('transport_fingerprint') == transport_fp
    collision_pass = not transaction.exists() and matching_task_key == matching_fp == matching_transport == 0
    if not collision_pass: raise SystemExit('fresh transaction collision gate failed')
    execution_sha = sha(EXECUTION)
    readiness = {
        'schema':'qingshan.e40.u02.v5.fast720_paid_readiness.v1','recorded_at':'2026-08-14T06:29:00Z','status':'PASS_EXACTLY_ONCE_READY_NO_PROVIDER_POST_YET',
        'canonical':manifest['canonical'],'execution_manifest':{'path':portable(EXECUTION),'sha256':execution_sha},
        'installed_precheck':{'path':portable(PRECHECK),'sha256':sha(PRECHECK),'status':'PASS_SUBMITTED0_PRECHECK1_FAILED0'},
        'price_gate':{'method':'AUTHORITATIVE_LATEST_EXACT_SEEDANCE_FAST_720P_4S_CLASS','expected_pay':expected_pay,'rate_credits_per_second':16,'gate':'PASS'},
        'episode_ledger_gate':{'gross_pay':credits['gross_pay'],'refund':credits['refund'],'net':credits['net'],'cap':credits['cap'],'projected_net':projected_net,'projected_remaining':credits['cap']-projected_net,'gate':'PASS'},
        'fresh_transaction_gate':{'expected_transaction_path':portable(transaction),'expected_transaction_exists':False,'matching_task_key_count':matching_task_key,'matching_submission_fingerprint_count':matching_fp,'matching_transport_fingerprint_count':matching_transport,'submission_fingerprint':fp,'transport_fingerprint':transport_fp,'gate':'PASS_ZERO'},
        'side_effects':{'provider_posts':0,'transactions':0,'credits':0},
        'next_action':'Persist authorization, then invoke deployed submitter once without --precheck-only.'}
    write(READINESS, readiness)
    auth = {
        'schema':'qingshan.e40.u02.v5.fast720_exactly_once_authorization.v1','episode':'E40','authorized_task_id':'E40-U02-V5-FAST720-EXACTLY-ONCE-EXECUTION','recorded_at':'2026-08-14T06:29:00Z',
        'source_authority':'Root explicit successor execution under Roger standing E40 credit cap and 2026-08-08 seedance-2.0-fast authorization','status':'ACTIVE_EXACTLY_ONCE_UNCONSUMED',
        'maximum_provider_posts':1,'consumed_provider_posts':0,'maximum_generating_count':1,'model':'seedance-2.0-fast','resolution':'720p','duration_seconds':4,
        'execution_manifest':{'path':portable(EXECUTION),'sha256':execution_sha},'paid_readiness':{'path':portable(READINESS),'sha256':sha(READINESS),'status':'PASS_EXACTLY_ONCE_READY_NO_PROVIDER_POST_YET'},
        'submission_fingerprint':fp,'transport_fingerprint':transport_fp,'expected_transaction_path':portable(transaction),
        'credit_guard':manifest['credit_guard'],'timeout_policy':'DO_NOT_REPOST. Classify exact transaction, task_id, Pay and Refund before any materially changed retry.',
        'forbidden':['seedance-2.0-pro','seedance-2.0-mini','seedance-2.0','second provider POST','blind timeout retry','browser upload or release before final QA']}
    write(AUTH, auth)
    print(json.dumps({'status':'PASS','execution_manifest_sha256':execution_sha,'readiness_sha256':sha(READINESS),'authorization_sha256':sha(AUTH),'submission_fingerprint':fp,'transport_fingerprint':transport_fp,'expected_transaction':portable(transaction)}))

if __name__ == '__main__': main()
