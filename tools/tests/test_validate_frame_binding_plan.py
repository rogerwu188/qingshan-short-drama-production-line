import copy
import json
import unittest
from pathlib import Path

from tools.validate_frame_binding_plan import evaluate


BASE = Path(__file__).resolve().parents[2]
PLAN = json.loads(
    (BASE / "configs/e17_remake_full_binding_plan_v2_20260716.json").read_text(
        encoding="utf-8"
    )
)


class FrameBindingPlanTests(unittest.TestCase):
    def test_e17_full_binding_plan_passes(self):
        result = evaluate(PLAN)
        self.assertEqual(result["status"], "PASS", result["errors"])
        self.assertEqual(result["replacement_frames"], 761)
        self.assertEqual(result["schema"], "qingshan.frame_binding_validation.v2")
        self.assertEqual(result["check_count"], 13)
        self.assertIn(
            "EXCLUDED_SOURCE_RANGES_NOT_USED",
            {check["name"] for check in result["checks_performed"]},
        )

    def test_rejects_excluded_source_frames(self):
        plan = copy.deepcopy(PLAN)
        segment = plan["replacement_windows"][0]["segments"][1]
        segment["source_frames"] = [53, 68]
        result = evaluate(plan)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("excluded frames" in error for error in result["errors"]))

    def test_rejects_noncontiguous_output_segments(self):
        plan = copy.deepcopy(PLAN)
        plan["replacement_windows"][2]["segments"][1]["output_timeline_frames"] = [1589, 1656]
        result = evaluate(plan)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("not contiguous" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
