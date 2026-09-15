from copy import deepcopy
import unittest
from tools.tests.test_shared_video_execution_compiler import _unit
from tools.sd2_shot_camera_adapter import compile_shot_cameras, render_shot_cameras
from tools.video_prompt_compiler import compile_model_prompt


class ShotCameraTests(unittest.TestCase):
    def make_unit(self):
        u = _unit()
        p = u.pop('camera_plan')
        u['camera_scope_policy'] = 'PER_SHOT_EXPLICIT'
        s = u['ordered_prompt_specs'][0]
        s['shot_id'] = 'shot-one'
        s['camera_plan'] = p
        s['action'].update(t0_seconds=0, t1_seconds=4)
        return u

    def test_scoped_render_and_real_compile(self):
        u = self.make_unit(); before = deepcopy(u)
        rows = compile_shot_cameras(u, 'COMBAT_IMPULSE')
        self.assertIn('仅分镜shot-one（0–4秒）适用', render_shot_cameras(rows))
        text = compile_model_prompt(u, preproduction_only=True)
        self.assertIn('仅分镜shot-one', text)
        self.assertEqual(u, before)

    def test_reject_missing_camera_and_conflicting_authority(self):
        u = self.make_unit()
        u['camera_plan'] = deepcopy(u['ordered_prompt_specs'][0]['camera_plan'])
        with self.assertRaisesRegex(ValueError, 'AUTHORITY_CONFLICT'):
            compile_shot_cameras(u, 'COMBAT_IMPULSE')
        u.pop('camera_plan'); u['ordered_prompt_specs'][0].pop('camera_plan')
        with self.assertRaises(ValueError):
            compile_shot_cameras(u, 'COMBAT_IMPULSE')

    def test_h3_not_silently_supported(self):
        u = self.make_unit(); u['model'] = 'minimax-h3'
        with self.assertRaisesRegex(ValueError, 'SD2_ONLY'):
            compile_shot_cameras(u, 'COMBAT_IMPULSE')


if __name__ == '__main__':
    unittest.main()
