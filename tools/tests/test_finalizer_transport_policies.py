"""Finalization must not lose source camera/time policies before submission."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools'))
from build_nalu_preproduction import _copy_compiled_transport_policies
from tools.submit_giggle_video_manifest_v2 import grouped_sequence_unit


class FinalizerTransportPoliciesTest(unittest.TestCase):
    def test_submission_validates_each_shot_instead_of_empty_unit_camera(self):
        from tools.submit_giggle_video_manifest_v2 import validate_submission_camera
        from tools.tests.test_grouped_camera_contract import track
        task = {'model': 'seedance-2.0-pro', 'duration_seconds': 4,
                'machine_contract': {'camera_scope_policy': 'PER_SHOT_EXPLICIT',
                    'camera_plan': {}, 'ordered_prompt_specs': [
                        {'shot_id': 'S1', 'camera_plan': track(),
                         'action': {'t0_seconds': 0, 't1_seconds': 4}}]}}
        self.assertEqual(validate_submission_camera(task), {})
        task['machine_contract']['ordered_prompt_specs'][0]['camera_plan'] = {}
        with self.assertRaises(ValueError):
            validate_submission_camera(task)

    def test_explicit_policies_survive_paid_projection(self):
        compiled = {'camera_scope_policy': 'PER_SHOT_EXPLICIT',
                    'camera_time_coordinate': 'EPISODE',
                    'timeline_policy': 'PRESERVE_AUTHORED_NO_STRETCH'}
        before = copy.deepcopy(compiled)
        machine = {'camera_plan': {}}
        _copy_compiled_transport_policies(machine, compiled)
        projected = grouped_sequence_unit({'machine_contract': machine})
        for key, value in compiled.items():
            self.assertEqual(projected[key], value)
        self.assertEqual(projected['camera_plan'], {})
        self.assertEqual(compiled, before)

    def test_legacy_source_does_not_gain_policy_defaults(self):
        machine = {'camera_plan': {'motion_family': 'PAN'}}
        before = copy.deepcopy(machine)
        _copy_compiled_transport_policies(machine, {})
        self.assertEqual(machine, before)

    def test_removed_source_policy_cannot_leak_from_old_task(self):
        machine = {'camera_scope_policy': 'PER_SHOT_EXPLICIT',
                   'camera_time_coordinate': 'EPISODE', 'timeline_policy': 'OLD'}
        _copy_compiled_transport_policies(machine, {})
        self.assertEqual(machine, {})


if __name__ == '__main__':
    unittest.main()
