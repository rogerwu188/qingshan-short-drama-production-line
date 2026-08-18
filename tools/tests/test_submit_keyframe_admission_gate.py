import unittest

from tools.submit_giggle_task_manifest import validate_keyframe_admissions


class SubmitKeyframeAdmissionGateTests(unittest.TestCase):
    def test_e40_variant_direct_submit_cannot_omit_formal_admission(self):
        failures = validate_keyframe_admissions(
            {"episode": "E40-REMAKE-V1"},
            [{"source_id": "R01", "reference_images": ["start.png"]}],
        )
        self.assertEqual(failures, ["FAIL_START_FRAME_ADMISSION_MISSING:R01"])

    def test_legacy_episode_is_not_retroactively_blocked(self):
        self.assertEqual(
            validate_keyframe_admissions({"episode": "E39"}, [{"source_id": "old"}]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
