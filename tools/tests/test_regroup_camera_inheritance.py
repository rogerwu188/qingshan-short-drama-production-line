import unittest

from tools.regroup_e50_v5_sd2_overlength_units import camera_for_chunk


class RegroupCameraInheritanceTest(unittest.TestCase):
    def test_every_child_inherits_camera_plan_byte_for_byte(self) -> None:
        camera = {
            "motion_family": "PAN", "motion_direction": "LEFT_TO_RIGHT",
            "shot_scale": "MEDIUM", "camera_side": "AXIS_A",
            "start_framing": "门口双人中景", "end_framing": "桌边双人中景",
            "motivation": "随证物交接右摇", "signature": "PAN:LEFT_TO_RIGHT",
            "camera_height": "EYE_LEVEL", "lens_intent": "35mm",
            "axis_relation": "不越轴",
        }
        specs = [{"action": {"start_state": "门口", "completion_state": "桌边"}}]
        self.assertEqual(camera_for_chunk(camera, specs, child_index=0, parent_id="VU"), camera)
        self.assertEqual(camera_for_chunk(camera, specs, child_index=1, parent_id="VU"), camera)
        self.assertEqual(camera["motion_family"], "PAN")


if __name__ == "__main__":
    unittest.main()
