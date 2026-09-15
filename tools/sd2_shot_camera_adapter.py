"""Explicit SD2 per-shot camera transport; never invent a unit-wide camera."""
from copy import deepcopy
from tools.grouped_camera_contract import compile_camera_prompt
from tools.camera_language_selector import select_camera_language


def compile_shot_cameras(unit, unit_class):
    if unit.get('camera_scope_policy') != 'PER_SHOT_EXPLICIT':
        return []
    if unit.get('model') != 'seedance-2.0-pro':
        raise ValueError('PER_SHOT_CAMERA_SD2_ONLY')
    if unit.get('camera_plan'):
        raise ValueError('UNIT_AND_SHOT_CAMERA_AUTHORITY_CONFLICT')
    specs = unit.get('ordered_prompt_specs') or []
    ids = [s.get('shot_id') for s in specs]
    if not ids or not all(ids) or len(set(ids)) != len(ids):
        raise ValueError('SHOT_CAMERA_IDS_INVALID')
    rows = []
    for spec in specs:
        plan, receipt = select_camera_language(
            deepcopy(spec.get('camera_plan') or {}), unit_class=unit_class,
            unit=unit, source_id=spec['shot_id'])
        clause = compile_camera_prompt(plan, source_id=spec['shot_id'])
        action = spec.get('action') or {}
        start, end = action.get('t0_seconds'), action.get('t1_seconds')
        if start is None or end is None or not 0 <= start < end <= unit['duration_seconds']:
            raise ValueError('SHOT_CAMERA_TIME_INVALID:' + spec['shot_id'])
        rows.append({'shot_id': spec['shot_id'], 'start_seconds': start,
                     'end_seconds': end, 'camera_plan': plan,
                     'selection_receipt': receipt, 'clause': clause})
    return rows


def render_shot_cameras(rows):
    return '\n'.join(
        f"仅分镜{r['shot_id']}（{r['start_seconds']:g}–{r['end_seconds']:g}秒）适用：{r['clause']}"
        for r in rows)
