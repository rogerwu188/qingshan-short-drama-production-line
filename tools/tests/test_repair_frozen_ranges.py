import unittest

from tools.repair_frozen_ranges import frames_to_delete


class FrozenRangeRepairTest(unittest.TestCase):
    def test_keeps_first_frame_and_deletes_rest_of_each_localized_run(self):
        runs = [{"start_seconds": 33.0, "duration_seconds": 0.5}]
        self.assertEqual(frames_to_delete(runs, 24.0, 32.0, 9.0), list(range(25, 37)))


if __name__ == "__main__":
    unittest.main()
