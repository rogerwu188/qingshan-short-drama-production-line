import unittest
from tools.global_space_layout_gate import evaluate_batch, requires_space_map


class AuthorityOnlyTests(unittest.TestCase):
    def test_explicit_requirement_runs_on_empty_late_episode(self):
        self.assertTrue(requires_space_map('E60', [], True))
        result = evaluate_batch({}, [], episode='E60', required=True)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['failures'])

    def test_late_shot_cannot_opt_out(self):
        self.assertTrue(requires_space_map('E60', [{'stage':'VIDEO_GENERATION'}], False))

    def test_unrequested_empty_batch_keeps_legacy_behavior(self):
        self.assertFalse(requires_space_map('E60', [], None))

if __name__ == '__main__': unittest.main()
