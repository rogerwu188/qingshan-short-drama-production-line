import unittest

from tools.build_harvested_image_review_request import (
    shot_id_from_task_key,
    video_unit_id_from_state_id,
)


class HarvestedImageReviewRequestTest(unittest.TestCase):
    def test_state_task_key_maps_back_to_video_unit(self):
        state_id = shot_id_from_task_key("E29-CW-S02-SH05-C3-STILL-V1")

        self.assertEqual(state_id, "E29-CW-S02-SH05-C3")
        self.assertEqual(video_unit_id_from_state_id(state_id), "E29-CW-S02-SH05")

    def test_plain_shot_id_remains_unchanged(self):
        self.assertEqual(video_unit_id_from_state_id("E28-CW-S01-SH01"), "E28-CW-S01-SH01")


if __name__ == "__main__":
    unittest.main()
