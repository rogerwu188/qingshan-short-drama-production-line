import unittest
from tools.video_execution_plan_compiler import _content_timeline_duration, _timeline
from tools.sd2_motion_density_gate import validate_execution_plan


class ContentWindowTimelineTest(unittest.TestCase):
    def test_explicit_window_does_not_stretch_into_padding(self):
        specs = [{'action': {'t0_seconds': 0, 't1_seconds': x}} for x in (2.4, 2.5, 2.4)]
        duration = _content_timeline_duration({'authorized_content_seconds': 7.3}, 8)
        self.assertEqual(_timeline(specs, duration), [(0, 2.4), (2.4, 4.9), (4.9, 7.3)])

    def test_legacy_without_explicit_window_unchanged(self):
        self.assertEqual(_content_timeline_duration({}, 8), 8)

    def test_invalid_window_rejected_instead_of_silently_compressed(self):
        for value in (0, -1, 8.1, float('nan')):
            with self.assertRaises(ValueError):
                _content_timeline_duration({'authorized_content_seconds': value}, 8)

    def test_gate_uses_explicit_content_end_not_provider_end(self):
        plan = {'unit_id':'test', 'duration_seconds':8,
                'duration_authority':{'action_timeline_seconds':7.3, 'authorized_content_seconds':7.3},
                'beats':[{'start_seconds':0,'end_seconds':7.3}]}
        # Unrelated state-delta checks may fail; this test isolates duration validation.
        errors = validate_execution_plan(plan)['failures']
        self.assertFalse(any('EXECUTION_DURATION_MISMATCH' in e for e in errors), errors)
        plan['duration_authority']['authorized_content_seconds'] = 7
        self.assertTrue(any('CONTENT_AUTHORITY_MISMATCH' in e for e in validate_execution_plan(plan)['failures']))


if __name__ == '__main__':
    unittest.main()
