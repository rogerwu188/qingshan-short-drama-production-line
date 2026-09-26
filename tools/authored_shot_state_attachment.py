"""Consume versioned, contract-bound authored state ledgers without a legacy episode."""
from copy import deepcopy
from tools.event_boundary_continuity_contract import validate_persistent_state_contract


def apply_authored_states(spec, editorial_by_id, attachment, *, contract_sha256, episode):
    if attachment.get('schema') != 'qingshan.authored_shot_state_attachment.v1':
        raise ValueError('SHOT_STATE_ATTACHMENT_SCHEMA_INVALID')
    if attachment.get('episode') != episode or attachment.get('source_contract_sha256') != contract_sha256:
        raise ValueError('SHOT_STATE_ATTACHMENT_AUTHORITY_MISMATCH')
    records = attachment.get('shots') or []
    rows = {r['shot_id']: r for r in records}
    if len(rows) != len(records) or set(rows) != set(editorial_by_id):
        raise ValueError('SHOT_STATE_ATTACHMENT_COVERAGE_MISMATCH')
    for group in spec['groups']:
        if group.get('shot_state_contracts'):
            raise ValueError('SHOT_STATE_ATTACHMENT_LEGACY_AUTHORITY_CONFLICT')
        states=[]
        for sid in group['editorial_shot_ids']:
            row=deepcopy(rows[sid]); shot=editorial_by_id[sid]
            if not row.get('source_ref') or not row.get('author'):
                raise ValueError('SHOT_STATE_AUTHOR_REQUIRED:'+sid)
            failures=validate_persistent_state_contract({'unit_id':sid,'persistent_state_contract':row.get('persistent_state_contract')})
            if failures: raise ValueError(';'.join(failures))
            cp=shot['prompt_spec']['camera_plan']
            row['camera_state']={key:cp[key] for key in ('shot_scale','lens_intent','motion_family')}
            row['camera_state'].update(camera_position_id=shot['angle_id'],axis_id=shot['axis_id'])
            states.append(row)
        first,last=states[0]['persistent_state_contract'],states[-1]['persistent_state_contract']
        first_chars={r['character_id']:r for r in first['characters']}
        last_chars={r['character_id']:r for r in last['characters']}
        if set(first_chars)!=set(last_chars):
            raise ValueError('SHOT_STATE_ATTACHMENT_GROUP_ROSTER_MISMATCH:'+group['unit_id'])
        envelope=deepcopy(first)
        for row in envelope['characters']:
            row['exit_state']=deepcopy(last_chars[row['character_id']]['exit_state'])
        envelope['environment']['exit_state']=deepcopy(last['environment']['exit_state'])
        if 'props' in first or 'props' in last:
            envelope['props']={
                'entry_state':deepcopy((first.get('props') or {}).get('entry_state',{})),
                'exit_state':deepcopy((last.get('props') or {}).get('exit_state',{})),
            }
        envelope['derivation']='AUTHORED_FIRST_ENTRY_AND_LAST_EXIT_NOT_OBSERVED_MEDIA'
        group['shot_state_contracts']=states
        group['persistent_state_contract']=envelope
        group['state_attachment_source_sha256']=contract_sha256
    return {(r['from_shot_id'],r['to_shot_id']):deepcopy(r)
            for r in attachment.get('internal_transitions') or []}
