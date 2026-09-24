"""Whole-batch prompt preparation barrier, independent of remote media waits.

No generation, automatic QA approval, transaction mutation or model rewriting.
Planned prompt QA is distinct from final exact-reference/provider admission.
"""
import hashlib
import json
import os
from pathlib import Path

ARTIFACTS=('keyframe_prompt','video_prompt','prompt_qa')

def _trusted_roots(root):
    roots=[Path(root).resolve()]
    runtime=os.environ.get('NALU_RUNTIME_ROOT','').strip()
    if runtime: roots.append(Path(runtime).resolve())
    return roots

def _trusted_path(root, value):
    raw=Path(str(value or ''))
    path=(raw if raw.is_absolute() else Path(root)/raw).resolve()
    if not any(path.is_relative_to(base) for base in _trusted_roots(root)):
        return None
    return path

def require_generation_batch(task, root, *, artifact_kind='video_prompt'):
    """Call after bound-transaction recovery, before uploads or new intent.

    Project policy is authoritative; omitting a manifest flag cannot opt out.
    Reusable character assets without an episode are outside episode batches.
    """
    root=Path(root)
    policy_path=root/'workflow/production_line/EPISODE_PROMPT_BATCH_POLICY.json'
    if not policy_path.exists():
        policy_path=root/'configs/EPISODE_PROMPT_BATCH_POLICY.json'
    if not policy_path.exists():
        return {'status':'NOT_REQUIRED','failures':[]}
    policy=json.loads(policy_path.read_text())
    episode=str(task.get('episode') or '')
    if not episode and not str(task.get('task_key','')).startswith('E'):
        return {'status':'NOT_EPISODE_TASK','failures':[]}
    execution=str(task.get('execution_id') or '')
    if not execution:
        for prefix,value in policy.get('task_key_execution_prefixes',{}).items():
            if str(task.get('task_key','')).startswith(prefix):
                execution=value;break
    config=(policy.get('executions') or {}).get(execution)
    if not config:
        raise ValueError('WHOLE_BATCH_PROMPT_QA_REQUIRED:EXECUTION_NOT_REGISTERED')
    uid=task.get('unit_id') or task.get('shot_id')
    uid=(config.get('unit_aliases') or {}).get(uid,uid)
    result=evaluate(root,{**config,'required':True},execution_id=execution,unit_id=uid)
    if result['status']!='PASS':
        raise ValueError('WHOLE_BATCH_PROMPT_QA_REQUIRED:'+','.join(result['failures']))
    report=json.loads((root/config['manifest_ref']).read_text())
    row=next(r for r in report['rows'] if r['unit_id']==uid)
    if row.get('mode') == 'REUSE_EXISTING_MEDIA':
        raise ValueError('WHOLE_BATCH_PROMPT_QA_REQUIRED:REUSE_ROW_CANNOT_GENERATE')
    planned=row[artifact_kind]['sha256']
    actual=task.get('prompt_sha256')
    if actual!=planned:
        # Only an explicitly reviewed late materialization may differ from
        # the batch-approved text (e.g. real-tail reference token binding).
        ref=task.get('prompt_batch_finalization') or {}
        path=_trusted_path(root,ref.get('path',''))
        if path is None or not path.is_file() or digest(path)!=ref.get('sha256'):
            raise ValueError('WHOLE_BATCH_PROMPT_QA_REQUIRED:FINAL_PROMPT_NOT_BOUND_TO_BATCH')
        qa=json.loads(path.read_text())
        expected={'status':'PASS','execution_id':execution,'unit_id':uid,'artifact_kind':artifact_kind,
                  'planned_prompt_sha256':planned,'final_prompt_sha256':actual,
                  'scope':'INCREMENTAL_EXACT_MATERIALIZATION_QA'}
        if not actual or any(qa.get(k)!=v for k,v in expected.items()):
            raise ValueError('WHOLE_BATCH_PROMPT_QA_REQUIRED:FINALIZATION_QA_MISMATCH')
    return result

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _reuse_failures(root, row, execution_id):
    """Validate an existing asset, never grant it a new generation permission.

    Historical admission is retained, not re-labelled as a fresh visual review.
    Repair-context continuity must be reviewed separately against this exact asset.
    """
    uid = row['unit_id']
    parent = row.get('parent_unit_id') or uid
    refs = row.get('reuse_evidence') or {}
    found = {}
    failures = []
    for name in ('media', 'assembly_receipt', 'admission_result', 'continuity_review'):
        ref = refs.get(name) or {}
        path = _trusted_path(root, ref.get('path'))
        if path is None or not path.is_file() or digest(path) != ref.get('sha256'):
            failures.append(f'MISSING_OR_STALE_REUSE_EVIDENCE:{uid}:{name}')
        else:
            found[name] = path
    if not all(name in found for name in ('media', 'assembly_receipt', 'admission_result')):
        return failures
    media_sha = refs['media']['sha256']
    assembly = json.loads(found['assembly_receipt'].read_text())
    admission = json.loads(found['admission_result'].read_text())
    matching_tasks = [t for t in assembly.get('tasks', [])
                      if t.get('source_id') == parent and t.get('sha256') == media_sha
                      and _trusted_path(root, t.get('output_path')) == found['media']
                      and t.get('status') == 'qa_pass']
    if (assembly.get('unit_id') != parent
            or assembly.get('downstream_status') != 'ADMITTED_FOR_ASSEMBLY'
            or len(matching_tasks) != 1
            or _trusted_path(root, assembly.get('admission_result')) != found['admission_result']):
        failures.append(f'REUSE_ASSEMBLY_BINDING_INVALID:{uid}')
    if (admission.get('status') != 'ADMITTED'
            or admission.get('downstream_status') != 'ADMITTED_FOR_ASSEMBLY'
            or admission.get('asset_sha256') != media_sha
            or _trusted_path(root, admission.get('asset_path')) != found['media']
            or admission.get('failures')):
        failures.append(f'REUSE_PRIOR_ADMISSION_INVALID:{uid}')
    if 'continuity_review' not in found:
        return failures
    review = json.loads(found['continuity_review'].read_text())
    expected = {'status': 'PASS', 'execution_id': execution_id, 'unit_id': parent,
                'media_sha256': media_sha, 'scope': 'REPAIR_CONTEXT_CONTINUITY',
                'cross_unit_continuity_checked': True}
    if (any(review.get(k) != v for k, v in expected.items())
            or not review.get('reviewer') or not review.get('observation')):
        failures.append(f'REUSE_CONTEXT_REVIEW_MISSING:{uid}')
    # Bind the review to its actual context inputs, not only to historical media.
    context_refs = review.get('context_refs') or []
    if not context_refs:
        failures.append(f'REUSE_CONTEXT_INPUTS_MISSING:{uid}')
    for ref in context_refs:
        path = _trusted_path(root, ref.get('path'))
        if path is None or not path.is_file() or digest(path) != ref.get('sha256'):
            failures.append(f'REUSE_CONTEXT_INPUT_STALE:{uid}')
    return failures

def evaluate(root, config, *, execution_id, unit_id):
    if not config or not config.get('required'):
        return {'status':'NOT_REQUIRED','failures':[]}
    failures=[]
    scope=config.get('unit_ids') or []
    if not scope or len(scope)!=len(set(scope)):
        failures.append('INVALID_BATCH_SCOPE')
    if unit_id not in scope:
        failures.append('UNIT_OUTSIDE_APPROVED_BATCH_SCOPE')
    rows=[]
    try:
        report=json.loads((Path(root)/config['manifest_ref']).read_text())
        if report.get('execution_id')!=execution_id:failures.append('BATCH_EXECUTION_MISMATCH')
        rows=report['rows']
        ids=[r['unit_id'] for r in rows]
        if len(ids)!=len(set(ids)) or set(ids)!=set(scope):failures.append('INCOMPLETE_OR_DUPLICATE_BATCH')
        for row in rows:
            uid=row['unit_id'];found={}
            if row.get('mode') == 'REUSE_EXISTING_MEDIA':
                failures.extend(_reuse_failures(root, row, execution_id))
                continue
            if row.get('mode', 'GENERATE') != 'GENERATE':
                failures.append(f'UNKNOWN_BATCH_ROW_MODE:{uid}')
                continue
            for name in ARTIFACTS:
                ref=row.get(name) or {}
                path=_trusted_path(root, ref.get('path',''))
                if path is None:
                    failures.append(f'ARTIFACT_OUTSIDE_PROJECT:{uid}:{name}');continue
                if not path.is_file() or not ref.get('sha256') or digest(path)!=ref['sha256']:
                    failures.append(f'MISSING_OR_STALE_ARTIFACT:{uid}:{name}');continue
                found[name]=path
            if len(found)!=len(ARTIFACTS):continue
            qa=json.loads(found['prompt_qa'].read_text())
            if qa.get('status')!='PASS' or qa.get('unit_id')!=uid or qa.get('execution_id')!=execution_id:
                failures.append(f'PROMPT_QA_NOT_PASS:{uid}')
            for name in ('keyframe_prompt','video_prompt'):
                if qa.get(name+'_sha256')!=row[name]['sha256']:
                    failures.append(f'QA_INPUT_MISMATCH:{uid}:{name}')
            # A future real frame may be unresolved, but never represented as
            # observed. Its immutable identity is checked at exact submission.
            if qa.get('scope')!='PLANNED_PROMPTS_AND_CROSS_UNIT_CONTINUITY':
                failures.append(f'QA_SCOPE_MISSING:{uid}')
            if not qa.get('cross_unit_continuity_checked'):
                failures.append(f'CROSS_UNIT_QA_MISSING:{uid}')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        failures.append('BATCH_EVIDENCE_UNAVAILABLE:'+type(exc).__name__)
    return {'status':'PASS' if not failures else 'HOLD','failures':failures,
            'prepared_scope_count':len(rows),'required_scope_count':len(scope),
            'preparation_allowed':True,'not_final_reference_admission':True}
