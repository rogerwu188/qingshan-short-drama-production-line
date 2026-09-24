"""Validate reviewed entry-time excerpts without changing scene authority."""
import hashlib
import json
from pathlib import Path

def validate_projection(ref, *, shot, scene, prompt_text):
    path=Path(ref['path'])
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ref.get('sha256'):
        raise ValueError('SCENE_PROJECTION_SHA_MISMATCH')
    data=json.loads(raw)
    if data.get('schema')!='qingshan.reviewed_entry_scene_projection.v1':
        raise ValueError('SCENE_PROJECTION_SCHEMA_INVALID')
    if data.get('shot_id')!=shot['shot_id'] or data.get('scene_id')!=shot['scene_id']:
        raise ValueError('SCENE_PROJECTION_SCOPE_MISMATCH')
    if data.get('entry_state')!=shot['entry_state']:
        raise ValueError('SCENE_PROJECTION_ENTRY_CHANGED')
    if data.get('prompt_sha256')!=hashlib.sha256(prompt_text.encode()).hexdigest():
        raise ValueError('SCENE_PROJECTION_PROMPT_CHANGED')
    if not all(data.get(k) for k in ('reviewer','reviewed_at','reason')) or data.get('review_status')!='PASS':
        raise ValueError('SCENE_PROJECTION_REVIEW_MISSING')
    source=data.get('source_fields',{})
    if source!={k:scene[k] for k in ('time_id','weather','lighting')}:
        raise ValueError('SCENE_PROJECTION_SOURCE_CHANGED')
    projected=data.get('entry_fields',{})
    if set(projected)!={'weather','lighting'}:
        raise ValueError('SCENE_PROJECTION_FIELDS_INVALID')
    for key,value in projected.items():
        # A projection selects existing authored content, never invents weather
        # or illumination. Temporal meaning still needs the explicit review.
        if not isinstance(value,str) or not value.strip() or value not in source[key]:
            raise ValueError('SCENE_PROJECTION_NOT_AUTHORED_EXCERPT')
        if value not in prompt_text:
            raise ValueError('SCENE_PROJECTION_NOT_IN_PROMPT')
    return projected
