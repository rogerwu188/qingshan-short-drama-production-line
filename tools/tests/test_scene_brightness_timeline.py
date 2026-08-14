import unittest

from tools.generate_scene_brightness_audit import validate_timeline


class SceneTimelineValidationTest(unittest.TestCase):
    def test_accepts_sorted_real_scene_map(self):
        rows = [
            {"shot_id": "1", "start": 0, "end": 2, "scene_id": "front"},
            {"shot_id": "2", "start": 2, "end": 4, "scene_id": "backyard"},
        ]
        self.assertEqual(validate_timeline(rows, ["front", "backyard"]), {"front", "backyard"})

    def test_rejects_wrong_scene_inventory(self):
        rows = [{"shot_id": "1", "start": 0, "end": 2, "scene_id": "front"}]
        with self.assertRaises(ValueError):
            validate_timeline(rows, ["front", "backyard"])

    def test_rejects_unsorted_timeline(self):
        rows = [
            {"shot_id": "2", "start": 2, "end": 4, "scene_id": "front"},
            {"shot_id": "1", "start": 0, "end": 2, "scene_id": "front"},
        ]
        with self.assertRaises(ValueError):
            validate_timeline(rows, ["front"])


if __name__ == "__main__":
    unittest.main()
