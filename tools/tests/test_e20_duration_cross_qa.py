import unittest

from tools.build_e20_duration_and_cross_qa import build_duration, split_seconds


class E20DurationCrossQaTests(unittest.TestCase):
    def test_split_seconds_preserves_total(self):
        self.assertEqual(sum(split_seconds(22, 4)), 22)
        self.assertEqual(len(split_seconds(22, 4)), 4)

    def test_duration_uses_budgets_not_single_shot_permission(self):
        beat = {
            "runtime_target_seconds": {"target": 22},
            "dialogue_draft": [{"dia_id": "DIA-001"}],
            "structure": [
                {"beat_id": "B01", "target_seconds": 22, "segment_type": "dialogue"}
            ],
        }
        coverage = {
            "beat_sheet_sha256": "sha",
            "beat_coverage": [
                {
                    "beat_id": "B01",
                    "dialogue_ids": ["DIA-001"],
                    "planned_units": ["one", "two", "three", "four"],
                }
            ],
        }
        duration = build_duration(beat, coverage, "sha")
        self.assertEqual(duration["checks"]["unit_total_seconds"], 22)
        self.assertEqual(duration["checks"]["non_null_source_ids"], 0)
        self.assertTrue(
            all(
                unit["budget_is_not_single_shot_permission"]
                for row in duration["beats"]
                for unit in row["units"]
            )
        )


if __name__ == "__main__":
    unittest.main()
