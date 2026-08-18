import json
import unittest
from pathlib import Path

from tools.us_drama_event_density_gate import discover_history_manifests, evaluate


FIXTURES = Path(__file__).parent / "fixtures"


class UsDramaEventDensityGateTests(unittest.TestCase):
    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def sample(self):
        return self.fixture("us_drama_pacing_v2_e41_positive.json")

    def test_e41_v4_sanitized_structure_fixture_passes(self):
        report = evaluate(self.sample())
        self.assertEqual("PASS", report["status"])
        self.assertTrue(report["structure_enforcement"]["effective"])
        self.assertEqual(
            "manifest.pacing_v2.location_list",
            report["observed"]["structure_v2"]["location_count_basis"],
        )

    def test_e40_v3_five_scene_single_location_is_negative_when_enforced(self):
        report = evaluate(
            self.fixture("us_drama_pacing_v2_e40_legacy_negative.json"),
            structure_mode="enforce",
        )
        self.assertEqual("FAIL", report["status"])
        self.assertIn("SCENE_COUNT_OUT_OF_RANGE", report["failures"])
        self.assertIn("SINGLE_LOCATION_EPISODE", report["failures"])

    def test_e40_structure_findings_are_warning_only_in_auto_backtest(self):
        report = evaluate(self.fixture("us_drama_pacing_v2_e40_legacy_negative.json"))
        self.assertEqual("PASS", report["status"])
        self.assertIn("BACKTEST_ONLY:SCENE_COUNT_OUT_OF_RANGE", report["warnings"])

    def test_e41_missing_pacing_v2_fails_closed(self):
        data = self.sample()
        del data["pacing_v2"]
        report = evaluate(data)
        self.assertIn("PACING_V2_MISSING", report["failures"])

    def test_dialogue_density_is_not_a_hard_gate(self):
        data = self.sample()
        data["dialogue_draft"] = [{"text": "one line"}]
        report = evaluate(data)
        self.assertEqual("PASS", report["status"])
        self.assertLess(report["observed"]["dialogue_lines_per_minute_reference"], 13)

    def test_event_density_is_a_hard_gate(self):
        data = self.sample()
        data["event_density"]["planned_event_count"] = 3
        data["pacing_v2"].pop("events_per_minute", None)
        report = evaluate(data)
        self.assertIn("event_density_below_hard_minimum", report["failures"])

    def test_non_advancing_atmosphere_is_a_hard_gate(self):
        data = self.sample()
        data["event_density"]["non_advancing_percentage"] = 16
        report = evaluate(data)
        self.assertIn("non_advancing_atmosphere_percentage_exceeds_15", report["failures"])

    def test_each_structure_failure_code(self):
        mutations = {
            "SCENE_COUNT_OUT_OF_RANGE": ("scene_count", 7),
            "SCENE_TOO_LONG": ("max_scene_seconds", 23),
            "LOCATION_STAGNATION": ("max_consecutive_same_location", 3),
            "NO_TIME_JUMP": ("time_jumps", 0),
            "NO_PARALLEL_THREAD": ("parallel_threads", 1),
            "TOO_FEW_CROSS_CUTS": ("cross_cuts", 2),
            "SCENE_WITHOUT_TURN": ("scenes_without_turn", 1),
            "LOCATION_BUDGET_EXCEEDED": ("new_locations_added", 3),
        }
        for code, (field, value) in mutations.items():
            with self.subTest(code=code):
                data = self.sample()
                data["pacing_v2"][field] = value
                self.assertIn(code, evaluate(data)["failures"])

    def test_dialogue_ratio_and_event_causal_form(self):
        data = self.sample()
        data["pacing_v2"]["dialogue_ratio"] = 0.36
        data["pacing_v2"]["event_list"] = ["only a description"]
        report = evaluate(data)
        self.assertIn("DIALOGUE_RATIO_EXCEEDED", report["failures"])
        self.assertIn("EVENT_NOT_IN_CAUSAL_FORM", report["failures"])

    def test_three_equal_consecutive_scene_counts_require_justification(self):
        data = self.sample()
        data["episode"] = "E43"
        history = []
        for episode in (41, 42):
            row = self.sample()
            row["episode"] = f"E{episode}"
            history.append(row)
        report = evaluate(data, history_manifests=history)
        self.assertIn("MECHANICAL_SCENE_TEMPLATE", report["failures"])
        data["pacing_v2"]["scene_count_justification"] = "The causal braid requires eleven scenes."
        self.assertNotIn(
            "MECHANICAL_SCENE_TEMPLATE",
            evaluate(data, history_manifests=history)["failures"],
        )

    def test_history_discovery_selects_latest_prior_episode_manifests(self):
        paths = discover_history_manifests(
            Path("workflow/claude_writer_agent/scripts/E43_manifest_v3.json"), "E43"
        )
        self.assertEqual(["E41_manifest_v4.json", "E42_manifest_v4.json"], [path.name for path in paths])


if __name__ == "__main__":
    unittest.main()
