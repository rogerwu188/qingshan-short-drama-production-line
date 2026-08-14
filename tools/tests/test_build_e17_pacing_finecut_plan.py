import unittest

from tools.build_e17_pacing_finecut_plan import build


class E17PacingFinecutPlanTest(unittest.TestCase):
    def test_weave_preserves_frames_and_source_order(self):
        plan = {
            "fps": 24,
            "expected_frames": 240,
            "segments": [
                {"source_id": "A", "path": "a.mp4", "in_sec": 1.0, "duration_sec": 6.0, "expected_frames": 144},
                {"source_id": "B", "path": "b.mp4", "in_sec": 2.0, "duration_sec": 4.0, "expected_frames": 96},
            ],
        }
        result = build(plan, [(1, 2)], 72)
        self.assertEqual(result["expected_frames"], 240)
        self.assertEqual([row["source_id"] for row in result["segments"]], ["A", "B", "A", "B"])
        self.assertEqual([row["in_sec"] for row in result["segments"] if row["source_id"] == "A"], [1.0, 4.0])
        self.assertTrue(all(row["expected_frames"] <= 72 for row in result["segments"]))

    def test_tiny_remainder_is_balanced(self):
        plan = {
            "fps": 24,
            "expected_frames": 73,
            "segments": [
                {"source_id": "A", "path": "a.mp4", "in_sec": 0, "duration_sec": 73 / 24, "expected_frames": 73},
            ],
        }
        result = build(plan, [(1,)], 72)
        self.assertEqual([row["expected_frames"] for row in result["segments"]], [37, 36])

    def test_overlapping_groups_fail(self):
        plan = {
            "fps": 24,
            "expected_frames": 72,
            "segments": [
                {"source_id": "A", "path": "a", "in_sec": 0, "duration_sec": 1, "expected_frames": 24},
                {"source_id": "B", "path": "b", "in_sec": 0, "duration_sec": 1, "expected_frames": 24},
                {"source_id": "C", "path": "c", "in_sec": 0, "duration_sec": 1, "expected_frames": 24},
            ],
        }
        with self.assertRaises(ValueError):
            build(plan, [(1, 2), (2, 3)], 72)


if __name__ == "__main__":
    unittest.main()
