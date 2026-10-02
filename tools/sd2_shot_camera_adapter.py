"""Explicit SD2 per-shot camera transport; never invent a unit-wide camera."""
from copy import deepcopy
from tools.grouped_camera_contract import compile_camera_prompt
from tools.camera_language_selector import select_camera_language

# compile_camera_prompt words a LOCKED plan for a whole unit ("全段锁定机位").  Inside a
# per-shot row that would claim the other shots' windows too, so it is scoped to the shot.
_UNIT_LOCKED = '全段锁定机位'
_SHOT_LOCKED = '本分镜锁定机位'


def scope_grouping_plan_cameras(plan, *, episode, model, policy=None):
    """Opt a grouping plan's multi-shot units into the per-shot camera path.

    Gated by tools.prompt_shot_scope_policy.active_for(episode, model); an inactive
    episode is returned untouched so its compiled bytes cannot change.  Single-shot units
    keep the legacy unit camera (one shot == one camera line already).  Returns the ids
    of the units that were scoped.
    """
    from tools.prompt_shot_scope_policy import active_for
    if not active_for(episode, model, policy=policy):
        return []
    scoped = []
    for unit in plan.get('units') or []:
        if len(unit.get('editorial_shot_ids') or []) < 2:
            continue
        # compile_grouped_seedance_manifest reads these two fields; prompt_spec action
        # windows are episode-absolute, hence the EPISODE time coordinate.
        unit['camera_scope_policy'] = 'PER_SHOT_EXPLICIT'
        unit['camera_time_coordinate'] = 'EPISODE'
        scoped.append(str(unit.get('unit_id')))
    return scoped


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
    origin = (float((specs[0].get('action') or {}).get('t0_seconds', 0))
              if unit.get('camera_time_coordinate') == 'EPISODE' else 0.0)
    for spec in specs:
        plan, receipt = select_camera_language(
            deepcopy(spec.get('camera_plan') or {}), unit_class=unit_class,
            unit=unit, source_id=spec['shot_id'])
        clause = compile_camera_prompt(plan, source_id=spec['shot_id'])
        if plan['motion_family'] == 'LOCKED':
            clause = clause.replace(_UNIT_LOCKED, _SHOT_LOCKED)
        action = spec.get('action') or {}
        start, end = action.get('t0_seconds'), action.get('t1_seconds')
        if start is not None and end is not None:
            start, end = round(float(start) - origin, 6), round(float(end) - origin, 6)
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
