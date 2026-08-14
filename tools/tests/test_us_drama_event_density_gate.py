import unittest

from tools.us_drama_event_density_gate import evaluate


class UsDramaEventDensityGateTests(unittest.TestCase):
    def sample(self):
        return {
            "episode": "E99",
            "pacing_standard": "US_DRAMA_PACING_V1",
            "runtime_target_seconds": {"min": 50, "target": 60, "max": 70},
            "event_density": {
                "planned_event_count": 4,
                "hard_min_per_minute": 4,
                "max_information_gap_seconds": 20,
                "non_advancing_percentage": 12,
            },
            "opening_hook": {"within_seconds": 3, "conflict": "already inside conflict"},
            "countdown": {"device": "clock"},
            "end_hook": {"line": "button"},
            "burst_segments": [{"duration_seconds": 25}],
            "structure": [{"beat_id": "B01", "target_seconds": 60, "new_information": "x", "power_shift": "y", "button": "z"}],
            "dialogue_draft": [{"text": "only one line"}],
        }

    def test_dialogue_density_is_not_a_hard_gate(self):
        report = evaluate(self.sample())
        self.assertEqual("PASS", report["status"])
        self.assertLess(report["observed"]["dialogue_lines_per_minute_reference"], 13)

    def test_event_density_is_a_hard_gate(self):
        data = self.sample()
        data["event_density"]["planned_event_count"] = 3
        report = evaluate(data)
        self.assertIn("event_density_below_hard_minimum", report["failures"])

    def test_non_advancing_atmosphere_is_a_hard_gate(self):
        data = self.sample()
        data["event_density"]["non_advancing_percentage"] = 16
        report = evaluate(data)
        self.assertIn(
            "non_advancing_atmosphere_percentage_exceeds_15", report["failures"]
        )

    def test_technique_fields_are_not_owned_by_density_gate(self):
        data = self.sample()
        data["countdown"] = None
        data["burst_segments"] = []
        data["structure"][0]["button"] = ""
        self.assertEqual("PASS", evaluate(data)["status"])


if __name__ == "__main__":
    unittest.main()
