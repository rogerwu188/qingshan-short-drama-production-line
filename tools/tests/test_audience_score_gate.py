import unittest

from tools.audience_score_gate import evaluate


def valid_report() -> dict:
    return {
        "episode": "E99",
        "technical_gate_status": "PASS",
        "viewing_passes": {"full_1x": True, "muted": True, "sound": True},
        "overall": 3.8,
        "verdict": "PASS",
        "dimensions": {
            "story": 4,
            "continuation": 4,
            "pacing": 3.5,
            "opening": 4,
            "clarity": 4,
            "visual": 3.5,
            "anti_ai": 3,
            "completeness": 4,
        },
        "hard_fail": [],
        "problems": [],
        "evidence": {
            "frame_grid": "frame.jpg",
            "asr": "asr.json",
            "semantic_group_pct": {"object": 10.0},
            "scene_rotation_table": "scenes.json",
            "burned_subtitles": True,
            "identity_color_consistent": True,
            "opening_10s_hook": True,
            "tail_5s_hook_intact": True,
            "narrative_stagnation": False,
        },
    }


class AudienceScoreGateTests(unittest.TestCase):
    def test_valid_pass_allows_release(self):
        result = evaluate(valid_report())
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["gate_status"], "PASS")
        self.assertTrue(result["release_allowed"])

    def test_score_under_three_rejects_with_problem(self):
        report = valid_report()
        report["overall"] = 2.9
        report["verdict"] = "REJECT_RECUT"
        report["problems"] = [{"t": "B02", "issue": "拖", "fix": "压缩"}]
        result = evaluate(report)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["gate_status"], "REJECT_RECUT")

    def test_hard_fail_rejects_even_with_high_score(self):
        report = valid_report()
        report["overall"] = 4.2
        report["verdict"] = "REJECT_RECUT"
        report["evidence"]["burned_subtitles"] = False
        report["problems"] = [{"t": "ALL", "issue": "无字幕", "fix": "烧字幕"}]
        result = evaluate(report)
        self.assertIn("missing_burned_subtitles", result["hard_fail"])
        self.assertFalse(result["release_allowed"])

    def test_semantic_over_budget_caps_pacing_and_visual(self):
        report = valid_report()
        report["verdict"] = "REJECT_RECUT"
        report["evidence"]["semantic_group_pct"] = {"box": 22.0}
        report["problems"] = [{"t": "B01", "issue": "重复盒子", "fix": "只留三次"}]
        result = evaluate(report)
        self.assertEqual(result["validation_status"], "FAIL")
        self.assertIn(
            "pacing_must_be_le_2_when_narrative_stagnation_or_semantic_over_15pct",
            result["validation_failures"],
        )

    def test_technical_fail_cannot_enter_audience_gate(self):
        report = valid_report()
        report["technical_gate_status"] = "FAIL"
        result = evaluate(report)
        self.assertEqual(result["gate_status"], "INVALID")

    def test_opening_or_tail_zero_tolerance_rejects(self):
        report = valid_report()
        report["verdict"] = "REJECT_RECUT"
        report["evidence"]["opening_10s_hook"] = False
        report["evidence"]["tail_5s_hook_intact"] = False
        report["problems"] = [{"t": "OPENING_TAIL", "issue": "hook failure", "fix": "recut"}]
        result = evaluate(report)
        self.assertIn("opening_10s_no_hook", result["hard_fail"])
        self.assertIn("tail_5s_hook_broken", result["hard_fail"])
        self.assertFalse(result["release_allowed"])


if __name__ == "__main__":
    unittest.main()
