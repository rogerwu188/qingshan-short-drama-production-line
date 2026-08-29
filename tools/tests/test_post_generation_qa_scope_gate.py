import unittest

from tools.post_generation_qa_scope_gate import evaluate


class PostGenerationQaScopeGateTest(unittest.TestCase):
    def test_allows_technical_and_basic_plot_checks(self):
        report = evaluate(["decode", "aspect_ratio", "audio_stream", "major_event_presence"])
        self.assertEqual(report["status"], "PASS")

    def test_blocks_action_and_task_detail_re_adjudication(self):
        report = evaluate(["decode", "action_reasonableness", "microexpression_precision"])
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("FORBIDDEN_POST_GENERATION_QA:action_reasonableness", report["failures"])
        self.assertIn("FORBIDDEN_POST_GENERATION_QA:microexpression_precision", report["failures"])


if __name__ == "__main__":
    unittest.main()
