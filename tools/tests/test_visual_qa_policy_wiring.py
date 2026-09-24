"""visual_post_qa_policy must actually be consumed by vlm_review_protocol and
keyframe_q1_builder, not just defined in visual_review_policy — a policy
snapshot that drifts from the live policy must surface as a failure, never a
silent PASS."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(TOOLS))


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


with patch.dict(os.environ, {
    "NALU_ENGINE_ROOT": str(ROOT),
    "NALU_RUNTIME_ROOT": tempfile.mkdtemp(),
}):
    vrp = load("vlm_review_protocol")
    vrp_policy = load("visual_review_policy")


class ValidateAnswersPolicyWiring(unittest.TestCase):
    def test_missing_items_still_reports_policy_drift(self):
        stale = vrp_policy.policy_snapshot('WEAK')
        stale['policy_sha256'] = 'not-the-live-hash'
        request = {"kind": "keyframe", "questionnaire": {}, "items": [],
                   "visual_post_qa_policy": stale}
        failures, verdicts = vrp.validate_answers(request, "irrelevant-sha", {"items": []})
        self.assertTrue(any("visual_post_qa_policy_invalid" in f for f in failures))
        self.assertEqual(verdicts, [])

    def test_legacy_request_without_a_snapshot_is_not_flagged(self):
        request = {"kind": "keyframe", "questionnaire": {}, "items": [],
                   "visual_post_qa_profile": "STRICT"}
        failures, verdicts = vrp.validate_answers(request, "irrelevant-sha", {"items": []})
        self.assertFalse(any("visual_post_qa_policy" in f for f in failures))

    def test_valid_bound_snapshot_is_not_flagged(self):
        request = {"kind": "keyframe", "questionnaire": {}, "items": [],
                   "visual_post_qa_policy": vrp_policy.policy_snapshot('WEAK')}
        failures, verdicts = vrp.validate_answers(request, "irrelevant-sha", {"items": []})
        self.assertFalse(any("visual_post_qa_policy" in f for f in failures))


class Q1MaterialisePolicyWiring(unittest.TestCase):
    def test_drifted_snapshot_stops_the_batch_before_any_row_is_built(self):
        q1 = load("keyframe_q1_builder")
        stale = vrp_policy.policy_snapshot('WEAK')
        stale['policy_sha256'] = 'not-the-live-hash'
        submitted = {"questionnaire": {}, "items": [], "visual_post_qa_policy": stale}
        with self.assertRaisesRegex(ValueError, 'Q1_VISUAL_POST_QA_POLICY_INVALID'):
            q1.materialise("E_TEST", submitted, Path("/tmp/does-not-need-to-exist.json"))


if __name__ == '__main__':
    unittest.main()
