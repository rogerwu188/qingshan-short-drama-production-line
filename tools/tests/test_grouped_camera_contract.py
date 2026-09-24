import copy
import unittest

from tools.grouped_camera_contract import (
    compile_camera_prompt,
    validate_camera_plan,
    validate_camera_sequence,
)


def track(direction="LEFT_TO_RIGHT"):
    return {
        "shot_scale": "MEDIUM_WIDE", "lens_intent": "35mm交代行进空间",
        "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
        "axis_relation": "保持既定人物视线轴，不越轴",
        "motion_family": "TRACK", "motion_direction": direction,
        "start_framing": "人物进入通道", "end_framing": "人物抵达门边",
        "motivation": "只为保持人物真实行进及其空间终点连续可读",
    }


class GroupedCameraContractTest(unittest.TestCase):
    def test_episode_camera_times_are_rebased_without_stretch_or_mutation(self):
        from tools.sd2_shot_camera_adapter import compile_shot_cameras
        from tools.sd2_provider_prompt_renderer import scoped_camera_prompt
        unit = {'unit_id': 'U1', 'model': 'seedance-2.0-pro', 'duration_seconds': 5,
                'camera_scope_policy': 'PER_SHOT_EXPLICIT', 'camera_time_coordinate': 'EPISODE',
                'ordered_prompt_specs': [
                    {'shot_id': 'S1', 'camera_plan': track(),
                     'action': {'t0_seconds': 31.6, 't1_seconds': 34.0}},
                    {'shot_id': 'S2', 'camera_plan': track('RIGHT_TO_LEFT'),
                     'action': {'t0_seconds': 34.0, 't1_seconds': 36.2}}]}
        before = copy.deepcopy(unit)
        rows = compile_shot_cameras(unit, 'DIALOGUE')
        self.assertEqual(unit, before)
        self.assertEqual([(r['start_seconds'], r['end_seconds']) for r in rows], [(0, 2.4), (2.4, 4.6)])
        prompt = scoped_camera_prompt({'unit_id': 'U1', 'camera_scope_policy': 'PER_SHOT_EXPLICIT',
                                       'per_shot_camera_plans': rows, 'beats': [{}, {}]})
        self.assertIn('仅分镜S1（0–2.4秒）', prompt)
        self.assertIn('仅分镜S2（2.4–4.6秒）', prompt)
        self.assertIn('左向右', prompt)
        self.assertIn('右向左', prompt)

    def test_per_shot_camera_sequence_uses_actual_order_without_unit_camera(self):
        unit = {"unit_id":"U1", "model":"seedance-2.0-pro", "duration_seconds":4,
                "camera_scope_policy":"PER_SHOT_EXPLICIT", "ordered_prompt_specs":[
                    {"shot_id":"S1", "camera_plan":track(),
                     "action":{"t0_seconds":0,"t1_seconds":2}},
                    {"shot_id":"S2", "camera_plan":track("RIGHT_TO_LEFT"),
                     "action":{"t0_seconds":2,"t1_seconds":4}}]}
        before=copy.deepcopy(unit)
        validate_camera_sequence([unit])
        self.assertEqual(unit,before)
        unit['ordered_prompt_specs'][1]['camera_plan']=track()
        with self.assertRaisesRegex(ValueError,'repeat camera motion'):
            validate_camera_sequence([unit])
        unit['ordered_prompt_specs'][1]['camera_plan']={}
        with self.assertRaises(ValueError):
            validate_camera_sequence([unit])

    def test_paid_projection_preserves_source_camera_and_timing_policy(self):
        from tools.submit_giggle_video_manifest_v2 import grouped_sequence_unit
        source={'camera_scope_policy':'PER_SHOT_EXPLICIT', 'camera_time_coordinate':'EPISODE',
                'camera_plan': {},
                'timeline_policy':'PRESERVE_AUTHORED_NO_STRETCH'}
        task={'machine_contract':source}
        projected=grouped_sequence_unit(task)
        for key,value in source.items():self.assertEqual(projected[key],value)
        task['camera_scope_policy']='UNIT_WIDE'
        with self.assertRaisesRegex(ValueError,'SOURCE_POLICY_TRANSPORT_MISMATCH'):
            grouped_sequence_unit(task)

    def test_compiles_explicit_direction_and_single_move_rule(self):
        text = compile_camera_prompt(track(), source_id="U1")
        self.assertIn("由画面左向右", text)
        self.assertIn("禁止反向复位或重复运动", text)

    def test_rejects_generic_follow_action_language(self):
        plan = track()
        plan["motivation"] = "镜头随主要动作平稳调整景别"
        with self.assertRaisesRegex(ValueError, "generic camera language"):
            validate_camera_plan(plan, source_id="U1")

    def test_rejects_adjacent_same_direction(self):
        units = [
            {"unit_id": "U1", "camera_plan": track()},
            {"unit_id": "U2", "camera_plan": copy.deepcopy(track())},
        ]
        with self.assertRaisesRegex(ValueError, "repeat camera motion"):
            validate_camera_sequence(units)

    def test_compiles_optional_camera_language_without_replacing_geometry(self):
        plan = track()
        plan.update({
            "lens_mm": 35,
            "shutter_visual_intent": "CRISP_ACTION_DIRECTION",
            "depth_of_field_intent": "DEEP_SPATIAL_READABILITY",
            "camera_profile_id": "CAM-COMBAT-IMPULSE-CLEAR-V1",
        })
        text = compile_camera_prompt(plan, source_id="U1")
        self.assertIn("估算35mm焦段", text)
        self.assertIn("接触瞬间", text)
        self.assertIn("空间关系同时可读", text)
        self.assertIn("由画面左向右", text)


if __name__ == "__main__":
    unittest.main()
