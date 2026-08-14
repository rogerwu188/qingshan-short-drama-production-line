import unittest

from tools.run_regression_ci import frame_repeat_stats


class FrameRepeatGateTests(unittest.TestCase):
    def test_real_progression_is_not_near_duplicate(self):
        hashes = [0, (1 << 32) - 1, (1 << 64) - 1, (1 << 96) - 1]
        stats = frame_repeat_stats(hashes)
        self.assertEqual(stats["near_duplicate_ratio"], 0.0)
        self.assertEqual(stats["max_nonadjacent_repeat_cluster"], 1)

    def test_nonadjacent_repeated_source_is_detected(self):
        base = (1 << 48) - 1
        hashes = [base, 0, base, 0, base]
        stats = frame_repeat_stats(hashes)
        self.assertGreater(stats["max_nonadjacent_repeat_cluster"], 2)


if __name__ == "__main__":
    unittest.main()
