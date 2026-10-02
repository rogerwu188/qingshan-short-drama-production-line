"""Shot-scope upgrade: per-shot SD2 camera lines, gated by PROMPT_SHOT_SCOPE_POLICY (synthetic fixtures)."""
from copy import deepcopy
import unittest

from tools.grouped_camera_contract import compile_camera_prompt, validate_camera_sequence
from tools.grouped_transition_contract import _boundary_camera
from tools.sd2_provider_prompt_renderer import scoped_camera_prompt
from tools.sd2_shot_camera_adapter import compile_shot_cameras, scope_grouping_plan_cameras

MODEL = 'seedance-2.0-pro'
POLICY = {'lines': {'demo': {'models': [MODEL], 'active_from_episode': 11}}}


def camera(family='PAN', direction='LEFT_TO_RIGHT', start='起幅：甲站在门边', end='落幅：甲走到桌前',
           axis='甲在画左；室内，绝无户外景', scale='MEDIUM', height='EYE_LEVEL', side='AXIS_A'):
    return {'shot_scale': scale, 'camera_height': height, 'camera_side': side,
            'motion_family': family, 'motion_direction': direction,
            'lens_intent': '35mm保留人物与门框关系', 'axis_relation': axis,
            'start_framing': start, 'end_framing': end,
            'motivation': '跟随甲走向桌前的位移', 'selection_mode': 'LOCKED'}


def shot_unit(*cameras, t0=40.0):
    specs, clock = [], t0
    for index, plan in enumerate(cameras, 1):
        specs.append({'shot_id': f'S{index}', 'camera_plan': plan,
                      'action': {'t0_seconds': clock, 't1_seconds': clock + 2}})
        clock += 2
    return {'unit_id': 'EX-VU-001', 'model': MODEL, 'duration_seconds': 2 * len(cameras),
            'camera_scope_policy': 'PER_SHOT_EXPLICIT', 'camera_time_coordinate': 'EPISODE',
            'ordered_prompt_specs': specs}


def grouping_plan():
    return {'units': [
        {'unit_id': 'EX-VU-001', 'editorial_shot_ids': ['S1', 'S2'], 'camera_plan': camera()},
        {'unit_id': 'EX-VU-002', 'editorial_shot_ids': ['S3'], 'camera_plan': camera()},
    ]}


def render(unit):
    rows = compile_shot_cameras(unit, 'DIALOGUE')
    return scoped_camera_prompt({'unit_id': unit['unit_id'], 'camera_scope_policy': 'PER_SHOT_EXPLICIT',
                                 'per_shot_camera_plans': rows,
                                 'beats': [{} for _ in unit['ordered_prompt_specs']]})


class GateTests(unittest.TestCase):
    def test_gate_off_leaves_plan_and_legacy_camera_line_unchanged(self):
        plan = grouping_plan()
        before = deepcopy(plan)
        self.assertEqual(scope_grouping_plan_cameras(plan, episode='E10', model=MODEL, policy=POLICY), [])
        self.assertEqual(scope_grouping_plan_cameras(plan, episode='E40', model='other-model', policy=POLICY), [])
        self.assertEqual(scope_grouping_plan_cameras(plan, episode='E40', model=MODEL, policy={}), [])
        self.assertEqual(plan, before)
        legacy = {'unit_id': 'EX-VU-001', 'camera_plan': camera(), 'beats': [{}, {}]}
        self.assertEqual(scoped_camera_prompt(legacy), compile_camera_prompt(camera(), source_id='EX-VU-001'))

    def test_gate_on_scopes_only_multi_shot_units(self):
        plan = grouping_plan()
        self.assertEqual(scope_grouping_plan_cameras(plan, episode='E11', model=MODEL, policy=POLICY),
                         ['EX-VU-001'])
        multi, single = plan['units']
        self.assertEqual((multi['camera_scope_policy'], multi['camera_time_coordinate']),
                         ('PER_SHOT_EXPLICIT', 'EPISODE'))
        self.assertNotIn('camera_scope_policy', single)


class RenderTests(unittest.TestCase):
    def test_each_shot_line_carries_framing_axis_and_its_own_window(self):
        second = camera('DOLLY', 'PUSH_IN', start='起幅：乙坐在桌后', end='落幅：乙抬头的近景',
                        axis='乙在画右；乙只穿浅色布袍，没有毛领', scale='MEDIUM_CLOSE_UP',
                        height='LOW', side='AXIS_B')
        lines = render(shot_unit(camera(), second)).splitlines()
        self.assertEqual(len(lines), 3)
        first_line, second_line = lines[1], lines[2]
        self.assertTrue(first_line.startswith('仅分镜S1（0–2秒）适用：'))
        self.assertTrue(second_line.startswith('仅分镜S2（2–4秒）适用：'))
        for text in ('景别中景', '平视', '轴线A侧', '甲在画左；室内，绝无户外景',
                     '起始起幅：甲站在门边', '结束落幅：甲走到桌前', '摇镜', '由画面左向右'):
            self.assertIn(text, first_line)
        for text in ('景别中近景', '低机位', '轴线B侧', '乙只穿浅色布袍，没有毛领',
                     '起始起幅：乙坐在桌后', '结束落幅：乙抬头的近景', '轨道推拉', '向主体推进'):
            self.assertIn(text, second_line)
        self.assertNotIn('甲在画左', second_line)

    def test_locked_shot_says_locked_and_never_move_once(self):
        locked = camera('LOCKED', 'NONE', start='固定：乙坐在桌后', end='固定：乙坐在桌后')
        line = render(shot_unit(camera(), locked)).splitlines()[2]
        self.assertIn('本分镜锁定机位', line)
        for forbidden in ('仅执行一次', '全段', '由画面', '推进'):
            self.assertNotIn(forbidden, line)

    def test_camera_and_beat_count_mismatch_fails_closed(self):
        rows = compile_shot_cameras(shot_unit(camera(), camera('DOLLY', 'PUSH_IN', end='落幅：近景')), 'DIALOGUE')
        for cameras, beats in ((rows, [{}]), (rows[:1], [{}, {}]), ([], [{}])):
            with self.assertRaisesRegex(ValueError, 'PER_SHOT_CAMERA_BEAT_COUNT_MISMATCH'):
                scoped_camera_prompt({'unit_id': 'EX-VU-001', 'camera_scope_policy': 'PER_SHOT_EXPLICIT',
                                      'per_shot_camera_plans': cameras, 'beats': beats})


class SequenceTests(unittest.TestCase):
    def test_adjacent_shots_still_may_not_repeat_direction(self):
        unit = shot_unit(camera(), camera('TRACK', 'LEFT_TO_RIGHT', end='落幅：横移到桌前'))
        with self.assertRaisesRegex(ValueError, 'repeat camera direction'):
            validate_camera_sequence([unit])

    def test_five_unit_window_counts_units_not_inner_shots(self):
        push = lambda: camera('DOLLY', 'PUSH_IN', end='落幅：近景')
        units = []
        for index in range(3):
            unit = shot_unit(camera('PAN', 'LEFT_TO_RIGHT' if index % 2 == 0 else 'RIGHT_TO_LEFT'), push())
            unit['unit_id'] = f'EX-VU-00{index + 1}'
            for spec in unit['ordered_prompt_specs']:
                spec['shot_id'] = f"{unit['unit_id']}-{spec['shot_id']}"
            units.append(unit)
        validate_camera_sequence(deepcopy(units))  # three inner PUSH_IN shots, three units
        legacy = [{'unit_id': f'L{i}', 'camera_plan': push() if i % 2 == 0 else camera()} for i in range(5)]
        with self.assertRaisesRegex(ValueError, 'more than twice in five units'):
            validate_camera_sequence(legacy)

    def test_transition_boundary_uses_first_shot_camera_of_per_shot_unit(self):
        unit = shot_unit(camera(), camera('DOLLY', 'PUSH_IN', end='落幅：近景'))
        unit['camera_plan'] = {}
        self.assertEqual(_boundary_camera(unit), unit['ordered_prompt_specs'][0]['camera_plan'])
        self.assertEqual(_boundary_camera({'camera_plan': camera(side='AXIS_B')})['camera_side'], 'AXIS_B')


if __name__ == '__main__':
    unittest.main()
